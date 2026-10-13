# Wynd

Spec and implementation plan for Wynd, the CLI that replaces pywrangler. Settled decisions live in [decisions.md](decisions.md). This file turns them into modules, user stories, a build order and the open questions that still block parts of the build. The runtime SDK has its own spec in [crosswind-workers.md](crosswind-workers.md).

## Problem statement

A developer who writes a Python Worker today uses pywrangler. pywrangler installs every resolved package into `python_modules/` and uploads all of it, including tests, docs, type stubs and modules the Worker never imports. Nothing reduces that upload.

pywrangler picks the Python version from the top level of the default Wrangler config. It ignores `--config` and `--env`, so `pywrangler deploy --env next` can install 3.12 wheels and upload them to a 3.14 runtime. It reruns sync only when `pyproject.toml` or `pylock.toml` has a newer timestamp, so changing the compatibility date keeps the old target until the developer remembers `sync --force`.

pywrangler always adds `workers-runtime-sdk` to the lockfile. A developer cannot choose a different SDK, and a library that wants to run on more than one SDK cannot avoid pulling in the stock one.

Typed bindings go through `wrangler types`, which generates TypeScript that pywrangler converts to Python. Host packages go into `.venv-workers`, which editors and type checkers don't find without manual configuration.

## Solution

Wynd is a Python CLI, published as `wynd`, that keeps pywrangler's project layout and replaces its behavior.

- `wynd dev` installs packages for the Worker's Python target and runs `wrangler dev` on the full tree.
- `wynd deploy`, `wynd versions upload` and `wynd preview` prune vendored packages down to what the Worker can import, stage the result in `.wynd/build/` and upload it with a pinned Wrangler. `--dry-run` reports bytes before and after pruning.
- Wynd reads `--config` and `--env` before choosing the Python target, so packages always match the runtime the upload will use.
- Sync reruns whenever its inputs change, including the resolved target.
- The project declares exactly one SDK, `crosswind-workers` or `workers-runtime-sdk`, and Wynd ships only that one.
- `wynd types` reads the Wrangler config in Python and writes a typed `Env` module for crosswind-workers.
- Wynd leaves the project's normal `.venv` to `uv sync`, so editors work without setup.

## User stories

