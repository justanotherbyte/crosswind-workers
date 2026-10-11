# crosswind-workers

Spec and implementation plan for crosswind-workers, the runtime SDK that replaces `workers-runtime-sdk`. It is published as `crosswind-workers` and imported as `workers`. Settled decisions live in [decisions.md](decisions.md). The CLI that builds and ships it has its own spec in [wynd.md](wynd.md).

## Problem statement

A developer writing a Python Worker depends on the stock `workers-runtime-sdk` for the classes workerd routes to, for request and response types, and for binding access. Most of that SDK passes JS objects through with little typing. `self.env.MY_DB` has no type the editor understands, many calls return `JsProxy` values, and the developer often has to learn Pyodide's FFI to finish ordinary work.

The SDK's conventions also work against Python. It exports both `waitUntil` and `wait_until`, serves `env` through a module `__getattr__`, leaks the private `_EnvWrapper`, and exports `patch_env`, which calls a workerd helper that no longer exists. `DurableObject.__init_subclass__` doesn't call `super()`, so the agents port has to put `Generic` first in its base list to make generics work.

Library authors porting Cloudflare's agents and containers SDKs to Python need one code path that works whichever SDK a project uses. Today the only SDK forces its own dependency into every project.

## Solution

crosswind-workers is a from-scratch SDK with the same import name, the same public names and the same observable behavior as the stock SDK, plus typing and Pythonic methods layered on top.

- Existing Workers and libraries written against the stock SDK run unchanged.
- `WorkerEntrypoint[Env]`, `DurableObject[Env]` and typed binding classes in `workers.bindings` give editors full types, using an `Env` that Wynd generates from the Wrangler config.
- Binding and context wrappers have async snake_case methods that take and return Python values, while camelCase JS calls still pass through.
- Every wrapper exposes its JS object as `js_object` and accepts a JS object in its constructor, which is the single way to drop down to FFI.
- Workflows run in pure Python, so the wheel contains only Python files.
- The stock SDK's entropy patches are ported, so numpy, pydantic, FastAPI and similar packages import at the top level.

## User stories

