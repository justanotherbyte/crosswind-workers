# Python config

Design sketch for `cloudflare.config.py`, written 2026-10-22. It covers the config types users write and how Wynd finds, loads and compiles the file. [config_internals.md](config_internals.md) replaces the internal parts: the rendered file beside the config, the `Project` changes and the module map. The user-facing types below still stand. The Cloudflare side is in [cloudflare_ts_config.md](cloudflare_ts_config.md). Wrangler facts come from the `wrangler@4.129.0` package (`config-schema.json` and `wrangler-dist/cli.js`), the version Wynd pins.

## Status

Started 2026-10-22, on this file's internal shape, not config_internals.md's. The config compiles to the Wrangler dict, and `.wynd.wrangler.json` (or `.wynd.<mode>.wrangler.json`) beside it is `Project.config_path`, so typegen, `src/env.py`, staging, targets and sync are unchanged. crosswind is untouched. [config_internals.md](config_internals.md) has since moved that file to `.wynd/run/cloudflare.config.py.json` (or `cloudflare.config.py.<mode>.json`). Built:

- `wynd.config` with `_model.py`, `bindings.py`, `triggers.py`, `exports.py` and `_compile.py` (`load`, `to_wrangler`, `render`). `errors.py` holds `WyndError`, so `project -> config -> project` doesn't cycle.
- Bindings: Text, Json, Secret, D1, KV, R2, Queue, DurableObject, Workflow, Service, AI, VersionMetadata, Assets. Triggers: Cron, Fetch, Queue. All five Durable Object states, Worker and Workflow exports.
- `Project.source_path` and `Project.python_config`. Discovery picks the deeper of `cloudflare.config.py` and the Wrangler walk, and both in one directory is an error.
- `cli._run_wrangler`: for a Python config, every Wrangler call (dev, passthrough, upload) drops `-c` and `-e`, adds `--config`, and runs without `CLOUDFLARE_ENV`.
- `tests/test_python_config.py`. `wrangler@4.129.0 types` parses a rendered file with no warnings.

Departures from the sketch below:
- The compile function is `to_wrangler`, so it doesn't shadow the builtin `compile`.
- "A container needs sqlite storage" lives in the export's `__post_init__`, because it is a rule inside one object.
- `triggers.crons` is always written, `[]` included, because Wrangler leaves a missing key alone and the config is the whole truth.
- typegen has no `secrets.required` rule. A `bindings.Secret()` reaches `Env` only through `.dev.vars`, as today.

- `wynd init` writes `cloudflare.config.py` in place of `wrangler.json`. Its `pyproject.toml` has `wynd>=<the running version>` in the `dev` dependency group, so editors resolve `wynd.config`, and sync never installs it into the Worker. `.gitignore` gets `.wynd.*wrangler.json`.

Not built yet: Connect, Vectorize, Hyperdrive and the other binding kinds, and a real deploy of `exports`.

## Problem

Users write `cloudflare.config.py` instead of a Wrangler file and deploy it with Wynd. The API follows `cloudflare.config.ts`, with Python conventions in place of TypeScript ones. These decisions were settled in conversation:

- Data objects are frozen keyword-only dataclasses. There are no `define*` wrappers, no awaitable inputs, and field names are snake_case.
- Bindings, triggers and exports live in three namespaces, `bindings`, `triggers` and `exports`, because `bindings.DurableObject` and `exports.DurableObject` are different things.
- A container is written once, on the Durable Object export that runs it.
- Wynd reads the module-level name `config`, which is a `Config` or a function `(mode) -> Config`.
- Workers and exported classes are named by strings.
- `Container` takes `dockerfile=` or `image=`, never both.

Five facts from the existing system shape the design:

1. Every Wynd module after the loader reads a Wrangler-shaped dict. `targets.py` reads the compatibility settings, `stage.py` rewrites path keys, and `typegen.py` walks binding sections. All of them read it through `Project` (`wynd/src/wynd/project.py`).
2. Wrangler collects `python_modules/`, reads `.dev.vars` and keeps `.wrangler/state` beside the config file it is given, and it resolves relative paths from there. Wynd has to hand Wrangler a file, and that file's directory matters.
3. A file named `cloudflare.config.py` can't be imported by name. Worker code can't import from it, and neither can another config.
4. crosswind imports `js` and `pyodide` at module level (`workers/fetch.py`, `rpc.py`, `workflows.py`). The host can't import Worker code or any crosswind class, so the config can't reference Worker classes as objects.
5. Wrangler 4.129.0 already has cf's declarative Durable Object model. Its schema has an `exports` map whose entries are `{"type": "durable-object", "state": "created" | "deleted" | "renamed" | "transferred" | "expecting-transfer", ...}` and `{"type": "worker", "cache": {...}}`. The validator rejects `exports` together with `migrations`. On `deploy` and `versions upload`, `resolveDoLifecyclePayload` sends `exports` in place of `migrations`. Durable Object lifecycle therefore needs no migration history on Wynd's side.