1. As a Worker developer, I want `wynd dev` to install my dependencies for the Workers runtime and start Wrangler's dev server, so that my Python Worker runs locally with one command.
2. As a Worker developer, I want Wynd to pick the Python version from my compatibility date and flags exactly as pywrangler does, so that my project behaves the same after switching.
3. As a Worker developer, I want an unsupported or unrecognized target to fail with a message naming the date and flags, so that I never install packages for the wrong Python.
4. As a Worker developer, I want `wynd deploy` to upload only the vendored files my code can import, so that my bundle is smaller.
5. As a Worker developer, I want `wynd deploy --dry-run` to print bytes before and after pruning, so that I can see what pruning saved without uploading.
6. As a Worker developer, I want the pruned tree to stay in `.wynd/build/` after a deploy, so that I can inspect what was uploaded when something goes wrong.
7. As a Worker developer, I want to list modules in `[tool.wynd] keep`, so that plugins my code imports by computed name survive pruning.
8. As a Worker developer, I want the build to fail when a vendored package contains a native binary built for my machine, so that I don't upload a Worker that crashes at import.
9. As a Worker developer, I want package metadata kept, so that libraries that call `importlib.metadata.version()` keep working.
10. As a Worker developer, I want templates and data files inside used packages kept, so that libraries like Jinja2 find their resources.
11. As a Worker developer, I want `.pth` startup hooks honored, so that SDK patches that load at startup still load in the deployed Worker.
12. As a Worker developer, I want Wynd to read `.pth` files without executing them, so that building never runs package code on my machine.
13. As a Worker developer, I want `wynd dev` to run the full unpruned tree, so that an import I add during a dev session works immediately.
14. As a Worker developer, I want sync to rerun when I change my compatibility date or flags, so that I never run packages built for the old Python version.
15. As a Worker developer, I want sync to skip when nothing relevant changed, so that `wynd dev` starts quickly.
16. As a Worker developer, I want `wynd deploy --env staging` to install packages for the staging environment's Python version, so that every environment gets matching wheels.
17. As a Worker developer in a monorepo, I want `wynd deploy -c wrangler.staging.jsonc` to use that file for everything, so that multiple configs work.
18. As a Worker developer, I want relative paths in my config, such as an assets directory or a container's Dockerfile, to keep working during deploy, so that staging doesn't break my deploy.
19. As a Worker developer, I want a clear error when my config has a relative path under a key Wynd can't rewrite, so that I find out before uploading.
20. As a Worker developer, I want every other Wrangler command passed through unchanged, so that `wynd` is the only CLI I need.
21. As a Worker developer, I want a passthrough command to exit with Wrangler's exit code, so that my scripts behave as they did with Wrangler.
22. As a Worker developer, I want Wynd to run one pinned Wrangler version, so that two machines build the same upload.
23. As a Worker developer, I want `wynd types` to generate a typed `Env` from my Wrangler config, so that my editor autocompletes bindings.
24. As a Worker developer, I want the generated `Env` to use the binding names from my config exactly, so that attribute names match what exists at runtime.
25. As a Worker developer, I want Durable Object bindings typed with my Durable Object class, so that the type checker catches wrong RPC method names and arguments.
26. As a Worker developer, I want secret names from `.dev.vars` included in `Env`, so that secrets are typed too.
27. As a Worker developer, I want `wynd dev` and `wynd deploy` to regenerate `env.py` when its content would change, so that I don't have to remember.
28. As a CI pipeline, I want `wynd types --check` to fail when `env.py` is stale, so that the config and its types never drift.
29. As a Worker developer, I want to choose my SDK by declaring `crosswind-workers` or `workers-runtime-sdk`, so that I control which `workers` package ships.
30. As a Worker developer, I want a clear error when I declare no SDK or both, so that the `workers` package is never ambiguous.
31. As a Worker developer, I want a library that depends on the SDK I didn't choose to leave it out of my bundle, so that only one `workers` package ships.
32. As a Worker developer, I want my editor to see my packages in the normal `.venv` after `uv sync`, so that I don't configure the editor by hand.
33. As a Worker developer, I want a warning when my `.venv` Python version differs from the target, so that I know editor types may not match production.
34. As a Worker developer, I want `pylock.toml` reused across syncs, so that my teammates and I resolve the same versions.
35. As a Worker developer, I want source builds off by default with an opt-in, so that only wheels built for Pyodide get installed unless I ask otherwise.
36. As a Worker developer, I want `wynd versions upload` and `wynd preview` pruned and staged like deploy, so that every upload path ships the same tree.
37. As a Worker developer, I want installation errors to stop Wynd before Wrangler runs, so that a half-installed tree never reaches dev or deploy.
38. As a Worker developer moving from pywrangler, I want the same project layout of `pyproject.toml`, Wrangler config, `src/` and `python_modules/`, so that switching needs no restructuring.
39. As a library author (agents, containers), I want Workers built by Wynd to use my library without my library declaring an SDK, so that it runs under Wynd and pywrangler.
40. As a Wynd maintainer, I want every Wrangler version bump to run a dry-run check of uploaded module names and types, so that silent Wrangler changes are caught before release.
41. As a Wynd maintainer, I want the Python target table stored as data, so that adding a Python version is one new row.
42. As a Wynd maintainer, I want each prune decision recorded with a reason, so that a user's "why was this file dropped" has an answer.

## Implementation decisions

### Modules

Each module below has one job and a small interface. The shaker, typegen and target table are pure over their inputs. Only the installer and the Wrangler runner start processes.

**Command dispatcher.** It parses the `wynd` command line, pulls out `-c`/`--config` and `-e`/`--env` (short, long and `=` forms) and sorts the command into one of four flows: Wynd-owned (`sync`, `types`), dev, upload (`deploy`, `versions upload`, `preview`) and passthrough (everything else). Other `versions` subcommands pass through, and so do `preview delete`, `settings`, `secret` and `base-config`, which upload no code. The dispatcher finds a subcommand by its name, not its position, because a flag's value can come before it. `--compatibility-date`, `--compatibility-flags` and `--latest` stop `dev` and the upload commands with an error, because Wrangler would apply them after Wynd installed packages for the config's target. Arguments it doesn't own are forwarded to Wrangler unchanged, in their original order. Wynd exits with Wrangler's exit code.

