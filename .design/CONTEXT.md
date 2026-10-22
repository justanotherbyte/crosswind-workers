# Wynd and crosswind-workers

Tooling for Python Cloudflare Workers. Wynd is the CLI that installs, prunes and uploads a Worker's packages. crosswind-workers is the runtime SDK that Worker code imports as `workers`.

## Build

**Target**:
The Python version and Pyodide package index a Worker runs on, chosen from its compatibility date and flags.
_Avoid_: runtime version, platform

**Full tree**:
Every package installed for the target, as `python_modules/` in the run directory. `wynd dev` runs it.
_Avoid_: vendor directory, site-packages

**Run directory**:
The directory under `.wynd/run/` that stands in for a config's directory. It holds the staged config that `wynd dev` and every passthrough command hand Wrangler, with the full tree, copies of `.dev.vars*` and `.env*`, and local state in `.wrangler/state/`.
_Avoid_: staging directory

**Staged tree**:
The pruned copy of a Worker in `.wynd/build/`, with its own config, that every upload command sends.
_Avoid_: build output, bundle

**Shake plan**:
The shaker's decision for every file in the full tree: kept or dropped, with a reason.
_Avoid_: manifest, report

**Root**:
A module the shaker treats as used without finding an import of it: the entry module, a `keep` entry, or a module named in a `.pth` file.
_Avoid_: entrypoint (that is one kind of root)

**Unresolved name**:
An imported name with no vendored file, such as a stdlib module or `js`. The shake plan lists it, and the build continues.
_Avoid_: missing import

## SDK

**Stock SDK**:
Cloudflare's `workers-runtime-sdk`, the SDK pywrangler installs.
_Avoid_: official SDK, workers-py

**Binding class**:
A crosswind class in `workers.bindings` with typed methods for one kind of binding, such as `KVNamespace`.
_Avoid_: binding wrapper, binding type

**`Binding`**:
The class for every binding type that has no binding class. Every name on it is a passthrough.
_Avoid_: untyped binding, raw binding

**Typed method**:
A method a crosswind class defines in Python, with an explicit signature and its own conversions.
_Avoid_: wrapper method

**Passthrough**:
Access to a name a crosswind class doesn't define, forwarded to the JS object under its exact JS name.
_Avoid_: proxy, fallback

**Escape hatch**:
The `js_object` attribute every crosswind wrapper exposes, plus constructors that accept a JS object.
_Avoid_: raw access, FFI mode