1. As a Worker developer, I want `from workers import WorkerEntrypoint, Request, Response` to work exactly as with the stock SDK, so that my existing Worker runs unchanged.
2. As a Worker developer, I want workerd to route requests to my `WorkerEntrypoint` subclass, so that a class with an async `fetch` is all I need.
3. As a Worker developer, I want my `DurableObject` subclasses constructed with `ctx` and `env` and routed by workerd, so that Durable Objects work like the stock SDK's.
4. As a Worker developer, I want my `WorkflowEntrypoint` subclasses and their steps to run without any JavaScript helper, so that Workflows work from a Python-only wheel.
5. As a Worker developer on a compatibility date before 2025-08-14, I want to write `fetch`, `scheduled`, `queue` and `alarm`, so that I never need to know workerd calls `on_fetch` on old dates.
6. As a Worker developer, I want `await request.json()`, `await request.text()` and `await request.bytes()` to return Python values, so that I never handle a `JsProxy` for a request body.
7. As a Worker developer, I want to return `Response("text")`, `Response(b"bytes", status=201, headers={...})` or `Response.json(data)`, so that I build responses from Python values.
8. As a Worker developer, I want `class Default(WorkerEntrypoint[Env])` to give `self.env` my generated `Env` type, so that my editor checks binding names and methods.
9. As a Worker developer, I want KV, D1, R2 and Queue bindings to have typed async methods that take and return Python values, so that storage code reads like ordinary Python.
10. As a Worker developer, I want `self.env.COUNTER.get_by_name("x")` typed as my Durable Object class, so that the type checker catches wrong RPC method names and arguments.
11. As a Worker developer, I want service bindings to support `fetch` and RPC calls, so that I can call other Workers.
12. As a Worker developer, I want RPC arguments and results converted between Python and JS automatically, so that Worker-to-Worker calls feel like Python calls.
13. As a Worker developer, I want `self.ctx.wait_until(coroutine)` to keep the request alive until the coroutine finishes, so that background work completes.
14. As a Worker developer, I want `self.ctx.storage` to have typed snake_case methods, so that Durable Object storage code is checked.
15. As a Worker developer migrating from the stock SDK, I want camelCase JS calls such as `self.ctx.storage.deleteAll()` to keep working, so that I can migrate one call at a time.
16. As a Worker developer, I want `js_object` on every wrapper, so that I can reach any JS API the SDK doesn't wrap.
17. As a Worker developer, I want every wrapper's constructor to accept a JS object, so that I can wrap results from raw JS calls.
18. As a Worker developer, I want `alarm` and WebSocket handlers on my Durable Object to receive Python wrappers, so that those handlers look like every other handler.
19. As a Worker developer, I want `fetch(url, method=..., headers=..., body=...)` for outbound HTTP with Python keyword arguments, so that outbound requests need no FFI.
20. As a Worker developer, I want `FormData`, `Blob` and `File`, so that I can handle multipart bodies and uploads.
21. As a Worker developer, I want the `asgi` adapter to serve a FastAPI app, so that I can deploy an existing FastAPI service as a Worker.
22. As a Worker developer, I want the `wsgi` adapter to serve a Flask app, so that WSGI frameworks run too.
23. As a Worker developer, I want module-level `env` and `wait_until`, so that code outside a handler can reach bindings like it can with the stock SDK.
24. As a Worker developer, I want `import_from_javascript("cloudflare:sockets")`, so that I can reach runtime modules the SDK doesn't wrap.
25. As a Worker developer, I want `import numpy` or `import fastapi` at the top of my module to deploy, so that snapshot creation doesn't reject my imports.
26. As a Worker developer, I want a clear error if `workers-runtime-sdk` is installed alongside crosswind-workers, so that I find the conflict before debugging odd behavior.
27. As a Worker developer, I want my code to behave the same on Python 3.12, 3.13 and 3.14 targets, so that upgrading Python doesn't change my program.
28. As a Worker developer, I want `class Counter(DurableObject)` without type arguments to work, so that generics stay optional.
29. As a library author, I want `class Agent(Generic[S], DurableObject)` and `class Agent(DurableObject, Generic[S])` both to work, so that base-class order doesn't matter.
30. As a library author, I want one code path that runs on the stock SDK and on crosswind-workers, so that I don't maintain two.
31. As a library author, I want `js_object`, JS-object constructors and camelCase passthrough to behave identically on both SDKs, so that my FFI code is portable.
32. As a library author, I want `python_from_rpc` and `python_to_rpc` with the stock SDK's semantics, so that my Durable Object RPC code is portable.
33. As a library author, I want my library to declare no SDK dependency, so that the project chooses which SDK ships.
34. As a Worker developer, I want crosswind-workers to install as a pure-Python wheel, so that installing it works on any machine and for any target.
35. As a Worker developer, I want crosswind-workers to hold no JS objects when imported, so that snapshot creation never fails because of the SDK.
36. As a Worker developer, I want the SDK to type-check under Pyright using only Python 3.12 features, so that the lowest target and my editor agree.
37. As a crosswind maintainer, I want most behavior tested on the host against a fake JS layer, so that the main test suite runs in seconds.
38. As a crosswind maintainer, I want integration tests in workerd for every target date, so that routing, snapshots and real bindings are proven.
39. As a crosswind maintainer, I want the stock SDK's own workerd tests to pass against crosswind-workers, so that "same observable behavior" is measured rather than claimed.
40. As a crosswind maintainer, I want the agents port's `verify` Worker to pass under both toolchains in CI, so that library compatibility is measured too.

## Implementation decisions

### Modules

**Entrypoints.** `WorkerEntrypoint`, `DurableObject` and `WorkflowEntrypoint`, all generic over an optional `Env` type. `__init_subclass__` calls `super()`, wraps the methods workerd calls with raw JS proxies (`connect`, Durable Object `alarm`, the `webSocket*` handlers and Workflow `run`) so they receive Python wrappers, and defines `on_fetch`, `on_scheduled`, `on_queue` and `on_alarm` as aliases for the short names. The constructor wraps `ctx` and `env` before user code sees them. Nothing in the SDK resolves annotations on `Env` or user classes at runtime, because the generated `Env` refers to classes that exist only for type checkers. Workers' own exceptions such as `DurableObjectAbort`, and the `handler` decorator, keep their stock meaning.

**Boundary conversion.** `python_from_rpc` and `python_to_rpc`, which workerd calls on every class-method argument and return value. Their conversion rules match the stock SDK's exactly. `python_to_rpc` on a crosswind `Response` returns its `js_object`, which is the JS `Response` workerd requires from `fetch`.