## Usage

### cloudflare.config.py

```python
from wynd.config import Assets, Config, Container, Observability, Worker
from wynd.config import bindings, exports, triggers

image_processor = Container(
    name="image-processor",
    dockerfile="./containers/image/Dockerfile",
    build_context="./containers/image",
    instance_type="lite",
    max_instances=3,
)


def config(mode: str | None) -> Config:
    staging = mode == "staging"
    suffix = "-staging" if staging else ""
    return Config(
        account_id="0123456789abcdef0123456789abcdef",
        worker=Worker(
            name=f"image-worker{suffix}",
            entrypoint="src/main.py",
            compatibility_date="2026-09-08",
            assets=Assets(directory="./public", not_found_handling="404-page"),
            domains=[] if staging else ["images.example.com"],
            observability=Observability(enabled=True, head_sampling_rate=0.1),
            env={
                "GREETING": bindings.Text("staging" if staging else "hello"),
                "FEATURES": bindings.Json({"resize": True, "max_px": 4096}),
                "API_KEY": bindings.Secret(),
                "DATABASE": bindings.D1(name=f"application-db{suffix}"),
                "CACHE": bindings.KV(id="9f0c0d6e1a2b4c3d8e7f6a5b4c3d2e1f"),
                "UPLOADS": bindings.R2(name=f"uploads{suffix}"),
                "JOBS": bindings.Queue(name=f"image-jobs{suffix}"),
                "IMAGE_PROCESSOR": bindings.DurableObject("ImageProcessor"),
                "COUNTERS": bindings.DurableObject("Counter", worker="metrics"),
                "THUMBNAILS": bindings.Workflow("ThumbnailFlow"),
                "AUTH": bindings.Service("auth", export="Sessions"),
                "AI": bindings.AI(),
                # None or False leaves the binding out, as cf does.
                "DEBUG_LOGS": staging and bindings.R2(name="debug-logs"),
            },
            triggers=[
                triggers.Cron("0 * * * *"),
                triggers.Queue(f"image-jobs{suffix}", max_batch_size=10, max_retries=3),
            ],
            exports={
                "ImageProcessor": exports.DurableObject(container=image_processor),
                "ThumbnailFlow": exports.Workflow(name=f"thumbnails{suffix}"),
                "OldCache": exports.DeletedDurableObject(),
                "Tally": exports.RenamedDurableObject(renamed_to="ImageProcessor"),
            },
        ),
    )
```

A project without modes writes `config = Config(...)`. The mode is `-e`/`--env` or `CLOUDFLARE_ENV`, as Wynd reads it today. Wrangler never sees it.

`python_workers` is not listed. Wynd adds it to `compatibility_flags`, because every `cloudflare.config.py` describes a Python Worker. `compatibility_flags=[...]` holds only extra flags.

### Worker code

Worker code is unchanged from a Wrangler-config project. Wynd still generates `src/env.py`, now from the compiled config:

```python
# src/env.py. Generated by wynd types. Do not edit.
class Env(Protocol):
    DATABASE: D1Database
    CACHE: KVNamespace
    IMAGE_PROCESSOR: DurableObjectNamespace[ImageProcessor]
    COUNTERS: DurableObjectNamespace
    GREETING: str
    FEATURES: dict[str, Any]
    API_KEY: str
    ...
```

```python
# src/main.py
from env import Env
from workers import DurableObject, Response, WorkerEntrypoint


class Default(WorkerEntrypoint[Env]):
    async def fetch(self, request):
        row = await self.env.DATABASE.prepare("select count(*) as n from images").first()
        await self.env.IMAGE_PROCESSOR.get_by_name("main").resize(request.url, 200)
        return Response(f"{self.env.GREETING}: {row['n']} images")


class ImageProcessor(DurableObject[Env]):
    async def resize(self, url: str, width: int) -> None: ...
```

