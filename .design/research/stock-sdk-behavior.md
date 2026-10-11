# Stock SDK observable behavior

Researched 2026-10-11. Ticket from `.design/crosswind-workers.md`. Source is the workers-py checkout at `cb2db3c` (2026-10-06), package `workers-runtime-sdk` 1.9.3. Path prefixes: `w/` is `packages/runtime-sdk/src/workers/`, `src/` is `packages/runtime-sdk/src/`, `t/` is `packages/runtime-sdk/tests/`. Two facts come from workerd `main` at `5f4f3d3` (`wd/`), because the SDK calls into it. Lines marked **Bug?** look unintended.

## How workerd drives the SDK

- workerd imports `DurableObject`, `WorkerEntrypoint`, `WorkflowEntrypoint`, `python_from_rpc` and `python_to_rpc` from `workers` (`wd/src/pyodide/internal/introspection.py:7-13`). Every class method call runs `python_from_rpc` on each positional and keyword argument and `python_to_rpc` on the awaited result (`introspection.py:76-90`). A crosswind `python_to_rpc` must therefore return a JS `Response` for a `fetch` result.
- With `relaxed`, workerd calls the method through `relaxed_call`, which drops surplus arguments (`introspection.py:81-84`). That is why `scheduled(self, ctrl, env, ctx)` and `queue(self, batch, env, ctx)` both work (`t/workerd-test/sdk/worker.py:43`, `t/bindings-test/src/worker.py:23`).
- Only public, plain functions become RPC methods (`introspection.py:27-37`).

## `__all__`, `env`, `wait_until`, `waitUntil`

`__all__` lists 27 names (`w/__init__.py:23-51`). `DurableObjectAbort`, `NonRetryableError` and `DurableObjectContext` are not in it. They are importable from `workers.entrypoints` and `workers.workflows`.

- `workers.env` comes from the module `__getattr__`. Each access builds a new `_EnvWrapper(cloudflare_workers.env)` (`w/__init__.py:54-57`), so `workers.env is workers.env` is false. `from workers import env` binds one wrapper for the life of the isolate. That wrapper caches bindings (see `_EnvWrapper`).
- `wait_until` and `waitUntil` both return `cloudflare:workers`'s `waitUntil` unwrapped (`w/__init__.py:58-60`). workerd replaces that function with one that accepts a Pyodide future, calls `copy()` on it, awaits it and then calls `destroy()` (`wd/src/pyodide/python-entrypoint-helper.ts:44-64,104-121`).
- Any other unknown attribute raises `AttributeError` (`w/__init__.py:61`).

## `import_from_javascript(module_name)`

The call is synchronous. `"cloudflare:workers"` and `"cloudflare:sockets"` return modules that were imported ahead of time, so they work at top level (`w/utils.py:103-106`). Other names run `run_sync(doAnImport(name))` and need JSPI (`w/utils.py:108-112`). Errors:

- A JS failure becomes `ImportError("Failed to import '<name>': <e>")` (`w/utils.py:113-114`).
- A `RuntimeError("No suspender")`, meaning the call ran in global scope, becomes `ImportError` saying only the two modules work there (`w/utils.py:115-119`).
- A Pyodide without `run_sync` gives `ImportError` "...until the next python runtime version" (`w/utils.py:121-125`).

## `patch_env(d=None, **kwds)`

This is a `@contextmanager` that merges `dict(d) | kwds` and runs `yield from _pyodide_entrypoint_helper.patch_env_helper(to_js(kwds))` (`w/utils.py:148-154`).

workerd added it in `3d8bf1e` ("Add patch_env to Python workers sdk", 2025-12-16). The helper was a JS generator that held `innerEnv.pythonPatchEnv(patch)` open across one `yield`. That native call replaced the env stored in the async context, as a `StorageScope` released on dispose. It did not merge with the existing env. workerd removed all of it in `6581cf0` ("Remove patch_env", 2026-06-30), and current `PyodideEntrypointHelper` has no `patch_env_helper` (`wd/src/pyodide/python-entrypoint-helper.ts:84-91`).