**HTTP types.** `Request`, `Response`, `FetchResponse`, `fetch`, headers handling, `Blob`, `File`, `FormData` and the body and keyword-argument types the stock SDK exports. Bodies are read lazily through async methods. Constructors accept either Python values or a JS object.

**Bindings.** `workers.bindings` holds one typed class per covered binding type, plus a generic passthrough wrapper for the rest. The `Env` wrapper decides which class wraps each binding by its JS constructor name, as the stock SDK does. `DurableObjectNamespace[T]` returns stubs typed as `T`. Every binding class has typed methods written by hand, each with an explicit signature and its own conversions. A name the class doesn't define is a passthrough to the JS object under its exact JS name, using the stock conversion rules. There is no automatic snake_case-to-camelCase translation. A typed method always wins over passthrough. Typed methods take snake_case keywords (`expiration_ttl=60`) and forward any keyword they don't recognize into the JS options object unchanged, so stock calls such as `kv.put("k", "v", expirationTtl=60)` keep working. Every binding class exposes `js_object`. v1 has typed classes for KV, D1, R2, Queue producers, Durable Object namespaces, service and assets `Fetcher`s, and Workflows. Text vars and secrets are `str`, and JSON vars are converted to Python values. Every other binding is a `Binding` passthrough.

**Context.** Wrappers for the execution context and the Durable Object state. They expose `js_object`, typed snake_case methods (`wait_until`, `storage.get`, `storage.put`, `storage.delete_all` and so on), and forward every other attribute, including camelCase names, to the JS object. `wait_until` accepts a coroutine.

**Module globals.** Module-level `env`, `wait_until`, `waitUntil` and `import_from_javascript`, served as the stock SDK serves them. `patch_env` was meant to swap `env` for the duration of a `with` block, but workerd removed the helper it calls on 2026-06-30, so the stock version raises `AttributeError`. crosswind exports the name and raises `NotImplementedError` with that explanation.

**Adapters.** `asgi` and `wsgi`, with the stock SDK's entry functions and behavior.

**Workflows.** Step wrapping, `sleep`, `sleep_until`, `wait_for_event`, step configuration and retries in pure Python. The stock SDK already does all of this in Python. Its JavaScript helper does one job: it turns a Python `NonRetryableError` into a JS `Error` named `NonRetryableError`, which is the name the Workflows engine checks. A Python `raise` can't produce that error, because Pyodide always wraps it in a fresh `PythonError`. crosswind's step callback instead catches `NonRetryableError` and returns a JS thenable whose `then` calls `reject` with the named error, and the engine adopts the rejection. This works on all three targets because it needs only `await`. It is untested in workerd.

**Entropy patches.** The stock SDK's per-package patches, ported as private modules and loaded by a `.pth` hook. The loader skips patches for packages that aren't installed. Wynd's shaker keeps them because it treats `.pth` imports as roots.

**Stock-conflict guard.** At import, `workers` checks `importlib.metadata` for a `workers-runtime-sdk` distribution and raises an error naming both packages and pointing at Wynd. The guard runs only if crosswind's files survived any overwrite.

### Contract with workerd

These facts come from workerd at commit `d08010b` and the local `wrangler dev` test. The decisions file records the detail.

- workerd imports `DurableObject`, `WorkerEntrypoint`, `WorkflowEntrypoint`, `python_from_rpc` and `python_to_rpc` from `workers` and routes with `issubclass`. All five must exist from the first slice.
- A vendored `workers` package wins over workerd's builtin copy on every target.
- On dates before 2025-08-14 workerd calls `on_fetch` on the class.
- The SDK must hold no JS object at import time other than the helper module, the compatibility flags and `doAnImport` import proxies.
- 3.12 lacks `run_sync`. The async-only API doesn't need it.

### API shape

Typed and FFI usage side by side. The generated `Env` comes from Wynd.

```python
class Default(WorkerEntrypoint[Env]):
    async def fetch(self, request: Request) -> Response:
        counter = self.env.COUNTER.get_by_name("global")   # typed as Counter
        value = await counter.increment(by=2)
        await self.env.CACHE.put("last", str(value))
        raw = self.env.CACHE.js_object                      # JS KVNamespace
        return Response.json({"value": value})
```

### Package constraints

- `requires-python = ">=3.12"`, with no runtime dependencies, including `typing_extensions`.
- The distribution name is `crosswind-workers` and the module is `workers`, set through `[tool.uv.build-backend] module-name`.
- The wheel contains Python files, `.pth` files and `py.typed` only.