### Command lines

```console
$ wynd dev                 # compiles mode None into .wynd.wrangler.json, runs wrangler dev on it
$ wynd dev -e staging      # mode "staging", writes .wynd.staging.wrangler.json
$ wynd deploy -e staging   # stages .wynd/build/wrangler.json from the staging compile and deploys it
$ wynd d1 migrations apply DATABASE -e staging --remote   # passthrough, gets --config .wynd.staging.wrangler.json
```

## Shape

### Module map

```
wynd/src/wynd/
  config/
    __init__.py   Public names: Config, Worker, Container, Assets, Observability,
                  Placement, Limits, TailConsumer, and the bindings, triggers and
                  exports modules. Re-exports only.
    _model.py     Config, Worker, Container and the nested settings.
    bindings.py   Binding and one class per binding kind. Each class knows its Wrangler entry.
    triggers.py   Trigger, Fetch, Cron, Queue, Connect.
    exports.py    Export, DurableObject and its four lifecycle classes, Worker, Workflow.
    _compile.py   load(path, mode) -> Config and compile(config) -> dict. Every check
                  that spans objects lives here.
  project.py      Discovery finds cloudflare.config.py. load_project compiles it and
                  writes the rendered file. Project gains source_path.
  cli.py          For a Python config, every Wrangler call gets --config <rendered>,
                  without -c, -e or CLOUDFLARE_ENV.
  typegen.py      One added rule: names in secrets.required are typed str.
  wrangler.py     run() gains an environ parameter.
  scaffold.py     Ignores .wynd.*wrangler.json. Switching init to a Python config is separate work.
```

`targets.py`, `stage.py`, `shake.py` and `sync.py` don't change.

A deploy passes through three files:

```
cli.main -> project.load_project -> config._compile.load, compile   (the Wrangler dict, rendered file written)
cli.main -> stage.stage(project)                                     (.wynd/build/wrangler.json, as today)
cli.main -> wrangler.run([... "--config", staged])
```

### Types

#### config/_model.py

```python
@dataclass(frozen=True, kw_only=True)
class Container:
    """A container image that one Durable Object export runs.

    Exactly one of `dockerfile` and `image` is set. `build_context` and
    `build_vars` need `dockerfile`. __post_init__ raises ValueError otherwise.
    Paths are relative to cloudflare.config.py's directory.

    Compiles to containers[] {name, class_name, image, image_build_context,
    image_vars, instance_type, max_instances}. class_name comes from the export
    that holds the container.
    """

    name: str
    dockerfile: str | None = None
    image: str | None = None            # a prebuilt image reference
    build_context: str | None = None
    build_vars: dict[str, str] | None = None
    instance_type: str | None = None
    max_instances: int | None = None

    def __post_init__(self) -> None:
        raise NotImplementedError


# Nested settings. Frozen, keyword-only, each field mapped to the Wrangler key of
# the same name in snake_case.
class Assets: ...         # directory, html_handling, not_found_handling, run_worker_first
                          # directory is a Wynd addition. cf sets it outside cloudflare.config.ts.
class Observability: ...  # enabled, head_sampling_rate, redact_query_string, logs, traces
class Placement: ...      # mode: "off" | "smart", hint. The targeted forms come later.
class Limits: ...         # cpu_ms, subrequests
class TailConsumer: ...   # worker -> tail_consumers[].service


@dataclass(frozen=True, kw_only=True)
class Worker:
    """The one Worker a config describes, for one mode."""

    name: str
    compatibility_date: str                  # YYYY-MM-DD, checked in __post_init__
    entrypoint: str | None = None            # Wrangler main. None for an assets-only Worker.
    base_dir: str | None = None
    compatibility_flags: Sequence[str] = ()  # python_workers is added by compile
    env: Mapping[str, Binding | None | Literal[False]] = field(default_factory=dict)
    triggers: Sequence[Trigger] = ()
    exports: Mapping[str, Export] = field(default_factory=dict)
    domains: Sequence[str] = ()              # routes[] {pattern, custom_domain: true}
    assets: Assets | None = None
    observability: Observability | None = None
    placement: Placement | None = None
    limits: Limits | None = None
    logpush: bool | None = None
    workers_dev: bool | None = None
    preview_urls: bool | None = None
    tail_consumers: Sequence[TailConsumer] = ()


@dataclass(frozen=True, kw_only=True)
class Config:
    """What `config` names, or what `config(mode)` returns. There is no
    `containers` field: compile collects containers from the exports."""

    worker: Worker
    account_id: str | None = None
    compliance_region: Literal["public", "fedramp-high"] | None = None
```