Today, calling `patch_env()` returns a context manager, and entering it raises `AttributeError` from the JsProxy module. It cannot work. **Bug?** Even before removal, `to_js(kwds)` with no `dict_converter` gives a JS `Map`, not an object, so `env.NAME` lookups on the patched env would likely miss.

## `python_from_rpc(obj)` (`w/rpc.py:92-114`)

| Input | Result |
|---|---|
| `jsnull` | `None` (`rpc.py:101-102`) |
| `undefined` | `None`, from Pyodide (`t/workerd-test/python-rpc/worker.py:228-229`) |
| Anything without `.constructor` (Python values, primitives) | returned unchanged (`rpc.py:104-105`) |
| `TestController` | `None` (`rpc.py:107-110`) |
| Other JS values | `obj.to_py(default_converter=...)`, then a recursive null pass (`rpc.py:112-114`) |

`to_py` turns arrays into `list`, plain objects and `Map` into `dict`, `Set` into `set`, and buffers into `memoryview` (`python-rpc/worker.py:172-226`). The default converter handles class instances by `constructor.name` (`rpc.py:22-54`):

- `Response` becomes `Response(value)`. `FormData`, `Blob` and `Request` become the matching Python wrapper.
- `File` becomes `File(value)`. **Bug?** `File.__init__` requires `filename` (`w/blob.py:83-87`), so receiving a JS `File` raises `TypeError`.
- `Blob(value)` makes a new JS Blob that wraps the old one and keeps its `type` (`blob.py:30-52`).
- `Date` becomes a naive `datetime.fromtimestamp(ms/1000)` in the isolate's local zone (`rpc.py:40-42`).
- An object whose constructor is exactly `Error` becomes `Exception(value.toString())`, so the message reads `"Error: msg"` (`rpc.py:43-44`). `TypeError` and other subclasses pass through as JsProxy.
- A boxed `Number` becomes `valueOf()` (`rpc.py:45-46`).
- Anything else passes through as a JsProxy (`rpc.py:48-54`).

After `to_py`, `_replace_jsnull_with_none` recurses into `dict` and `list` only. Every dict becomes a `JsDict`, a `dict` subclass with attribute get and set; a missing key raises `AttributeError` (`rpc.py:57-89`). Sets and tuples are not walked.

## `python_to_rpc(value)` (`w/rpc.py:180-205`)

1. `None` becomes `jsnull`, and a `_BindingWrapper` becomes its `_binding` (`rpc.py:188-192`).
2. `None` nested in `dict` and `list` becomes `jsnull` (`rpc.py:170-177`).
3. `_raise_on_disabled_type` walks the value (`rpc.py:117-140`). It raises `TypeError` for a `tuple`, a `bytearray`, an awaitable, or a JS `RegExp`, at any depth inside iterables. Callables and wrappers are skipped. The tests confirm `(1,2,3)`, `[(1,2,3)]`, `{"test": (1,2,3)}`, `bytearray` and `RegExp` raise `TypeError` (`python-rpc/worker.py:318-330`).
4. `to_js(value, default_converter=..., dict_converter=Object.fromEntries)`. A dict becomes a plain object, so non-string keys turn into strings: a `Map` round trip gives `{"1": "one"}` (`python-rpc/worker.py:208-219`). The default converter (`rpc.py:143-167`) handles these:
   - an object with `.js_object` (`Request`, `Response`, `Blob`, `FormData`) gives that object;
   - `datetime` gives `js.Date(obj.timestamp()*1000)`, where a naive datetime is read as local time;
   - `Exception` gives `js.Error(str(obj))`, which drops the exception type;
   - a callable that is not a class gives `create_proxy(obj)`, a persistent proxy that is never destroyed.

