# Removing a dependency with uv

Resolution of the "Removing a dependency with a uv override" task in the [Wynd map](../wynd.md), run on 2026-10-11 with uv 0.12.19.

## Method

A local package `libdep` declared `dependencies = ["workers-runtime-sdk"]`. The requirements were `libdep` plus the local `crosswind-workers`. Each case ran pywrangler's resolve flags against the Pyodide 3.13 target:

```bash
uv pip compile req.in --python <pyodide-3.13.2-emscripten-wasm32-musl> \
  --extra-index-url https://index.pyodide.org/0.28.3 --index-strategy unsafe-best-match \
  --no-build [--overrides overrides.txt | --excludes excludes.txt] -o pylock.<case>.toml
```

## Results

| Case | Exit | `workers-runtime-sdk` in the lock |
| --- | --- | --- |
| Baseline | 0 | Yes |
| `--overrides` with `workers-runtime-sdk ; sys_platform == "never"` | 0 | No |
| `--excludes` with `workers-runtime-sdk` | 0 | No |

Installing the `--excludes` lock into a Pyodide venv with `uv pip install -r pylock.excludes.toml --preview-features pylock` succeeded. The venv held `libdep` and crosswind's `workers` package, and no stock SDK.

## Answer

Both approaches work. Wynd uses `--excludes`, which uv documents as "Exclude packages from resolution" and which says what it means. The never-true-marker override is a fallback only. Wynd's minimum uv version must include `--excludes`. 0.12.19 has it, and the exact first version is unchecked.

## Side finding

`uv venv` writes `_virtualenv.pth` (one line, `import _virtualenv`) and `_virtualenv.py` into site-packages. pywrangler copies the whole site-packages directory into `python_modules/` (`sync.py:230` at commit `cb2db3c`), so every pywrangler project uploads that hook, and workerd runs it at startup when `python_process_pth_files` is on. Wynd's installer skips both files when it copies site-packages. Otherwise the shaker's `.pth` rule would treat `_virtualenv` as a root.