#### config/bindings.py

Each class holds its own Wrangler mapping in private class variables. Adding a binding kind means writing one class. `compile` only special-cases the bindings that refer to exports.

```python
type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]


class Binding:
    """Base of every env value.

    `_section` is the Wrangler key, dotted for nested lists ("queues.producers").
    `_keys` maps a dataclass field to its Wrangler key. None values are left out.
    `_name_key` is the entry key that holds the binding name. `_single` marks a
    section that holds one table, not a list. A second binding of a single
    section is a compile error.
    """

    _section: ClassVar[str]
    _keys: ClassVar[Mapping[str, str]] = {}
    _name_key: ClassVar[str] = "binding"
    _single: ClassVar[bool] = False

    def _emit(self, name: str, out: dict[str, Any]) -> None:
        """Add this binding to `out` under `name`. Text, Json and Secret
        override it, because vars and secrets aren't lists of entries."""
        raise NotImplementedError


# Each class below is @dataclass(frozen=True). A class whose first field comes
# before `_: KW_ONLY` takes that field positionally.

class Text(Binding):            # vars[name] = value
    value: str

class Json(Binding):            # vars[name] = value. typegen types it from the value.
    value: JSON

class Secret(Binding):          # secrets.required += [name]
    pass

class D1(Binding):              # d1_databases[] {binding, database_name, database_id}
    name: str | None = None
    id: str | None = None

class KV(Binding):              # kv_namespaces[] {binding, id}
    id: str | None = None

class R2(Binding):              # r2_buckets[] {binding, bucket_name, jurisdiction}
    name: str | None = None
    jurisdiction: Literal["eu", "fedramp"] | None = None

class Queue(Binding):           # queues.producers[] {binding, queue, delivery_delay}
    name: str
    delivery_delay: int | None = None

class DurableObject(Binding):
    """durable_objects.bindings[] {name, class_name, script_name}.

    With no `worker`, the class is this Worker's. script_name is left out, so
    typegen keeps typing it DurableObjectNamespace[Class]. compile checks that
    `export` names a live exports.DurableObject.
    """
    export: str
    _: KW_ONLY
    worker: str | None = None

class Workflow(Binding):
    """workflows[] {binding, name, class_name, script_name, ...}.

    For this Worker's workflow, compile takes `name` and the settings from
    exports[export], so the name is written once. With `worker`, `name` is required.
    """
    export: str
    _: KW_ONLY
    worker: str | None = None
    name: str | None = None

class Service(Binding):         # services[] {binding, service, entrypoint, props}
    """cf's bindings.worker(). It is named Service so it doesn't read like wynd.config.Worker."""
    worker: str
    _: KW_ONLY
    export: str | None = None
    props: dict[str, JSON] | None = None

class Vectorize(Binding):       # vectorize[] {binding, index_name}
    name: str

class Hyperdrive(Binding):      # hyperdrive[] {binding, id, localConnectionString}
    id: str
    local_connection_string: str | None = None

class AI(Binding): ...          # ai {binding}, single
class Assets(Binding): ...      # assets.binding, single. Needs Worker.assets.
class VersionMetadata(Binding): ...  # version_metadata {binding}, single

# The other kinds. Their 4.129 sections exist in the schema, and their fields
# come from cf in snake_case: Browser, Images, Media, Stream, AISearch,
# AISearchNamespace, AgentMemory, Artifacts, Flagship, AnalyticsEngineDataset,
# SecretsStoreSecret, Pipeline, SendEmail, Logfwdr, DispatchNamespace,
# WorkerLoader, MtlsCertificate, RateLimit, VpcNetwork, VpcService.
```

Left out: K2, Analytics, `unsafe` bindings and per-binding `dev` options.

#### config/triggers.py

```python
class Trigger:
    """Base. Same contract as Binding._emit, without a name."""
    def _emit(self, out: dict[str, Any]) -> None: ...

class Cron(Trigger):        # triggers.crons += [schedule]
    schedule: str

class Fetch(Trigger):       # routes[] {pattern, zone_name}
    pattern: str
    _: KW_ONLY
    zone: str | None = None

class Queue(Trigger):       # queues.consumers[] {queue, max_batch_size, ...}, same names
    name: str
    _: KW_ONLY
    max_batch_size: int | None = None
    max_batch_timeout: int | None = None
    max_retries: int | None = None
    max_concurrency: int | None = None
    retry_delay: int | None = None
    dead_letter_queue: str | None = None

class Connect(Trigger):     # connect {protocol, port, address}
    protocol: Literal["tcp", "udp"]
    port: int
    address: str | None = None
```