**Project loader.** It finds the project root by walking up to the nearest `pyproject.toml`, chooses the Wrangler config, parses it, and applies the chosen environment's overrides to the keys Wynd reads. Discovery mirrors Wrangler: with no `-c`, it searches the working directory and each parent for `wrangler.json`, then repeats the whole search for `wrangler.jsonc`, then `wrangler.toml`, so a `wrangler.json` in a parent beats a `wrangler.toml` in the working directory. A key set in an environment replaces the top-level value outright. `main`, `rules`, `assets`, `build` and `python_modules` are inherited when the environment leaves them out. Bindings, `vars` and `containers` are not. It also reads `[tool.wynd]` (`keep`, `allow-build`) and the project's direct dependencies. It parses JSONC with the `jsonc` package from json-with-comments and TOML with `tomllib`. It returns one immutable project description that every other module reads. No other module parses config files.

**Target table.** Each row holds a Python version, its version flag, its date threshold, the uv interpreter name and the Pyodide index URL, copied from pywrangler's table. Selection requires the base `python_workers` flag and a compatibility date, checks rows from newest to oldest, and picks the first row whose flag is present or whose threshold the date has passed. A config without the base flag or date fails with a message that names what's missing.

**SDK selector.** It reads the project's direct dependencies and returns the chosen SDK distribution. Neither declared, or both declared directly, is an error. The unchosen SDK is passed to uv's `--excludes`, so a library that depends on it resolves without it.

**Resolver and installer.** It compiles the project's dependencies for the target interpreter and index with `--no-build` (unless `allow-build` is set) into `pylock.toml`, installs the lock with `uv pip install --target .wynd/site-packages --python <target interpreter>`, and moves that directory into place as `python_modules/` only after uv succeeds, so a failed install leaves the previous tree. Any uv failure stops the command before Wrangler runs. The resolver and installer follow pywrangler's resolve and sync flow, with two differences. The SDK comes from the selector instead of being injected. The install uses `--target` instead of pywrangler's Pyodide venv, because uv 0.12.19 ignores a Pyodide venv's interpreter named through `VIRTUAL_ENV` ("system interpreter not explicitly requested"), and with `--python <venv>` it installs into `/`, the prefix Pyodide reports. `--target` also writes no `_virtualenv` hook files.

**Sync token.** A SHA-256 over the contents of `pyproject.toml` and `pylock.toml`, the resolved target (Python version, date, flags) and the Wynd version, stored in `.wynd/synced`. Sync runs when the stored hash differs, `python_modules/` is missing, or the lock has a package from a local path, whose edits the hash can't see.

**Shaker.** It takes the full site-packages tree, the project's source directory, the entry module and the keep list. It returns a shake plan listing every kept file, every dropped file with its reason, and any build errors. It never writes files.

- Roots are the entry module, the keep list, and the modules on each `.pth` file's `import` lines, parsed with `ast`. A `.pth` line that is not a plain import is a build error.
- It builds an import graph across all vendored distributions from `import` and `from` statements (relative ones included) and from `importlib.import_module` or `__import__` calls with a literal name, then walks it from the roots. A call whose name is computed but starts with literal text, such as pydantic's lazy `import_module(f".{name}", package=...)` or AnyIO's `f"anyio._backends._{name}"`, follows every module the literal start allows. A module keeps its package ancestors.
- It drops unreachable modules and whole distributions, tests, docs, `__pycache__`, `.pyi` files and `py.typed` markers.
- It keeps `.dist-info` metadata of distributions with a kept file, `.so` files whose bytes start with the WebAssembly magic number, and every non-Python file under a top-level package that has a kept module. The whole package counts, because packages such as tzdata load data files from subpackages by computed paths.
- A kept `.so` that doesn't start with the WebAssembly magic number is a build error. The message names ELF, Mach-O and PE headers.