`bytes` and `memoryview` arrive at the receiver as `memoryview` (`python-rpc/worker.py:177-180`). `set` stays `set`. Primitives come back as Python values, not JsProxy. Objects `to_js` cannot convert become PyProxies, and the RPC send then fails with `JsException` `DataCloneError`, as for a custom class, `complex` or `range` (`python-rpc/worker.py:313-321`). **Bug?** Step 3 iterates any iterable, so a generator gets consumed before conversion. **Bug?** `_EnvWrapper` and `_DurableObjectNamespaceWrapper` have no `js_object` and are not `_BindingWrapper`s, so they become PyProxies instead of the binding.

## `_EnvWrapper` and binding wrappers (`w/rpc.py:208-449`)

`_EnvWrapper(env)` is idempotent: `_EnvWrapper(x) is x` (`rpc.py:213-229,423-428`; `t/workerd-test/durable-object-inheritance/worker.py:144-146`). On attribute access it reads `env.<name>` and wraps by JS `constructor.name`, then caches the result with `setattr` (`rpc.py:430-449`):

- `Fetcher` (service bindings, `ASSETS`, mTLS) becomes `_FetcherWrapper`.
- `DurableObjectNamespace` becomes `_DurableObjectNamespaceWrapper`.
- `WorkflowImpl` becomes `_WorkflowBindingWrapper`.
- `KvNamespace`, `R2Bucket`, `D1Database`, `WorkerQueue`, `Ai`, `VectorizeIndexImpl`, `AnalyticsEngine`, `AnalyticsEngineDataset`, `LocalAnalyticsEngineDataset`, `ImagesBindingImpl`, `HostedImagesBindingImpl` and `Ratelimit` become `_BindingWrapper` (`rpc.py:408-421`).
- Everything else comes back raw: text vars as `str` (`python-rpc/worker.py:147`), JSON vars, Hyperdrive and version metadata as JsProxy.

There is no `__getitem__`, iteration or `__contains__`.

`_BindingWrapper` (`rpc.py:232-337`) behaves as follows:

- **Attribute access.** A non-callable attribute returns `_convert_result(attr)`. A callable returns a function that converts each argument and keyword with `python_to_rpc`, calls the JS method, and returns a coroutine if the result is thenable, or the converted value directly if not (`rpc.py:283-309`). Results are cached on the instance (`rpc.py:311-314`).
- **Keywords.** Pyodide passes keywords as a trailing JS object, so `q.send("x", contentType="text")` works (`t/bindings-test/src/test_queue.py:31,46-48`).
- **No snake_case mapping.** Callers use JS names such as `sendBatch`, `writeDataPoint` and `deleteAll`.
- **Result conversion.** `_convert_result` runs `python_from_rpc`, then wraps a leftover JsProxy, or each JsProxy item of a top-level list (`rpc.py:273-281`). A callable becomes `_RpcStubWrapper`, which has `__call__` (`rpc.py:340-349`). Other values get `self.__class__(value)`. Constructor names in `_JS_PASSTHROUGH_TYPES` stay raw: the buffer and typed-array types, `Blob`, `FormData`, `ReadableStream`, `URLSearchParams`, `Response` and `Headers` (`w/utils.py:23-53`). JsProxies inside dicts are not wrapped.
- **Container methods.** `[int]` indexes the binding and `[str]` reads an attribute (`rpc.py:316-319`). `__iter__` raises `TypeError` unless the binding is iterable (`rpc.py:321-326`). `__bool__` is always true. `__len__` needs an integer `length`, else `TypeError "... has no len()"` (`rpc.py:328-337`; `python-rpc/worker.py:364-369`).
- **Bug?** The `setattr` cache freezes non-callable attributes, such as a SQL cursor's counters, at their first value.

The specific wrappers:

- `_FetcherWrapper.fetch(*a, **kw)` calls `workers.fetch(*a, fetcher=binding.fetch, **kw)` and returns a Python `Response` (`rpc.py:352-354`). Other attributes, including DO stub RPC methods, go through `_BindingWrapper`. A nested value such as `stub.id` gets wrapped as `_FetcherWrapper` too (`rpc.py:271`).
- `_DurableObjectNamespaceWrapper` is a plain class. It has no conversion and is not idempotent. `get` and `getByName` return `_FetcherWrapper`, `jurisdiction` returns a new namespace wrapper, and every other attribute (`idFromName`, `newUniqueId`) is raw (`rpc.py:357-373`).
- `_WorkflowBindingWrapper` has async `get`, `create`, and `create_batch` (which calls `createBatch`). Each returns `_WorkflowInstanceWrapper`, or a list of them (`rpc.py:388-404`).
- `_WorkflowInstanceWrapper.send_event` is async and calls `sendEvent`. `status`, `pause`, `resume`, `restart`, `terminate` and `id` go through `_BindingWrapper` (`rpc.py:376-385`). The tests accept plain dicts and pre-converted `to_js` objects (`t/bindings-test/src/test_workflow.py:200-250`).

## `WorkerEntrypoint`, `DurableObject`, `WorkflowEntrypoint` (`w/entrypoints.py`)

- Each base `__init__(self, ctx, env)` sets `self.ctx` and `self.env` (`entrypoints.py:369-371,386-388,404-406`).
- `_wrap_class` replaces the `__init__` a class defines itself. Classes without one inherit the parent's wrapped init. The wrapped init calls `patchWaitUntil(args[0])`, wraps `ctx` in `DurableObjectContext` for `DurableObject` subclasses, and wraps `env` in `_EnvWrapper` (`entrypoints.py:280-298`). Because the wrapping is idempotent, multi-level inheritance does not double-wrap (`durable-object-inheritance/worker.py:55-169`).
- `patchWaitUntil` only patches objects whose tag is `[object ExecutionContext]` (`wd/.../python-entrypoint-helper.ts:67-82`). For a WorkerEntrypoint, `self.ctx` is the raw JS `ExecutionContext`, and `ctx.waitUntil(coroutine)` keeps the coroutine alive (`python-rpc/worker.py:86-87,337-340`). Workflow `ctx` is not wrapped either.
- `__init_subclass__` does not call `super().__init_subclass__()` (`entrypoints.py:373-374,390-392,408-410`).
- `WorkerEntrypoint` subclasses also get `_wrap_queue_handler`. It finds `queue`, including an inherited one, and wraps it so `batch` becomes `_BindingWrapper(batch)`. The handler can be sync or async and its result is returned unconverted (`entrypoints.py:344-357`). Then `batch.messages` is a list of wrapped messages: `message.body` arrives converted, and `message.ack()` is a sync call (`t/bindings-test/src/worker.py:23-32`). DurableObject has no queue wrapping.

## `DurableObjectContext` and `DurableObjectAbort` (`w/entrypoints.py:30-72`)

- The constructor is idempotent, and `_ctx` holds the raw JS `DurableObjectState` (`entrypoints.py:34-45`).
- `__getattr__` forwards to `_ctx` and caches the result. Only a `DurableObjectStorage` gets wrapped, as `_BindingWrapper` (`entrypoints.py:47-53`). So `ctx.storage.get/put/deleteAll/sql.exec` convert, while `ctx.id`, `blockConcurrencyWhile`, `acceptWebSocket` and the rest are raw JS. `storage.get` of a missing key gives `None`, and a list of keys gives a dict (`t/bindings-test/src/worker_durable_object.py:22-82`).
- `abort(reason=None)` queues `ctx.abort()` or `ctx.abort(reason)` in a JS microtask, then raises `DurableObjectAbort(reason or "Durable Object abort requested")` (`entrypoints.py:55-72`). `DurableObjectAbort` subclasses `BaseException`, so `except Exception` does not catch it. The caller sees an error containing the reason, and the object is recreated (`t/workerd-test/durable-object-abort/worker.py:43-54`).