cf's `email` trigger is left out. I didn't find its key in 4.129.

#### config/exports.py

Each Durable Object state is its own class. That way the type checker catches a missing `renamed_to` or a `storage` set on a tombstone.

```python
type Storage = Literal["sqlite", "legacy-kv"]

class Export: ...

# Frozen, keyword-only dataclasses. Each compiles to the Wrangler exports entry
# in the comment, which matches 4.129's schema field for field.
class DurableObject(Export):                    # {type: "durable-object", storage, container}
    storage: Storage = "sqlite"
    container: Container | None = None          # needs storage="sqlite"

class DeletedDurableObject(Export): ...          # {type, state: "deleted"}

class RenamedDurableObject(Export):             # {type, state: "renamed", renamed_to}
    renamed_to: str

class TransferredDurableObject(Export):         # {type, state: "transferred", transferred_to}
    transferred_to: str

class ExpectingTransferDurableObject(Export):   # {type, state: "expecting-transfer",
    transfer_from: str                          #  transfer_from, storage, container}
    storage: Storage = "sqlite"
    container: Container | None = None

class Worker(Export):                           # {type: "worker", cache: {enabled}}
    cache: bool | None = None

class Workflow(Export):
    """No exports entry. 4.129 declares a workflow through workflows[], which
    needs a binding, so compile merges these fields into the entry for the
    bindings.Workflow that names this export."""
    name: str
    limits_steps: int | None = None
```

#### config/_compile.py

```python
def load(path: Path, mode: str | None) -> Config:
    """Run cloudflare.config.py and return its Config for `mode`.

    The file runs with its directory on sys.path, so it can import helper
    modules beside it. It can't import Worker code. WyndError when `config` is
    missing or isn't a Config, or a callable returning one. A ValueError from a
    __post_init__ becomes a WyndError naming the file and line.
    """
    # TODO: runpy.run_path(path) with path.parent on sys.path; value = ns["config"];
    #   value = value(mode) if callable; isinstance(value, Config) or WyndError.
    raise NotImplementedError


def compile(config: Config) -> dict[str, Any]:
    """The Wrangler 4.129 dict for one mode, with no env blocks.

    Paths stay as written, because the rendered file sits beside
    cloudflare.config.py. Pure: the same Config always gives the same dict.
    Collects every error, then raises one WyndError listing them all.

    Checks that span objects:
    - each env value is a Binding, None or False; each trigger a Trigger;
      each export an Export.
    - a local bindings.DurableObject names a live exports.DurableObject, and
      a local bindings.Workflow names an exports.Workflow.
    - every exports.Workflow has exactly one binding, because workflows[] needs one.
    - a container sits on a sqlite export, is held by one export, and has a unique name.
    - a RenamedDurableObject's target is a live exports.DurableObject.
    """
    # TODO:
    #   out = {name, main, base_dir, compatibility_date, account_id, ...} with None dropped
    #   out["compatibility_flags"] = ["python_workers", *flags without it]
    #   for name, b in env (falsy dropped): b._emit(name, out)
    #   for t in triggers: t._emit(out); domains -> routes
    #   out["exports"] = {name: entry for each non-Workflow export}
    #   out["containers"] = [container entry + class_name for each export holding one]
    #   workflow exports: merge name and limits into the workflows[] entry of their binding
    raise NotImplementedError
```

#### project.py

```python
PYTHON_CONFIG = "cloudflare.config.py"


@dataclass(frozen=True)
class Project:
    root: Path
    source_path: Path    # new: the file the user wrote. Error messages name it.
    config_path: Path    # the file Wrangler reads. For a Python config, the rendered file.
    config: dict[str, Any]
    environment: dict[str, Any]   # the same dict as `config` for a Python config
    # main, base_dir, compatibility_*, dependencies, allow_build, keep_*: unchanged


def load_project(cwd: Path, config: str | None, env: str | None) -> Project:
    """For a Python config, `env` is the mode. Compiles the config and writes
    the rendered file beside it, but only when its text differs."""
    # TODO: path = cwd / config if config else _find_config(cwd)
    #   if path.suffix == ".py":
    #       compiled = compile(load(path, env))
    #       rendered = path.parent / (".wynd.wrangler.json" if env is None
    #                                 else f".wynd.{env}.wrangler.json")
    #       write the JSON when it differs; config = environment = compiled
    #   else: today's path, with source_path = config_path
    raise NotImplementedError


def _find_config(cwd: Path) -> Path:
    """Today's Wrangler walk, plus the nearest cloudflare.config.py. The deeper
    directory wins. Both in one directory is an error naming both files."""
    raise NotImplementedError
```

