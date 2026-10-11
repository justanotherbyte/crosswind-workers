# Workflows without the JavaScript helper

Researched 2026-10-11. Ticket from `.design/crosswind-workers.md`. Nothing here was run in workerd. Every claim comes from reading source.

Sources and short names:
- `sdk/` is workers-py at `cb2db3c9`, `packages/runtime-sdk/src/workers/`.
- `wd/` is workerd at `d08010b905b3fb894b47552f56cf87a81c3fc7b4`, `src/pyodide/`.
- `py26/`, `py28/`, `py314/` are pyodide tags `0.26.0a2`, `0.28.2` and `314.0.6`, `src/core/`. These are the three Pyodide versions workerd ships (`wd/internal/const.ts:5-10`).
- `ws/` is workers-sdk at `fcf625da`, `packages/workflows-shared/src/` (the local Workflows engine).

## 1. What `workflows.js` does (high confidence)

It does one thing. `wrapWorkflowStep` returns a JS `Proxy` over the step stub that forwards every property except `do` (`sdk/workflows.js:67-90`). For `do`, it wraps each function argument with `wrapWorkflowStepCallback`. That wrapper awaits the Python callback and catches a `PythonError` whose `type` is `"NonRetryableError"`. It then throws a fresh `Error` with `name = "NonRetryableError"` and the message parsed from the traceback's last line (`workflows.js:33-58`). It rethrows all other errors unchanged.

Everything else is already Python. `sleep`, `sleep_until` and `wait_for_event` are in `sdk/entrypoints.py:186-204`. Step config (including `retries`) goes through `to_js(config, dict_converter=Object.fromEntries)` at `entrypoints.py:238-239`, and the engine applies retries. Result serialization uses `python_to_rpc` at `entrypoints.py:231`. Memoisation and dependency resolution are at `entrypoints.py:112-255`.

Why JS: the engine treats a step error as non-retryable only if `error.name === "NonRetryableError"` or `error.message.startsWith("NonRetryableError")` (`ws/context.ts:936-937`). A Python exception reaches JS as a `PythonError` whose message is the traceback (commit `1c1980a` message). Pyodide builds that error in `wrap_exception` (`py28/error_handling.c:147-188`). This code always makes a new `PythonError`, even for a re-raised `JsException`, because it never unwraps the original JS error (`py26/error_handling.c:192-218`). A coroutine that raises is rejected through the same `wrap_exception` (`py28/pyproxy.c:1161-1167`). So no `raise` in Python can produce a JS error with a custom `name`.

## 2. Doing it from Python (medium-high confidence, unverified at runtime)

A Python coroutine can still settle with an arbitrary JS error. When the coroutine returns, Pyodide calls `python2js(result)` and passes it to the native `resolve` of a real `Promise` (`py28/pyproxy.c:1148-1151`, `py28/pyproxy.ts:2554-2557`). `python2js` of a `JsProxy` returns the underlying JS object. A native `resolve` given a thenable adopts that thenable's state ([ECMA-262 Promise Resolve Functions](https://tc39.es/ecma262/#sec-promise-resolve-functions)). So a step callback that *returns* a thenable whose `then` calls `reject(err)` makes the engine see `err` itself.

Return a thenable, not `js.Promise.reject(err)`. asyncio runs done callbacks through `call_soon`, which the WebLoop schedules with `setTimeout` (pyodide `src/py/pyodide/webloop.py`, lines 290-305 at `0.26.0a2` and 277-291 at `0.28.2`). A rejected promise created inside the coroutine would sit without a handler for a full task. Whether workerd then reports an unhandled rejection is unverified. The thenable never exists in a rejected state, so the question does not arise.

Item by item:
- Passing a Python async function to `step.do` works without a JS wrapper. Pyodide keeps borrowed argument proxies alive until a returned promise settles (`py26/jsproxy.c:3207-3229`). In 0.28 that logic moved into result converters (`py28/jsproxy_call.c:400-415`). I did not trace the converter, so this is medium confidence for 0.28 and 3.14. As evidence, workerd's bundled SDK passes the bare `_callback` to the stub (`wd/internal/workers-api/src/workers/_workers.py:1293-1296`).
- Promise identity is no issue. The shim returned the stub's own promise (`workflows.js:64-66,87`), and the Python code awaits that same promise (`entrypoints.py:236`).
- Structured clone is no issue. Results already go through `python_to_rpc` in Python.
- Only JS can throw synchronously with a custom error object, and only JS can make a rejection reason that is not a `PythonError` from inside a `raise`. The thenable return avoids both needs.

## 3. Python versions (high confidence)

The answer is the same on all three. workerd calls `run` with `callWithOptions({relaxed, promising: true})` when it exists, else `callRelaxed` (`wd/python-entrypoint-helper.ts:355-372,491-497`). `callWithOptions` exists in 0.28.2 (`py28/pyproxy.ts:2694`) and not in 0.26.0a2. The approach needs only `await`, so it needs no JSPI or `run_sync`. The resolve path and `wrap_exception` are unchanged in 3.14 (`py314/pyproxy.c:1047-1050`, `py314/error_handling.c:188`, `py314/pyproxy.ts:2587`).

The current shim is loaded with a dynamic import on the first `run` (`sdk/entrypoints.py:301-314`), and that import works only because Wrangler registers `.js` files under `python_modules/workers/` (`sdk/utils.py:128-145`). The pure-Python version removes both the import and that packaging requirement.

## 4. Sketch

```python
from js import Error, Object
from pyodide.ffi import create_once_callable, to_js

def _non_retryable(exc):
    err = Error.new(str(exc))
    err.name = "NonRetryableError"
    # A thenable, so no rejected promise exists before the engine adopts it.
    return to_js({"then": create_once_callable(lambda _res, rej: rej(err))},
                 dict_converter=Object.fromEntries)

async def _callback(ctx=None):          # inside _do_call
    try:
        ...                             # existing body, ends in python_to_rpc(result)
    except NonRetryableError as exc:
        return _non_retryable(exc)
```

Then delete `_wrap_js_workflow_step` and pass the raw `step` to `_WorkflowStepWrapper` (`entrypoints.py:304-327`). `str(exc)` matches the shim's message for single-line messages and keeps all lines of a multi-line message. It gives `""` for `NonRetryableError()`, which the stock test expects (stock `tests/workerd-test/workflow/worker.js:68-79`).

Nothing blocks the pure-Python approach. To verify it, port `tests/workerd-test/workflow/` from the stock SDK unchanged. It asserts on the error name and message that the engine receives.