## Testing decisions

A good test calls the public `workers` API the way a Worker or library does and checks what that code observes: return values, raised exceptions, and what reached the JS side. Tests don't reach into private modules or assert on how a wrapper stores its JS object.

Proposed seams, which still need your confirmation:

1. **The public `workers` API on the host, with a fake JS layer.** A fake `js`, `pyodide.ffi`, `_pyodide_entrypoint_helper` and `_cloudflare_compat_flags` sit in `sys.modules`. Tests subclass the entrypoints, call `fetch` and RPC methods the way workerd would, and inspect what the fake JS side received. This covers conversion rules, wrappers, aliases, generics and the conflict guard.
2. **Real workerd through Wynd.** Small fixture Workers run under `wynd dev` on one date per target (3.12, 3.13 and 3.14) and answer HTTP requests. Routing, the `on_*` aliases on old dates, snapshots with the entropy patches, real local bindings (KV, D1, R2, Durable Objects) and the ASGI and WSGI adapters are proven here.
3. **Conformance against the stock SDK.** The stock SDK's own workerd and web-framework tests run against crosswind-workers. The agents port's `verify` Worker runs under pywrangler with the stock SDK and under Wynd with crosswind-workers.

Prior art: the agents port's fake FFI and fake `workers` modules are the model for seam 1. The stock SDK's in-workerd tests, bindings test Worker and FastAPI, Flask and Django tests are the model for seam 2 and the source for seam 3. The design review's SDK-precedence experiment showed the `wrangler dev` harness works on all three targets.

## Out of scope

- Module-level `on_fetch` style handlers, planned for after v1.
- Support for running under pywrangler, which waits on a pywrangler PR.
- Re-exporting `pyodide.ffi` helpers.
- Rewriting the entropy patches. v1 ports them.
- JavaScript helper files in the wheel.

## Further notes

"Same observable behavior as the stock SDK" is defined by the [stock SDK catalog](research/stock-sdk-behavior.md), which lists every public name's behavior with file and line citations. Slices 2 to 10 implement against it.

The agents port reads the stock SDK's private `_ctx` attribute. The port changes to check `js_object` first, which is tracked in the agents port, not here.

## Implementation plan

Each slice ends with a Worker that runs. Seam 2 tests are added in the same slice as the behavior they cover.

1. **Tracer.** The five workerd names, a minimal `Request` and `Response`, `fetch` routing and the `on_*` aliases. Done when a fixture Worker answers a request under `wynd dev` on all three targets, including a pre-2025-08-14 date. It first runs under plain `wrangler dev` with `src/workers` copied into the fixture's `python_modules/`, so it doesn't wait for Wynd slice 2.
2. **Boundary conversion.** `python_from_rpc` and `python_to_rpc` with stock rules, and RPC between two entrypoints.
3. **HTTP types.** Full `Request`, `Response`, `FetchResponse`, headers, `fetch`, `Blob`, `File` and `FormData`.
4. **Env and bindings.** The `Env` wrapper, typed binding classes, the passthrough wrapper, and `DurableObjectNamespace[T]`.
5. **Durable Objects and context.** Context wrappers, storage, `alarm` and WebSocket wrapping, and `DurableObjectAbort`.
6. **Module globals.** `env`, `wait_until`, `waitUntil`, `import_from_javascript` and `patch_env`.
7. **Entropy patches.** Port the patches and the `.pth` hook. Done when a fixture importing numpy and pydantic at the top level starts under `wynd dev` on 3.13 and 3.14. numpy 2.2.5 deployed and seeded itself per isolate without the patches in production, so the slice also records which patched packages still fail without them.
8. **Adapters.** `asgi` and `wsgi`. Done when FastAPI and Flask fixture Workers answer requests.
9. **Workflows.** Pure-Python steps, including the thenable for `NonRetryableError`. Done when the stock SDK's workerd Workflow tests pass unchanged against crosswind.
10. **Stock-conflict guard and conformance.** The guard, the stock SDK's tests run against crosswind, and the agents `verify` Worker under both toolchains.

## Map

### Destination

A crosswind-workers spec and build order with no open decision left, so that implementation can run from slice 1 to slice 10 without stopping for design questions.

### Notes