### Load-bearing decisions

**Wynd compiles the config to the Wrangler dict it already reads.** `compile` is the only code that reads a `Config`. `Project` exposes the compiled dict where it exposes a parsed Wrangler file today, so target selection, staging, the path rewrite and typegen work on Python configs with no changes. Wrangler configs stay supported through the same `Project`, so wynd needs no second internal model (per single source of truth).

**The rendered file sits beside `cloudflare.config.py`.** It is named `.wynd.wrangler.json`, or `.wynd.<mode>.wrangler.json` for a mode. In that directory, `python_modules/`, `.dev.vars`, `.wrangler/state` and every relative path resolve as they do for a Wrangler project, so none of them moves. Wrangler's discovery doesn't look for these names, so a plain `wrangler` run in the directory ignores them. Each mode gets its own file. Running `wynd dev` in one terminal and a staging `wynd d1 ...` in another therefore never rewrites the file `wrangler dev` is watching. Wynd writes the file only when its text changes, so an unrelated passthrough doesn't reload dev.

**Every Wrangler call for a Python config gets the rendered file.** That includes passthrough. Wynd removes `-c`/`--config` and `-e`/`--env` from the arguments, adds `--config <rendered>`, and runs Wrangler without `CLOUDFLARE_ENV`, because the rendered file has no env blocks. The upload flow keeps passing the staged file, as it does today.

**Durable Object lifecycle compiles to Wrangler `exports` field for field.** Wrangler 4.129 sends the map on upload and has the server reconcile it, so Wynd keeps no history and writes no files for it. The five states are five classes, so the type checker catches per-state fields (per encode-lessons-in-structure).

**Containers come from the exports.** Compile writes `containers[]` with `class_name` set from the holding export. It also writes the export's `container` as the container's name, which 4.129 requires to match.

**`env.py` stays generated.** Worker code keeps `from env import Env` and `WorkerEntrypoint[Env]`. Typegen keeps its one table of crosswind class names. Its only new rule types the names in `secrets.required` as `str`. Wrangler 4.129 documents `secrets.required` as replacing `.dev.vars` inference for types and warning in dev about missing secrets. On upload, it adds inherit bindings for them (`addRequiredSecretsInheritBindings`).

**Validation happens in three places, one per kind of fact.**
- The type checker checks field types and per-state fields.
- `__post_init__` checks rules inside one object, such as `dockerfile` or `image` but not both, and the date format.
- `compile` checks rules across objects and reports them all in one message.

Wrangler's validator handles everything else, because it receives a plain dict. The trust boundary is user code returning objects. `compile` checks each node with `isinstance` and then trusts its fields (per boundary-discipline).

**Interface depth.** Users import from one module, and each binding kind they use is one class. Behind that surface sit:
- Wrangler's key names, nested sections and single-table sections
- the `python_workers` flag
- the `script_name` rule
- the container `class_name` link
- workflow declaration through a binding
- mode handling and the location of the rendered file
- the `-e`/`CLOUDFLARE_ENV` stripping

Callers inside Wynd see one new field on `Project`.

**Left out on purpose.** The design has no `define*` wrappers and no awaitables. It has no Wrangler `env` blocks, no cross-config imports, and no watcher on `cloudflare.config.py` during `wynd dev`. A config edit needs a restart, as an `env.py` change does today.

## Synthesis decision

I compared two candidates.

- **Candidate A** compiled a dataclass tree to the Wrangler dict and kept `env.py` generated.
- **Candidate B** made binding declarations the type source. Each declaration was generic over its crosswind class, with a `__get__` overload, so `self.env.DATABASE` typed as `D1Database` with no generated file.

B showed that its shape can't live in `cloudflare.config.py`, because a dotted file name can't be imported. B moved `Env` to a second file, `cloudflare_env.py`, which Worker code imports under `TYPE_CHECKING` with a quoted `WorkerEntrypoint["Env"]`.