## `handler` (`w/entrypoints.py:258-277`)

`handler` is a sync wrapper for the old module-level handlers. It converts `args[0]` to `Request` if it is a JS `Request`, and wraps `args[1]` in `_EnvWrapper` whatever its type. Keywords are not converted. It returns `func`'s return value, which may be a coroutine. Module-level handlers are not registered once `python_no_global_handlers` is on (compat date 2025-08-14 or later, `python-rpc/worker.py:122-124`).

## Workflows (summary; `w/entrypoints.py:75-339`)

- `_wrap_workflow_step` wraps a `run` the class defines itself. It converts `event` with `python_from_rpc`. It wraps `step` first in JS `wrapWorkflowStep`, imported from `python_modules/workers/workflows.js`, and then in `_WorkflowStepWrapper`. A non-`None` result goes through `python_to_rpc` (`entrypoints.py:304-339`; `w/utils.py:133-145`).
- The `step.do` signature depends on a compat flag (`entrypoints.py:87-90`). Without `python_workflows_implicit_dependencies`, it is `do(name, depends=None, concurrent=False, config=None)`. Parameters other than `ctx` must match `depends` one to one, or `TypeError` (`entrypoints.py:92-100,146-173`). With the flag, it is `do(name=None, *, concurrent=False, config=None)`, and each parameter name must be an earlier step's name or `ctx`, else `TypeError` (`entrypoints.py:102-110,136-144`). **Bug?** Steps are keyed by step name, so a step named `"ctx-step"` cannot be a dependency.
- A decorated step becomes an async no-argument callable. Results are memoized per step function, and concurrent awaits share one in-flight task. The step's return value goes through `python_to_rpc`, and `ctx` arrives through `python_from_rpc` (`entrypoints.py:217-255`).
- The other step methods (`entrypoints.py:186-204`):
  - `sleep` passes its arguments through raw;
  - `sleep_until(name, ts)` converts any non-`str` timestamp and calls `sleepUntil`;
  - `wait_for_event(name, event_type, /, timeout="24 hours")` is async, calls `waitForEvent`, and converts the result.
- Errors from `step.do` go through `_from_js_error` (`entrypoints.py:243-244`). **Bug?** A non-JS exception there has no `.message`, so `_from_js_error` raises `AttributeError`.

## How JS errors become Python exceptions

- Binding calls, `fetch` on current Pyodide, and RPC sends do not translate errors. They raise `pyodide.ffi.JsException` (`rpc.py:289-298`; `python-rpc/worker.py:313-321`).
- `_to_python_exception` maps `RangeError` to `ValueError` and `TypeError` to `TypeError`, and returns anything else unchanged (`w/utils.py:157-163`). Only `Request.form_data`, `Response.form_data`, `Response.redirect` and `Response.from_json` use it (`w/request.py:156-157`; `w/response.py:61-62,87-88,110-111`). `Response.redirect("", 502)` raises `ValueError` (`t/workerd-test/sdk/tests/test_sdk.py:175-188`).
- `_from_js_error` is used for workflows only. It returns `NonRetryableError` when the name is `NonRetryableError` or the message starts with it. For a `PythonError`, it reads the traceback's last line and returns `TypeError`, `ValueError` or `NonRetryableError` built from that whole line, so the type prefix stays in the message. Anything else goes to `_to_python_exception` (`w/utils.py:166-209`). `workflows.js` turns a Python `NonRetryableError` raised in a step into a JS `Error` named `NonRetryableError` (`w/workflows.js:44-58`).
- Reading a used body raises `OSError("Body already used")` (`w/request.py:133-137,167-170`). Under Pyodide `0.26.0a2`, `fetch` raises `OSError(message)` (`w/fetch.py:28-29`).

## HTTP types

