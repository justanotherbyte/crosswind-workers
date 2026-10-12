# Tracker

The build runs in six phases, numbered 0 to 5. Each phase ends with something that runs and passes the checkpoint. The slices come from [wynd.md](wynd.md#implementation-plan) and [crosswind-workers.md](crosswind-workers.md#implementation-plan), which define each slice's done-condition. Work one slice per session, test first, then tick its box and commit.

## Python rules

These apply to both packages.

1. Don't use `typing.cast`. It hides a type the checker can't prove. Narrow with `isinstance`, or fix the type at its source.
2. Follow PEP 8. Ruff enforces it with line length 88, ruff's default and inside PEP 8's allowance for teams.
3. Lint and type-check with `uvx ruff` and `uvx ty` at every checkpoint.

Each package's `pyproject.toml` encodes rules 1 and 2:

```toml
[tool.ruff.lint]
extend-select = ["E", "W", "N", "I", "TID251"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"typing.cast".msg = "Narrow with isinstance or fix the type instead of casting."
```

## Checkpoint

Run these from inside `wynd/` or `crosswind-workers/`. Each package is checked on its own.

```sh
uv run pytest
uvx ruff format --check
uvx ruff check
uvx ty check
```

A slice is done when all four pass and its done-condition from the spec holds.

## Phase 0: setup

- [x] `git init` in `helm/`
- [x] Both packages: `requires-python = ">=3.12"`. crosswind's `.python-version` is `3.12`.
- [x] Both packages: the ruff config above, a `dev` dependency group with pytest, a `tests/` with one import test (pytest exits 5 when it collects nothing), and a passing checkpoint.
- [x] Wynd: `[project.scripts] wynd = "wynd.cli:main"` and the `json-with-comments` dependency.
- [x] crosswind: ty resolves `js`, `pyodide.ffi` and the workerd helper modules. The stock SDK ships `.pyi` stubs for the helpers. Check whether `pyodide-py` covers `js`.
  - Result: it doesn't. `pyodide-py` covers `pyodide` only, and 314.x needs Python 3.14, so uv pins 0.27.8 on 3.12. `crosswind-workers/stubs/` holds `js.pyi` and the helper stubs, outside the wheel, found through ty's `extra-paths`. The helper stub drops `patch_env_helper`, which workerd removed in `6581cf0`.

Done when the checkpoint passes in both packages, which still contain no real code.

## Phase 1: first request

- [x] Wynd 1. Passthrough: the dispatcher, the runner and the pin. `wynd whoami` behaves like `wrangler whoami`.
- [x] crosswind 1. Tracer: the five names workerd imports, a minimal `Request` and `Response`, and the `on_*` aliases. It runs first under plain `wrangler dev` with the SDK copied into the fixture.
  - Result: `uv run pytest -m e2e` answers on 3.12 (2025-06-01, legacy `on_fetch`), 3.13 and 3.14. The alias set follows workerd's source, not the old spec list (see [decisions](decisions.md#contract-with-workerd)).
- [x] Wynd 2. Dev on the full tree: the project loader, target table, SDK selector, resolver, installer, sync token and host check. The tracer then moves to `wynd dev`.
  - Result: `uv run pytest -m e2e` passes in both packages, with a stock-SDK fixture in Wynd and the crosswind tracer, built from its local path, on 3.12 (2025-06-01), 3.13 and 3.14. The installer uses `uv pip install --target` instead of a Pyodide venv, and `dev` runs Wrangler from the working directory (see [wynd.md](wynd.md#modules)).
- [x] Spike. A 20-line Worker whose step callback returns a rejecting thenable with a `NonRetryableError`-named error. Does the Workflows engine stop retrying?
  - Result: yes, in the local engine on all three targets. With two retries allowed, the thenable named `NonRetryableError` ran once, and the same thenable named `OtherError` ran three times. `run` receives the step error as `Error: NonRetryableError: stop`. `uv run pytest -m e2e -k thenable` in crosswind reproduces all of it. The pure-Python wheel decision stands. On 2026-10-12 the same Worker, deployed with wrangler 4.129.0 to production on 2025-06-01 (3.12), 2025-10-01 (3.13) and 2026-09-08 (3.14), gave the same result on all three: `NonRetryableError` once, `OtherError` three times, each instance `complete`. Still open for crosswind 9: attempt counts across engine replays (the spike counts in a module global, and no replay happened in these runs), and a `NonRetryableError` that escapes `run`.

Done when a crosswind Worker answers HTTP under `wynd dev` on 3.12, 3.13 and 3.14, including a date before 2025-08-14. If the spike fails, revisit the pure-Python wheel decision now, before any crosswind design rests on it.

## Phase 2: an SDK you can write Workers with

- [x] crosswind 2. Boundary conversion
  - Result: `python_from_rpc` and `python_to_rpc` follow the stock rules. `uv run pytest -m e2e -k rpc_e2e` round-trips the stock RPC test's values between two entrypoints on all three targets. The check for unsendable types walks iterables as stock does but skips one-shot iterators, so a generator is no longer consumed. `Blob`, `FormData` and `File` pass through as JS values until crosswind 3. As in the stock SDK, a JS `Error` that crosses twice reads `Error: Error: message`.
- [x] crosswind 3. HTTP types
  - Result: `Request`, `Response`, `FetchResponse`, `fetch`, headers, `Blob`, `File` and `FormData` are ported from the stock SDK, with `FetchResponse` still built on Pyodide's. `uv run pytest -m e2e -k http_e2e` runs the stock HTTP unit tests that don't need `env`, plus one test per fixed stock bug, inside workerd on all three targets. The fixed bugs are a JS `File` over RPC, `len()` and missing keys on `FormData`, `Response(blob)`, non-standard methods, `memoryview` and `bytearray` Blob parts, and `Response.redirect`. `Response.json` became a descriptor, so `Response.json(data)` and `await response.json()` both type-check. `Request.cf` is typed `Any`.
- [x] crosswind 4. Env and bindings
  - Result: `workers.bindings` has `Binding`, `KVNamespace`, `D1Database` (with `D1PreparedStatement`), `R2Bucket` (with `R2Object` and `R2ObjectBody`), `Queue`, `DurableObjectNamespace[T]`, `Fetcher`, `Workflow` and `WorkflowInstance`. Entrypoints wrap `env`. `uv run pytest -m e2e -k bindings_e2e` drives real local KV, D1, R2, a Queue producer, Durable Object RPC, service `fetch` and RPC, a Workflow, text and JSON vars and version metadata on all three targets. `tests/test_typing.py` shows ty following `WorkerEntrypoint[Env]` through `get_by_name` to the Durable Object class. Entrypoints are generic only to type checkers, so `Generic[S]` mixes in before or after at runtime. Type checkers need it last. Stub RPC calls must be positional (see [crosswind-workers.md](crosswind-workers.md#modules)). Typed methods also accept the stock SDK's positional options, as a dict or a JS object, and namespace attributes such as `idFromName` stay raw as in stock. Two stock bugs are fixed: non-callable attributes are read fresh on each access, and `env` and Durable Object namespaces are sent over RPC as their JS objects.
- [ ] crosswind 5. Durable Objects and context
- [ ] crosswind 6. Module globals
- [ ] Wynd 3. SDK exclusion with `--excludes`

Done when a fixture Worker that uses KV, D1, R2, a Durable Object and RPC between entrypoints runs under `wynd dev`, and `workers.bindings` exists with its final class names.

## Phase 3: shipping

- [ ] Wynd 4. The stager and config path rewrite, without pruning
- [ ] Wynd 5. The shaker and size report
- [ ] Wynd 6. `versions upload` and `preview` use the deploy flow

Test the shaker against real Pyodide installs of FastAPI and pydantic as well as synthetic packages. Run the end-to-end check before the first real deploy, so a broken prune never uploads. The first real deploy also shows whether `site.bucket` works as an absolute path.

Done when `wynd deploy --dry-run` reports fewer bytes, the pruned fixture still answers its end-to-end request, and a real deploy succeeds.

## Phase 4: types

- [ ] Wynd 7. Typegen, `wynd types --check`, and render-and-compare inside dev and deploy

This waits for phase 2, because typegen imports the class names from `workers.bindings`. The research tested Pyright and mypy, not ty, so this phase also checks whether ty accepts the generated `Env` protocol and the Durable Object generic. If it doesn't, run Pyright alongside ty for this check or change the generated shape.

Done when the fixture's generated `env.py` type-checks, imports at runtime, and `--check` fails after the config changes.

## Phase 5: the ecosystem

- [ ] crosswind 7. Entropy patches, with numpy and pydantic fixtures built by Wynd as an outside tool. Record which patches are still needed.
- [ ] crosswind 8. ASGI and WSGI adapters, proven with FastAPI and Flask fixtures
- [ ] crosswind 9. Workflows, built on the spike's thenable
- [ ] crosswind 10. The conflict guard, the stock SDK's tests run against crosswind, and the agents `verify` Worker under both toolchains

Done when the stock SDK's workerd tests and agents `verify` pass against crosswind.

## Order

Phase 1 joins both packages in the real runtime early, so later phases build on a path already proven end to end. Phases 2 and 3 can overlap, because phase 3 needs only a Worker that runs. Phase 4 waits for the binding class names, and phase 5 waits for Wynd sync, because its fixtures need Pyodide packages.

The two biggest risks, the thenable and the shaker on real packages, are tested in phases 1 and 3, before anything depends on them.