- Imports under `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:` are skipped. Imports inside `try`/`except ImportError` and inside function bodies are followed.
- A name with no vendored file is recorded as unresolved in the plan, without an error.
- `from pkg import *` follows the submodules in `pkg`'s literal `__all__`, and `from pkg import name` follows `pkg.name` when it is a module.
- A name resolves against the source directory first, then the full tree. In one directory a package with `__init__.py` wins over an extension module, and an extension module wins over a `.py` file. A directory without `__init__.py` is a namespace package only when no directory has a regular match.
- The shaker drops files directly in site-packages, except `.pth` files.
- The shaker keeps a `.dist-info` without a `RECORD`, because it can't tell which files the distribution owns.
- The shaker keeps a module that doesn't compile but doesn't follow its imports. Python raises at import, and the importer may catch it.

**Stager.** It wipes `.wynd/build/`, shakes the full tree, and stops on the plan's build errors. It copies the project's source directory (`base_dir`, or the entrypoint's parent without it) and the shake plan's kept files into `python_modules/` there. It writes the shake plan to `.wynd/shake.txt`, one tab-separated line per file or unresolved name with the decision, the path or name, and the reason. It writes a staged config in which `main` and `base_dir` stay relative, so they resolve into the staged source, and every other known path key is rewritten to an absolute path into the original project. The rewrite applies at the top level, in every `env` section and in `previews`. The known keys are `assets.directory`, `containers[].image` when it is a Dockerfile path, `containers[].image_build_context`, `d1_databases[].migrations_dir`, `d1_databases[].migrations_pattern`, `tsconfig`, `build.watch_dir`, `alias` targets, `site.bucket` and `site.entry-point`. `wasm_modules`, `text_blobs` and `data_blobs` are left alone, because Wrangler rejects them for every Python Worker. A `containers[].image` that starts with `.` is rewritten even when the file is missing, so Wrangler's error names the absolute path. `build.cwd` resolves from the process working directory, so Wynd runs Wrangler from the user's working directory, as `dev` does, with `--config` replaced by the staged file, and leaves `build.cwd` alone. `--outdir` and `--env-file` then resolve as they would under plain Wrangler. A relative path under an unrecognized key is a build error. A value counts as relative when it starts with `./` or `../`, and `$schema`, `main`, `base_dir`, `build`, `rules`, `vars` and `define` are never checked. The source directory must be a subdirectory of the config's directory that holds the entrypoint and doesn't hold `.wynd/`, so an entrypoint beside the config is a build error. It returns the staged config's path and the shake plan.

**Typegen.** A pure function from the effective config, the `.dev.vars` key names and the binding class table to the text of `env.py`. It emits a `Protocol` named `Env` with one attribute per binding, named exactly as in the config. Durable Object classes from the same project are imported under `TYPE_CHECKING` and passed as the namespace's type argument. Check mode compares the rendered text with the file on disk. `wynd types` fails when the chosen SDK is not crosswind-workers. `env.py` goes in the source directory, and the Durable Object classes are imported from the entry module by its dotted name below that directory. A section counts as a binding when its entries carry a `binding` key, or a `name` key for `durable_objects.bindings`, `ratelimits`, `send_email`, `unsafe.bindings` and `logfwdr.bindings`. Version metadata is typed as `workers.rpc.JsDict`. A JSON var is typed from its value, and a list or object whose items differ in type gets `Any` for its items. Names that aren't Python identifiers are left out. The text follows ruff's formatter and isort, so formatting the project doesn't make `--check` fail. Wynd overwrites `env.py` only when its first line is the generated header, and otherwise stops with an error. The intended output shape:

```python
class Env(Protocol):
    COUNTER: DurableObjectNamespace[Counter]
    CACHE: KVNamespace
    API_TOKEN: str
```

**Host check.** It reads the Python version of the project's `.venv` and prints one warning when its minor version differs from the target's. It never creates or modifies `.venv`. The uv check lives in the installer, the module that runs uv: before any uv work it runs `uv --version` and stops the command when uv is missing from PATH or older than 0.12.3.

**Wrangler runner.** It runs `npx --yes wrangler@<pinned>` with the given arguments and working directory, inherits the environment, and returns the exit code. A missing `npx` is an error that names Node.js as a requirement.

**Size report.** With `--dry-run`, Wynd sums the file sizes of the full tree and of the shake plan's kept files, and prints both totals and the difference as one line: `wynd: python_modules is 2,500 bytes, 100 after pruning (2,400 fewer). Each file's decision is in .wynd/shake.txt.` It stages once and runs one Wrangler dry run. The totals exclude Wrangler's module wrapper overhead.

### Command flows

| Command | Flow |
| --- | --- |
| `sync` | load project, select target and SDK, resolve and install if the token is stale |
| `types [--check]` | load project, render `env.py`, write it or compare |
| `dev` | sync, regenerate `env.py` if its rendered text differs, host check, run `wrangler dev` with the original arguments from the working directory, so `-c` and config discovery mean the same to Wynd and Wrangler |
| `deploy`, `versions upload`, `preview` | sync, regenerate `env.py` if its rendered text differs, shake, stage, run Wrangler with `--config` set to the staged config and the user's other arguments |
| anything else | run Wrangler with the original arguments |

### Contracts with other components

- **Wrangler.** Wynd relies on the seven behaviors in the decisions file's Wrangler table. The pinned version is the contract, and bumping it requires the dry-run check.
- **crosswind-workers.** Typegen imports binding classes from `workers.bindings` using the class names in the binding coverage table, which the crosswind-workers spec owns. Version metadata uses `JsDict` from `workers.rpc`.
- **uv.** Wynd calls `uv pip compile` and `uv pip install` with pylock support, as pywrangler does at commit `cb2db3c`.

## Testing decisions

A good test runs Wynd the way a user does and checks what a user sees: files on disk, the staged tree, the printed report, the exit code and the arguments handed to Wrangler. Tests don't assert on internal function calls or intermediate data structures.

Proposed seams, which still need your confirmation:

1. **The CLI entry point, run in-process against fixture projects on disk.** The process boundary is the only substitution. uv and Wrangler calls go through one runner, and tests give it a fake that materializes a prebuilt site-packages fixture for installs and records Wrangler invocations. Every module above is covered through this seam: target selection by varying fixture configs, the shaker and stager through `deploy` with the fake Wrangler, typegen through `types` and `types --check`, and passthrough through recorded arguments.
2. **End-to-end with the real toolchain.** A small fixture Worker runs through `wynd sync`, `wynd dev` (one HTTP request) and `wynd deploy --dry-run` with real uv, the real Pyodide index and the pinned Wrangler, once per target date (3.12, 3.13 and 3.14). These tests need the network and run in a separate CI job.

Prior art: pywrangler's target-selection and flag tests (`test_py_version_detect`, `test_unsupported_flags`) are the model for target-table fixtures. The local SDK-precedence experiment from the design review (fixture Worker, background `wrangler dev`, one request) is the model for the end-to-end harness.

## Out of scope

- `wynd init` and project scaffolding.
- `publish`, which Wrangler no longer has.
- A `--pruned` mode for `wynd dev`.
- Symbol slicing, minification and execution tracing in the shaker.
- Pruning the project's own source.
- Creating or managing a host virtual environment.
- Supporting crosswind-workers under pywrangler. That depends on a pywrangler PR outside this effort.

## Further notes

Wynd has no runtime coupling to crosswind-workers beyond the binding class names typegen writes. A project on the stock SDK gets everything except `wynd types`.

The shake plan's per-file reasons make the size report and future debugging cheap, and the plan is the natural place to add symbol-level pruning later without changing the stager.

## Implementation plan

Each slice ends with something a user can run. Later slices assume earlier ones.

1. **Passthrough.** The command dispatcher and Wrangler runner, with every command passed through to the pinned Wrangler. Done when `wynd whoami` behaves like `wrangler whoami`. The pin is wrangler 4.129.0.
2. **Dev on the full tree.** Project loader, target table, SDK selector (without the override), resolver, installer, sync token, host check and the `dev` flow. Done when a fixture Worker using the stock SDK answers a request under `wynd dev` on all three targets.
3. **SDK exclusion.** `--excludes` for the unchosen SDK. Done when a fixture whose library depends on `workers-runtime-sdk` resolves with only crosswind-workers.
4. **Staged deploy without pruning.** The stager copies the full tree and rewrites config paths, and `deploy --dry-run` runs against it. Done when a fixture with assets and a relative container image path passes a dry run from `.wynd/build/`.
5. **Shaker.** The shake plan, its errors and the size report. Done when the fixture's dry run shows fewer bytes, every kept file has a reason, and the pruned fixture still answers its end-to-end request.
6. **Every upload path.** `versions upload` and `preview` use the deploy flow. Done when both commands' recorded Wrangler arguments point at the staged config.
7. **Typegen.** `wynd types`, `--check`, and regeneration inside dev and deploy. Done when the generated `env.py` for the fixture passes ty and imports at runtime.

## Map

### Destination

A Wynd spec and build order with no open decision left, so that implementation can start at slice 1 and run to slice 7 without stopping for design questions.

### Notes

Settled decisions are in [decisions.md](decisions.md). Tickets in this map are worked one per session. Wayfinder only resolves tickets. The implementation-plan slices are built after the map has no open tickets, for example one slice at a time with the tdd skill. Grilling tickets use the grilling and domain-modeling skills, research tickets use the research skill and write findings to `.design/research/`, and a ticket is claimed by writing the driver's name next to its status before any work starts. Shared tickets live in whichever map owns the decision, and the other map references them by name.

### Decisions so far

The design review settled these. Each line points at its section in the decisions file.

- [Packages and names](decisions.md#packages-and-names): Wynd replaces pywrangler. Python 3.12 to 3.14 are supported.
- [Resolution and SDK selection](decisions.md#resolution-and-sdk-selection): resolve like pywrangler, and the project declares exactly one SDK.
- [Host environment](decisions.md#host-environment): no host venv, and a version-mismatch warning.
- [Project layout](decisions.md#project-layout): full tree in `python_modules/`, cache and staging in `.wynd/`.
- [When sync runs](decisions.md#when-sync-runs): a content hash including the resolved target.
- [Config and environment flags](decisions.md#config-and-environment-flags): Wynd reads `-c` and `-e` to choose the target.
- [Staged config](decisions.md#staged-config): known path keys rewritten to absolute paths.
- [Commands](decisions.md#commands): three upload commands prune, dev runs the full tree, the rest pass through.
- [Wrangler version](decisions.md#wrangler-version): one exact pin with a dry-run check per bump.
- [Compatibility flags](decisions.md#compatibility-flags): none required.
- [Tree-shaker](decisions.md#tree-shaker): import reachability over vendored packages, with files copied verbatim.
- [Typed bindings](decisions.md#typed-bindings): a generated `Env` protocol importing from `workers.bindings`.
- [First Wrangler release supporting 2026-09-08](research/wrangler-release-for-2026-09-08.md): wrangler 4.129.0 (workerd 1.20260903.1) is the first to accept 2026-09-08, so Wynd pins it. The latest release is 4.149.0.
- [Wrangler config discovery and environment overrides](research/wrangler-config-discovery.md): `python_modules/` sits beside the config file, environments can override the compatibility date and flags, and the config search walks parent directories one file name at a time.
- [Absolute paths in staged config](research/absolute-paths-in-staged-config.md): wrangler 4.129.0 accepts absolute paths for every rewritten key. `main` and `base_dir` stay relative, `previews` and `migrations_pattern` join the rewrite list, and the blob keys drop out.
- [Removing a dependency with a uv override](research/removing-a-dependency-with-uv.md): uv's `--excludes` drops the unchosen SDK from the Pyodide resolution, and pywrangler's venv install copies uv's `_virtualenv` hook files, which Wynd's `--target` install never writes.
- [Wynd runtime dependencies](decisions.md#runtime-dependencies): `argparse` for the CLI and json-with-comments for JSONC, Wynd's only dependency. uv 0.12.3 or later must be on PATH, because users run Wynd with `uvx wynd`. The staged config is always written as `wrangler.json`.
- [Shaker edge rules](decisions.md#tree-shaker): `TYPE_CHECKING` imports skipped, optional and function-level imports followed, unresolved names recorded without failing, `.dist-info` dropped with its distribution, and literal `__all__` followed for star imports.
- [Typed binding coverage](crosswind-workers.md#decisions-so-far): decided in the crosswind-workers map. It fixes typegen's section-to-class table.

### Open tickets

None.

### Not yet specified

- Whether `wynd sync` needs an `--upgrade` flag like pywrangler's, and how `allow-build` interacts with local path dependencies.
- Platform support beyond Linux and macOS.