`Request(input, **FetchKwargs)` (`w/request.py:21-181`):

- A JS `Request` with any options raises `ValueError`. An `HTTPMethod` becomes its value. `headers` accepts a dict, a list of tuples or `js.Headers`, and anything else raises `TypeError` (`w/utils.py:240-249`). `body` accepts `bytes`, which is copied zero-decode, a Python `FormData`, or JS values.
- Properties: `js_object`, `body` (JS stream), `body_used`, `cf` (JsProxy or `None`), `cache`, `credentials`, `destination`, `headers`, `integrity`, `is_history_navigation`, `keepalive`, `method`, `mode`, `redirect`, `referrer`, `referrer_policy` and `url`.
- `method` returns `HTTPMethod[...]`. **Bug?** A non-standard method raises `KeyError`.
- Async methods: `buffer` (JS ArrayBuffer), `form_data`, `blob`, `bytes`, `json(**kw)` and `text`. `clone()` is sync. The repr is `Request(method='POST', url='https://test.com/')` (`test_sdk.py:357-449`).

`headers` on `Request`, `FetchResponse` and `Response` returns `HTTPMessageMapping`, a `http.client.HTTPMessage` that is also a `Mapping`, with stripped values (`w/utils.py:252-285`). With `python_request_headers_preserve_commas`, `Set-Cookie` values come from `getSetCookie()` and stay separate. Other duplicate headers stay comma-joined, as JS joins them (`test_sdk.py:384-432`).

`Response(body=None, status=None, status_text="", headers=None, web_socket=None)` (`w/response.py:123-199`):

- Accepted bodies are `str`, `bytes`, a Python `FormData`, `None`, or a JS value whose constructor is in `RESPONSE_ACCEPTED_TYPES`. Anything else raises `TypeError("Unsupported type in Response: <name>")`. **Bug?** A Python `Blob` is rejected.
- A JS `Response` with any option raises `ValueError`. Falsy `status` and `status_text` are dropped.
- Behavior comes from Pyodide's `FetchResponse`: `status`, `status_text`, `ok`, `url`, `text()`, `bytes()`, `buffer()` and `clone()`. The SDK adds `body`, `js_object`, `headers`, `form_data()`/`formData()`, `blob()` and `replace_body(body)`, which is sync and passes only `FormData`, not `bytes`.
- `from_json(data, status=200, status_text="", headers=None)` sets `content-type: application/json` unless the headers already have one.
- `Response.json(data, ...)` called on the class is `from_json`. Called on an instance, it is the async body parse (`response.py:115-120`).
- `redirect(url, status=302)` is static. **Bug?** It returns a raw `js.Response`.
- The repr is `Response(status=200, status_text='OK', content_type='application/json')` (`test_sdk.py:497-566`).

`FetchResponse` is the `Response` base class and adds no constructor. `fetch(resource, **FetchKwargs)` is async and always returns `Response` (`w/fetch.py:34-44`). A positional options dict raises `TypeError` (`test_sdk.py:108-131`). `cf`, `redirect` and `fetcher` go to `pyfetch`.

`Blob(blob_parts, content_type=None, endings=None)` (`w/blob.py:20-79`):

- A single non-iterable part is wrapped in a list. A single `Blob` or `File` part passes on its type.
- Parts may be `str`, Python or JS Blob/File, or buffer-protocol objects. Anything else raises `TypeError`. **Bug?** A bare `memoryview` or `bytearray` is iterable, so it is split into ints and fails.
- Members: `size`, `content_type`, `js_object`, async `text()` and `bytes()`, and sync `slice(start, end, content_type)`, which returns a `Blob`.

`File` adds `filename`, `last_modified`, and the properties `name` and `last_modified` (`blob.py:82-131`). `BlobEnding` is a `StrEnum` with `TRANSPARENT` and `NATIVE`. `BlobValue` and `FormDataValue` are string aliases (`blob.py:10-18`; `w/formdata.py:8`).