Settled decisions are in [decisions.md](decisions.md). Tickets in this map are worked one per session. Wayfinder only resolves tickets. The implementation-plan slices are built after the map has no open tickets, for example one slice at a time with the tdd skill. Grilling tickets use the grilling and domain-modeling skills, research tickets use the research skill and write findings to `.design/research/`, and a ticket is claimed by writing the driver's name next to its status before any work starts.

### Decisions so far

The design review settled these. Each line points at its section in the decisions file.

- [Packages and names](decisions.md#packages-and-names): published as `crosswind-workers`, imported as `workers`, Python 3.12 and later.
- [Scope](decisions.md#scope): full parity with the stock SDK's public names, with Workflows in pure Python.
- [Contract with workerd](decisions.md#contract-with-workerd): the five required names, raw-proxy methods wrapped, `on_*` aliases.
- [Compatibility with the stock SDK](decisions.md#compatibility-with-the-stock-sdk): stock behavior is the minimum, with typed methods on top.
- [FFI escape hatch](decisions.md#ffi-escape-hatch): `js_object` everywhere, plus constructors that accept JS objects.
- [Entropy patches](decisions.md#entropy-patches): ported from the stock SDK and loaded by a `.pth` hook.
- [pywrangler compatibility](decisions.md#pywrangler-compatibility): requires Wynd for now, with an import-time guard.
- [Testing](decisions.md#testing): host tests with a fake JS layer plus workerd integration tests.
- [Agents and containers ports](decisions.md#agents-and-containers-ports): no SDK dependency in the ports, and the agents `verify` Worker as the conformance test.
- [Workflows without the JavaScript helper](research/workflows-without-js.md): the helper only renames `NonRetryableError` for the engine. Python can do the same by returning a rejecting thenable from the step callback, so nothing blocks pure-Python Workflows.
- [Stock SDK observable behavior](research/stock-sdk-behavior.md): a per-name catalog of the stock SDK with citations. It covers the conversion rules, the 15 binding types the env wrapper recognizes, the four snake_case names that map to camelCase, the ctx wrappers and JS error mapping, and it flags 13 suspected bugs.
- [Pyright and the generated Env](research/pyright-and-the-generated-env.md): Pyright and mypy in strict mode accept the generated module and catch wrong RPC methods, argument types and binding names. It imports on 3.12, and the SDK must never resolve its annotations at runtime.
- Python names for JS methods: typed methods are hand-written with snake_case keywords, any other name passes through to JS under its JS name, typed methods win, and unknown keywords flow into the JS options object. Recorded in the Bindings module above and in [CONTEXT.md](CONTEXT.md).
- [Production snapshot precedence](research/production-deploy-checks.md): in production on a 3.12 date, the vendored `workers` wins and is the only copy loaded. On that pre-2025-08-14 date, production called the class's `on_fetch` for HTTP but the class's `scheduled` for a cron trigger.
- [Entropy patches without the hook](research/production-deploy-checks.md#entropy-patches-without-the-hook): numpy 2.2.5 imported at the top level deployed without the patches, with `python_process_pth_files` on and off, and every isolate drew different first values from numpy and stdlib `random`. Other patched packages are untested, so the port stays.
- [Stock SDK bugs: match or fix](decisions.md#compatibility-with-the-stock-sdk): crosswind fixes all 12 fixable bugs, `patch_env` raises `NotImplementedError`, and a docs page lists every difference.
- [Typed binding coverage](decisions.md#typed-bindings): typed classes for KV, D1, R2, Queues, Durable Object namespaces, `Fetcher` and Workflows, `str` for text vars and secrets, `Binding` for the rest, and JSON vars as Python values.

### Open tickets

None.

### Not yet specified

- Which of the stock SDK's entropy patches are still needed. numpy 2.2.5 deployed and reseeded per isolate without them, and the other patched packages are untested.
- The exact signatures workerd calls `scheduled`, `queue` and the other non-fetch handlers with. On a 2025-06-01 date production called `on_fetch` but `scheduled`, so the `on_*` rename doesn't apply to every handler. A cron handler declared as `scheduled(self, controller, env=None, ctx=None)` never wrote its result, and the cause is unknown.
- How JS exceptions map to Python exception classes beyond what the stock SDK does today.
- Streaming request and response bodies, and how they interact with lazy body reads.
- The WebSocket API shape for Durable Objects beyond wrapping the handlers.
- What, if anything, replaces the stock SDK's `handler` decorator in typed code.
- Logging and how Python logging maps to Workers' console output.
