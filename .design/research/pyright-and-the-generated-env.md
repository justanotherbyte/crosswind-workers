# Pyright and the generated Env

Resolution of the "Pyright and the generated Env" task in the [crosswind-workers map](../crosswind-workers.md), run on 2026-10-11.

## Method

A stub `workers` package held the planned shapes: `WorkerEntrypoint[E]` and `DurableObject[E]` written with PEP 695 class syntax, `KVNamespace`, and `DurableObjectNamespace[T]` whose `get_by_name` returns `T`. `src/env.py` was the generated module from the Wynd spec: `from __future__ import annotations`, a `Protocol` named `Env`, and `DurableObjectNamespace[Counter]` with `Counter` imported from `main` under `TYPE_CHECKING`. `src/main.py` defined `Counter(DurableObject[Env])` and `Default(WorkerEntrypoint[Env])`. `src/bad.py` planted four mistakes:

- a misspelled RPC method
- a wrong argument type
- a misspelled binding name
- a `str` binding assigned to `int`

The checkers ran with Python 3.12 settings: Pyright in strict mode, and mypy with `--strict`. The runtime check imported `main` and `env` on CPython 3.12.3.

## Results

- **Pyright (strict).** `main.py` and `env.py` reported nothing. `bad.py` reported every planted mistake, for example `Cannot access attribute "incremnt" for class "Counter"` and `Argument of type "Literal['two']" cannot be assigned to parameter "by" of type "int"`.
- **mypy (strict).** The same result, with suggestions: `"Counter" has no attribute "incremnt"; maybe "increment"?` and `"Env" has no attribute "CACHEE"; maybe "CACHE"?`.
- **Runtime on 3.12.** `import main` succeeded. There was no circular import, because `env.py` imports `main` only under `TYPE_CHECKING`. `Default.__orig_bases__` was `(workers.WorkerEntrypoint[env.Env],)`.
- **`typing.get_type_hints(env.Env)` raises `NameError: name 'Counter' is not defined`.** `Counter` exists only for type checkers.

## Answer

The generated module shape works for Pyright, mypy and the 3.12 runtime, and `get_by_name` resolves `Counter`'s methods. crosswind must never resolve annotations on `Env`, or on user classes, at runtime: no `get_type_hints`, and no evaluation of `__annotations__` strings. A real Worker on Python 3.14 has lazy annotations by default and was not tested.