A is the base. It keeps one config file, leaves Worker code unchanged, and its typing doesn't depend on unverified checker behavior. B's typing depends on ty applying a descriptor's `__get__` to an assigned class attribute, which nobody has tested.

Taken from B:
- The rendered file beside the config. A moved `python_modules/` into `.wynd/dev/` and then needed `--env-file` and explicit D1 `migrations_dir` defaults to make up for it.
- One rendered file per mode.
- `bindings.Service` in place of `bindings.Worker`.
- Lifecycle class names that use cf's and Wrangler's terms (`ExpectingTransferDurableObject`, `transfer_from`).
- The ValueError-to-WyndError mapping in `load`.

Rejected from both: the migrations ledger. Both runners designed a committed ledger with diff and replay, because they assumed Wrangler 4.129 only understood tagged `migrations`. The 4.129 package shows the native `exports` upload path, so the ledger and its `wynd migrations` command were dropped. A's version also had a flaw. A CI deploy appends steps to the ledger and never commits them, so a later change reuses a tag that has already been applied.

Also rejected: deriving typegen's class table from the binding classes (B). It couples typegen to `wynd.config`, while typegen still has to serve Wrangler configs. The table has eight rows.

## Tradeoffs accepted

- We accept a gitignored dotfile per mode in the project directory, in exchange for leaving `python_modules/`, `.dev.vars`, local state and relative paths where Wrangler expects them.
- We accept a generated `env.py` that Wynd rewrites, in exchange for one config file and Worker code identical to a Wrangler-config project's.
- We accept that `env.py` reflects the mode of the last command that rendered it, as it reflects `-e` today, in exchange for no per-mode types.
- We accept that every command in a Python-config project runs user Python, `wynd whoami` included, in exchange for passthrough commands that find the right Worker and mode. cf does the same.
- We accept naming Workers and export classes by string, in exchange for a config that runs on the host without crosswind.
- We accept a local Durable Object binding without `script_name`, which differs from `@cloudflare/config`'s output, in exchange for typegen keeping `DurableObjectNamespace[Class]`.

## Alternatives considered

- **Env declarations as the type source.** This was candidate B. It removes the generated file, but it needs a second file, `TYPE_CHECKING` imports and a quoted generic in Worker code. Its typing also depends on unverified ty behavior. It hides less from the user than the generated `env.py`.
- **A migrations ledger.** A committed history of Wrangler `migrations` steps, advanced on deploy or by a command. It made sense only if Wrangler lacked `exports`, and it exposes migration tags and a merge-conflict-prone file to users.
- **Rendered file in `.wynd/dev/`.** It keeps the project directory clean, but it moves `python_modules/` and local state, and it needs explicit defaults for every path Wrangler resolves beside the config.
- **Domain types throughout Wynd.** Wynd would replace the Wrangler dict internally. It loses because Wrangler files would then need a parser into the same types, which means modeling the whole Wrangler schema for no user-visible gain.

## Open questions and risks

- Does a real `wrangler@4.129.0 deploy` with `exports` succeed against production for each state? The upload path is in the bundle, but no deploy has run it. A Worker that already has tagged `migrations` from a Wrangler config is the riskiest case. Does the server accept `exports` after migration tags?
- Does `wrangler dev` 4.129 give a local `exports` Durable Object sqlite storage? The dev path passes `exports` to Miniflare, but it hasn't been run.
- Should a project with both `cloudflare.config.py` and a Wrangler file in one directory fail, as sketched, or should the Python config win?
- Should `.dev.vars.<mode>` keep working? Wynd strips `-e`, so Wrangler loads only `.dev.vars`.
- Wynd must be a dev dependency so editors resolve `wynd.config`, while `uvx wynd` runs the file. Should Wynd warn when the two versions differ?
- Several binding classes map to sections that 4.129's schema has but no Wynd test covers: media, stream, ai_search, flagship, vpc and pipelines. Should v1 ship only the kinds crosswind types (KV, D1, R2, Queue, Durable Object, Service, Workflow, vars, secrets) plus AI?

## Next implementation step

Write `config/_model.py`, `exports.py` and `compile` for one Durable Object export with a container. Then run a real `wrangler@4.129.0 deploy` and `wrangler dev` on the compiled dict, to confirm the `exports` path before building the rest of the bindings.