`FormData(form_data=None | dict | js.FormData)` is a `MutableMapping`. Other input raises `TypeError` (`formdata.py:28-97`). `__getitem__` returns the first value, with JS Blob and File converted. `__setitem__` rejects a `list`. The class also has `append(k, v, filename=None)`, `delete`, `get_all`, generator `keys()`, `values()` and `items()`, and `js_object`. **Bug?** `__len__` calls `len()` on a generator and raises `TypeError`. A missing key returns JS null, not `KeyError` (inferred, untested).

`types.py` exports `Context`, a Protocol with `waitUntil`; the string aliases `JSBody`, `Body` and `Headers`; and the `TypedDict`s `RequestInitCfProperties` and `FetchKwargs` (`headers`, `body`, `method`, `redirect`, `cf`, `fetcher`) (`w/types.py:12-49`).

## `asgi` (`w/asgi.py`; top-level `asgi` aliases it, `src/asgi.py:1-6`)

- `fetch(app, req, env, ctx=None)` runs a full lifespan startup on every request (`asgi.py:438-463`). Shutdown runs after the response, or later through `wait_until` when the response streams. A lifespan failure before startup counts as "no lifespan" (`asgi.py:96-187`).
- The request body is fully buffered into the receive queue before the app runs. Afterwards, `receive` blocks until the response finishes and then returns `http.disconnect` (`asgi.py:211-230`).
- The scope has `asgi` 3.0/2.0, lower-cased byte headers, `http_version` "1.1", a percent-decoded `path`, `raw_path`, `query_string`, a `state` copy, and `env`. It has no `client`, `server` or `root_path` (`asgi.py:53-93`).
- A body sent with `more_body` streams through a `TransformStream`. A single body chunk is copied once. Statuses 101, 103, 204, 205 and 304 get a null body (`asgi.py:232-287`).
- `websocket(app, req, env=None)` accepts a `WebSocketPair`, maps client messages to ASGI events, and returns status 101 (`asgi.py:335-469`).
- `entrypoint(app)` returns a `Default(WorkerEntrypoint)` that sends `upgrade: websocket` requests to `websocket` (`asgi.py:472-481`).
- `asgi.env` imports FastAPI and returns a `Depends` that reads `scope["env"]` (`asgi.py:484-494`).

## `wsgi` (`w/wsgi.py`)

- `fetch(app, req, env, ctx=None)` is async, but the app runs synchronously. `wsgi.input` is a lazy `BufferedReader` over the JS stream that uses `run_sync`, so it needs JSPI (`wsgi.py:28-104,364-381`). **Bug?** `_make_wsgi_input` never returns `None`, so the buffered fallback is dead code.
- The environ follows PEP 3333 and adds `workers.env`. Repeated headers are joined with a bare `,` (`wsgi.py:115-186`).
- The response streams from a pull-based `ReadableStream`. `write()` output comes first, and `close()` is called once the body ends (`wsgi.py:215-361`).
- `entrypoint(app)` returns a `Default(WorkerEntrypoint)` with no websocket support (`wsgi.py:384-391`).

## Compat flags and Python versions

- `python_workflows_implicit_dependencies` changes the `step.do` signature, and `python_request_headers_preserve_commas` changes header parsing (`src/_cloudflare_compat_flags.pyi:1-2`).
- `requires-python >=3.11` (`pyproject.toml:12`), because the code uses `HTTPMethod`, `StrEnum`, `Unpack` and `Never`. No code branches on 3.12 versus 3.13.
- On Pyodide `0.26.0a2`, `fetch` uses a local copy of `pyfetch` (`fetch.py:14-31`).
- On a Pyodide without `jsnull`, `jsnull = None` (`utils.py:17-20`). `None` then crosses as `undefined` rather than `null`.
- The tests skip Float16Array and BigInt arrays on older Pyodide (`test_sdk.py:572-586`).
