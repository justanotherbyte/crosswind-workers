# Production deploy checks

Resolution of the "Production snapshot precedence" and "Entropy patches without the hook" tasks in the [crosswind-workers map](../crosswind-workers.md). Run on 2026-10-11 with wrangler 4.129.0 against the user's Cloudflare account. All test Workers and the KV namespace were deleted afterwards.

## Production snapshot precedence

**Setup.** A Worker with compatibility date `2025-06-01` and flags `["python_workers"]`, which selects Python 3.12. It vendored the stock SDK (`workers-runtime-sdk` 1.9.3) in `python_modules/workers/`, with `HELM_MARKER = "vendored"` appended.

The development machine's ISP (EE) blocks `*.workers.dev`. HTTP redirects to `block.ee.co.uk`, and HTTPS and `wrangler tail` fail with TLS errors. So the Worker reported through a one-minute cron trigger that wrote to a KV namespace, which was read back through `api.cloudflare.com`.

**Result.** The cron run wrote:

```
file=/session/metadata/python_modules/workers/__init__.py
marker=vendored
python=3.12.1
workers_modules=1
mro=['main.Default', 'workers.entrypoints.WorkerEntrypoint', 'builtins.object']
```

The vendored `workers` package wins in production on a 3.12 date, as it did in local `wrangler dev`. Only one `workers` module was loaded, and workerd routed to a class built on the vendored `WorkerEntrypoint`.

**Side findings.**

- The cron called the class's `scheduled` method. It did not call `on_scheduled` on the class or the module-level `on_scheduled`, even though the date is before 2025-08-14. Local `wrangler dev` had called `on_fetch` for HTTP on the same kind of date. The `on_*` rename may apply only to some handlers. The HTTP rerun below confirmed that production calls the class's `on_fetch` on this date.
- The first deploy declared `scheduled(self, controller, env=None, ctx=None)` and wrote nothing over about six cron runs. The second declared `scheduled(self, *args)`, wrapped the work in `try`/`except`, and wrote on its first run. Logs weren't reachable, so the cause is unknown. A signature mismatch at the call boundary is one possibility.

## Entropy patches without the hook

**Setup.** Three Workers that do `import numpy` and `import numpy.random` at the top level, with numpy 2.2.5 and the stock SDK resolved for Pyodide 3.13 (`index.pyodide.org/0.28.3`), and uv's `_virtualenv` files removed.

| Worker | Date | `python_process_pth_files` | SDK `.pth` hook | Deploy |
| --- | --- | --- | --- | --- |
| hook, flag on | 2026-06-01 | on | present | succeeded |
| no hook, flag on | 2026-06-01 | on | removed | succeeded |
| no hook, flag off | 2026-05-01 | off | removed | succeeded |

**Result.** Cloudflare's upload-time validation, which runs top-level imports and takes the snapshot, accepted all three. The predicted "Disallowed operation called within global scope" failure did not happen for numpy 2.2.5 without the patches. The first run couldn't reach the Workers' responses, so it showed only that deploy succeeds. The HTTP rerun below covers runtime behavior.

**What this does not settle.** The stock patch set also covers pydantic_core, aiohttp, tiktoken, jiter, opentelemetry, fastapi and others. Only numpy was tested, and only one version. Whether any patch is still needed today is open. The decision to port the patches stands, because the ticket blocked nothing and the cost of a missing patch is a failed deploy.

## HTTP rerun

On the same day, after the network block was lifted, all four Workers were redeployed with `fetch` handlers and checked over HTTP, then deleted.

**Handler names.** The precedence Worker defined a class `fetch`, a class `on_fetch` and a module-level `on_fetch`, each returning its own name. Production called the class's `on_fetch` on the 2025-06-01 date. The vendored `workers` package won again, with one copy loaded.

**Generator state across isolates.** Each entropy Worker drew one `numpy.random.random()` and one `random.random()` on the first request each isolate served, and tagged the isolate with 4 bytes from `os.urandom`. Forty parallel requests per Worker reached between 9 and 15 isolates. In all three Workers, every isolate drew different first values from both generators, so no isolate inherited generator state from the snapshot. Five requests to each of two Workers returned Cloudflare's `error code: 1042`. The section below explains why.

**Answer.** On 2026-06-01 and 2026-05-01 dates, numpy 2.2.5 deploys and seeds itself per isolate without the stock patches. The same goes for the stdlib `random` module. The other patched packages are still untested.

## Error 1042 after a first deploy

Cloudflare's [Workers error docs](https://developers.cloudflare.com/workers/observability/errors/) give two causes for 1042: a Worker fetching another Worker on the same zone, and "a `workers.dev` URL with no Worker serving it". The test Workers make no subrequests, so the second cause was the suspect. The first deploy of a Worker creates its `workers.dev` hostname, and the requests above started within seconds of the deploys finishing.

A Worker named `crosswind-test-1042`, a copy of the no-hook numpy Worker, was deployed and probed with 10 parallel requests every 2 seconds:

| Time after deploy | 1042 responses out of 10 |
| --- | --- |
| 1 s | 10 |
| 3 s | 10 |
| 7 s | 3 |
| 11 s to 72 s | 0 |

A second deploy to the same name followed. Eight probes starting 2 seconds after it returned no 1042s, and a 40-request burst on the warm Worker returned none either.

**Answer.** The 1042s come from the new `workers.dev` hostname reaching Cloudflare's servers over about 10 seconds after a Worker's first deploy. They are not caused by cold starts, concurrency or the Python runtime. Redeploying an existing name doesn't produce them. A test that deploys a new Worker name should retry 1042 for about 30 seconds before treating it as a failure.
