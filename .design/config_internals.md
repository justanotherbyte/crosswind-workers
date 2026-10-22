# Config internals

Design sketch written 2026-10-22, for how Wynd reads a project's config and hands Wrangler a file it stages in `.wynd/`. Implemented on 2026-10-22, with the differences listed under [Implementation notes](#implementation-notes). The user-facing API for `cloudflare.config.py` is in [python_config.md](python_config.md), and this file replaces that file's internal shape. Wrangler facts come from the `wrangler@4.129.0` package Wynd pins: `config-schema.json`, and `wrangler-dist/cli.js` cited by line number.

## Problem

Every Wynd command builds one internal config, from either `cloudflare.config.py` or a Wrangler file (`wrangler.json`, `wrangler.jsonc` or `wrangler.toml`). Wynd then stages a `wrangler.json` in `.wynd/` and passes it to `npx wrangler`. Today only uploads stage a file. `dev` and passthrough commands run Wrangler on the user's own file.

Four facts shape the design:

1. **The Wrangler schema is big.** It has about 90 top-level keys and many per-entry keys Wynd never reads, such as `preview_id`, `remote`, `unsafe`, `build`, `rules`, `alias`, `migrations` and `previews`. An existing Wrangler project has to reach Wrangler exactly as before. Empty and missing values also differ: `triggers.crons: []` clears a Worker's schedules, while a missing key leaves them alone (cli.js:151499).
2. **Wrangler reads files beside the config it's given.** The config passed with `--config` decides where Wrangler looks for these:
   - `python_modules/` (cli.js:138507). Its schema entry has only `exclude`, so nothing moves it.
   - `.dev.vars*` and `.env*` (cli.js:176647-176726).
   - `.wrangler/state` (cli.js:187908).
   - The D1 `migrations` default (cli.js:222699, 225449).
   - Every relative path in the file.

   Moving the config into `.wynd/` moves all of these with it.
3. **Two flags look like fixes, but neither works.**
   - `--env-file` turns off `.dev.vars`, expands `$` values, and loads the file into Wrangler's own environment (cli.js:176652, 351247).
   - `--persist-to` exists on about 17 commands, so Wynd would need a hand-kept list of them, and `d1 execute` rejects it without `--local` (cli.js:223362).
4. **Two behaviours change once the file is staged.**
   - `wrangler dev` watches only the file it was given (cli.js:199519-199611). Editing the user's file no longer reloads dev unless Wynd restages it.
   - `d1 create`, `kv namespace create` and `r2 bucket create` write new bindings into the file they were given (cli.js:222605). That's now the staged copy.

Every module after the loader reads the config through `Project` today: `targets`, `sync`, `typegen`, `stage`, `host` and `cli`.

## Usage

### cli.py

```python
def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    options, rest = _parser.parse_known_args(args)
    flow = _flow(rest)
    cwd = Path.cwd() / options.cwd if options.cwd else Path.cwd()
    mode = options.env or os.environ.get("CLOUDFLARE_ENV")

    try:
        if flow == "init":
            ...  # unchanged
        try:
            project = load_project(cwd, options.config, mode)
        except ProjectNotFound:
            if flow != "passthrough":
                raise
            return wrangler.run(args)  # `wynd login` outside any project, as today

        if flow == "types":
            write_env(project, check="--check" in rest)
            return 0
        if flow != "passthrough":
            target = select_target(project.config)
            sync(project, target)
            if flow != "sync" and select_sdk(project.dependencies) == "crosswind-workers":
                write_env(project)
        if flow == "sync":
            return 0

        if flow == "upload":
            staged, plan = stage_upload(project)
            if "--dry-run" in rest:
                print(f"wynd: {plan.size_report(staged.path.parent / 'python_modules')}", flush=True)
        else:
            staged = stage_run(project)
    except WyndError as error:
        print(f"wynd: error: {error}", file=sys.stderr)
        return 1

    if flow == "dev":
        warn_on_venv_mismatch(project, target)
    argv, environ = project.source.wrangler_args(args, staged.path)
    restage = (lambda: stage_run(load_project(cwd, options.config, mode))) if flow == "dev" else None
    code = wrangler.run(argv, environ=environ, watch=project.source.path, restage=restage)
    staged.warn_if_edited(project.source.path)
    return code
```

What Wrangler receives, for a project with `wrangler.jsonc` at its root:

```console
$ wynd dev --port 8788
  wrangler dev --port 8788 --config <root>/.wynd/run/wrangler.jsonc.json
$ wynd d1 migrations apply DB --local -e staging
  wrangler d1 migrations apply DB --local -e staging --config <root>/.wynd/run/wrangler.jsonc.json
$ wynd deploy -e staging
  wrangler deploy -e staging --config <root>/.wynd/build/wrangler.json
```

For a `cloudflare.config.py` project, `-e` picks the mode, and Wrangler never sees it:

```console
$ wynd dev -e staging
  wrangler dev --config <root>/.wynd/run/cloudflare.config.py.staging.json   (CLOUDFLARE_ENV removed)
```

### Readers of the model

```python
# targets.py
def select_target(config: WranglerConfig) -> Target:
    flags = config.compatibility_flags
    found = (
        f"{config.source.name} has compatibility_date "
        f"{config.compatibility_date!r} and compatibility_flags {list(flags)}"
    )
    ...  # the rest is today's body


# typegen.py
def write_env(project: Project, check: bool = False) -> None:
    config = project.config
    secrets = [*config.required_secrets, *_dev_var_names(config.source.parent / ".dev.vars")]
    text = render_env(config.bindings, config.vars, secrets, config.entry_module)
    path = config.source_dir / "env.py"
    ...  # compare, check, write: unchanged
```

`typegen.CLASSES` stays in typegen, and it maps a Wrangler section to a crosswind class name. `sync` reads `config.source`, `compatibility_date` and `compatibility_flags` for its token, and installs into `project.python_modules`.

### Tests

```python
def test_a_wrangler_file_reaches_wrangler_unchanged_but_for_its_paths(
    tools: Tools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        **config(),
        "name": "w",
        "migrations": [{"tag": "v1", "new_sqlite_classes": ["Counter"]}],
        "unsafe": {"bindings": [{"name": "X", "type": "y"}]},
        "rules": [{"type": "Data", "globs": ["**/*.txt"]}],
        "triggers": {"crons": []},
        "assets": {"directory": "./public"},
        "d1_databases": [{"binding": "DB", "database_name": "d", "database_id": "i"}],
        "env": {"staging": {"name": "w-staging", "assets": {"directory": "./staging"}}},
    }
    root = make_project(tmp_path / "w", raw)
    (root / ".dev.vars").write_text("API_KEY=1\n")
    monkeypatch.chdir(root)

    assert main(["d1", "migrations", "apply", "DB", "--local", "-e", "staging"]) == 0

    staged = root / ".wynd" / "run" / "wrangler.jsonc.json"
    assert tools.wrangler() == [[
        "d1", "migrations", "apply", "DB", "--local", "-e", "staging", "--config", str(staged),
    ]]
    assert json.loads(staged.read_text()) == {
        **raw,
        "main": "../../src/entry.py",
        "assets": {"directory": str(root / "public")},
        "d1_databases": [{**raw["d1_databases"][0], "migrations_dir": str(root / "migrations")}],
        "env": {"staging": {"name": "w-staging", "assets": {"directory": str(root / "staging")}}},
    }
    assert (root / ".wynd" / "run" / ".dev.vars").read_text() == "API_KEY=1\n"
```

The expected paths are written out by hand, not computed from `PATH_FIELDS`, so a key missing from the table fails the test. A second test writes a `cloudflare.config.py` and the `wrangler.json` it should equal. It stages both and checks that the two staged files are identical.

## Shape

### Module map

```
wynd/src/wynd/
  errors.py        new. WyndError and ProjectNotFound, moved out of project.py to
                   break the project -> sources -> config -> project import cycle.
  sources.py       new. ConfigParser (ABC), WranglerConfigParser, PythonConfigParser,
                   and discovery. Takes _read from project.py.
  wrangler_config.py  new. WranglerConfig and BindingRef. Holds the Wrangler dict,
                   parses the typed view, writes staged files. Takes INHERITED and
                   _environment from project.py, PATH_FIELDS, _rewrite and
                   _dot_relative_paths from stage.py, and the binding walk and
                   _entry_module from typegen.py.
  project.py       Project (root, source, config, pyproject settings) and load_project.
  stage.py         stage_run (dev and passthrough), stage_upload (today's stage), StagedFile.
  config/          the user-facing package from python_config.md. _compile.run(path, mode)
                   returns a Wrangler dict. Only PythonConfigParser imports it.
  typegen.py       reads config.bindings, vars, required_secrets and entry_module. Keeps CLASSES.
  targets.py       select_target(config: WranglerConfig).
  sync.py          token from config fields. Tree and token live in project.run_dir.
  host.py          reads project.config.
  cli.py           the flow above. Every Wrangler call gets --config <staged>.
  wrangler.py      run(args, *, environ=None, watch=None, restage=None).
  scaffold.py      drops python_modules/ from IGNORED, because the tree now lives in .wynd/.
```

A deploy goes `cli.main` -> `project.load_project` -> `sources.ConfigParser.parse`, then `cli.main` -> `stage.stage_upload` -> `WranglerConfig.to_wrangler`.

### .wynd/ layout

```
<root>/
  wrangler.jsonc  .dev.vars  src/  public/  migrations/      the user's files, untouched
  .wynd/
    run/                        stands in for the directory of the root's config file
      wrangler.jsonc.json       staged for dev and every passthrough
      cloudflare.config.py.staging.json   a Python config gets one file per mode
      python_modules/           the full tree, moved here from <root>/python_modules
      synced                    its sync token, moved from .wynd/synced
      .dev.vars  .env*          copies of the files beside the source config
      .wrangler/state/          local state for dev, d1 --local, kv --local
      other/                    the same layout for a config in <root>/other/
    build/                      upload only, wiped for each upload, as today
      wrangler.json  src/  python_modules/
    excludes.txt  site-packages/  shake.txt   as today
```

Each piece answers one constraint from the problem section:

| Constraint | How the layout meets it |
| --- | --- |
| `python_modules/` beside the config | The full tree lives in the run directory, beside every staged file. |
| `.dev.vars` and `.env` beside the config | `stage_run` copies every `.dev.vars*` and `.env*` file when its bytes differ, and deletes copies whose source is gone. Dev never watched these files, so behaviour matches today. |
| `.wrangler/state` beside the config | State lives in the run directory, shared by dev and every `--local` command. Existing `<root>/.wrangler/state` stays behind, and Wynd warns once. |
| Relative paths and the D1 default | `to_wrangler` makes known path keys absolute, writes D1's default `migrations_dir` out, and points `main` and `base_dir` at the code. |
| Commands running at once | Each source file, and each Python mode, gets its own staged file. A file is replaced atomically and only when its text changes, so a passthrough never reloads a running dev. |
| Dev watching only its file | During `wynd dev`, `wrangler.run` checks the source file's mtime every second, and restages it when it changes. Wrangler reloads because the staged text changed. |
| Wrangler writing into its file | `StagedFile.warn_if_edited` compares the file after the run and prints the keys Wrangler added, naming the source file to copy them into. The next command overwrites the staged file anyway. |

### Types

#### sources.py

```python
__all__ = ("ConfigParser", "PythonConfigParser", "WranglerConfigParser")


class ConfigParser(ABC):
    """One config file and its language's rules.

    A subclass sets its file names and says whether Wrangler sees -e, and it
    produces the Wrangler dict for a mode. Discovery, staged-file naming and
    argument rewriting are written once, here.
    """

    names: ClassVar[tuple[str, ...]]
    passes_env: ClassVar[bool]

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @abstractmethod
    def _payload(self, mode: str | None) -> dict[str, Any]:
        """The Wrangler dict, paths relative to path.parent."""

    def parse(self, mode: str | None) -> WranglerConfig:
        env = mode if self.passes_env else None
        return WranglerConfig(self.path, env, self._payload(mode))

    def staged_name(self, mode: str | None) -> str:
        """wrangler.jsonc.json, or cloudflare.config.py.staging.json for a mode.
        Wrangler picks its parser from the .json suffix (cli.js:3360)."""
        if self.passes_env or mode is None:
            return f"{self.path.name}.json"
        return f"{self.path.name}.{mode}.json"

    def wrangler_args(self, args: list[str], staged: Path) -> tuple[list[str], dict[str, str] | None]:
        """Wrangler's arguments and environment for a run on `staged`.

        Removes -c/--config and adds --config staged. When not passes_env, also
        removes -e/--env and CLOUDFLARE_ENV, because -e on a file with no env
        blocks still renames the Worker to name-<env> (cli.js:19701). An
        environment of None means Wynd's own.
        """
        raise NotImplementedError

    @staticmethod
    def find(cwd: Path, config: str | None) -> ConfigParser:
        """-c picks a parser by file name. Without it, walk up as Wrangler does,
        one name at a time, with cloudflare.config.py included. The deeper
        directory wins, and two kinds in one directory is a WyndError naming both.
        Raises ProjectNotFound when nothing is found."""
        raise NotImplementedError


class WranglerConfigParser(ConfigParser):
    names = ("wrangler.json", "wrangler.jsonc", "wrangler.toml")
    passes_env = True

    def _payload(self, mode: str | None) -> dict[str, Any]:
        """The file as parsed, env blocks included. Wrangler applies -e itself."""
        raise NotImplementedError   # today's project._read


class PythonConfigParser(ConfigParser):
    names = ("cloudflare.config.py",)
    passes_env = False

    def _payload(self, mode: str | None) -> dict[str, Any]:
        """config._compile.run(path, mode). It has no env blocks, because the
        mode was applied while the config ran. WyndError for a mode that isn't
        [A-Za-z0-9_-]+, because the mode becomes part of a file name."""
        raise NotImplementedError
```

#### wrangler_config.py

```python
__all__ = ("BindingRef", "JSON", "WranglerConfig")

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]


@dataclass(frozen=True)
class BindingRef:
    """One binding of the effective config, as typegen needs it."""

    name: str                 # the Env attribute
    section: str              # dotted for nested lists, such as "queues.producers"
    class_name: str | None = None
    script_name: str | None = None


@dataclass(frozen=True, eq=False)
class WranglerConfig:
    """One Worker config, as Wynd reads it and as Wrangler will receive it.

    Invariant: `_payload` is the only state. It is the Wrangler dict exactly as
    the source gave it, with env blocks, migrations, unsafe, build, rules and
    previews, and with paths relative to source.parent. Every typed attribute is
    a cached_property parsed from `_payload` and `env`, and no constructor
    argument sets one. What Wynd reads therefore comes from the same dict Wrangler
    receives. Nothing outside this module reads `_payload`.

    Typed attributes parse lazily and raise WyndError on a malformed value, so an
    assets-only Worker with no `main` still loads for passthrough.
    """

    source: Path              # the file the user wrote
    env: str | None           # the -e env Wrangler will apply. Always None for a Python config.
    _payload: dict[str, Any] = field(repr=False)

    @cached_property
    def _settings(self) -> dict[str, Any]:
        """The env's table over the INHERITED top-level keys, today's
        project._environment. A payload with no env blocks is its own settings."""
        raise NotImplementedError

    @cached_property
    def main(self) -> Path | None: ...                 # absolute, against source.parent
    @cached_property
    def source_dir(self) -> Path: ...                  # base_dir or main's directory
    @cached_property
    def entry_module(self) -> str: ...                 # main's dotted name below source_dir
    @cached_property
    def compatibility_date(self) -> str | None: ...    # a TOML date becomes ISO text
    @cached_property
    def compatibility_flags(self) -> tuple[str, ...]: ...
    @cached_property
    def bindings(self) -> tuple[BindingRef, ...]: ...  # today's typegen._bindings walk
    @cached_property
    def vars(self) -> Mapping[str, JSON]: ...
    @cached_property
    def required_secrets(self) -> tuple[str, ...]: ... # secrets.required

    def to_wrangler(self, path: Path, *, code_root: Path) -> str:
        """Write the payload as JSON at `path`, so Wrangler reading `path`
        resolves what it would resolve reading `source`. Return the text.

        `code_root` holds the Worker source. For dev and passthrough it is
        source.parent, and for upload it is the staged tree. main and base_dir
        point into it, relative to path.parent. At the top level, in every env
        block and in every previews entry, these become absolute against
        source.parent: the PATH_FIELDS keys, container images that name files,
        tsconfig and relative alias targets. A D1 entry with neither
        migrations_dir nor migrations_pattern gets source.parent / "migrations".
        Every other key is copied unchanged, so `crons: []` stays `[]`.

        Raises WyndError for a "./" or "../" string under a key Wynd doesn't know.
        Replaces `path` atomically, and only when the text differs.
        """
        raise NotImplementedError
```

#### project.py and stage.py

```python
@dataclass(frozen=True)
class Project:
    """A Worker config plus the pyproject settings Wynd reads beside it."""

    root: Path
    source: ConfigParser
    config: WranglerConfig
    mode: str | None
    dependencies: tuple[str, ...]
    allow_build: bool
    keep_modules: tuple[str, ...]
    keep_docstrings: bool

    @property
    def wynd_dir(self) -> Path:
        return self.root / ".wynd"

    @property
    def run_dir(self) -> Path:
        """Stands in for the config's directory in every dev and passthrough run."""
        return self.wynd_dir / "run" / self.source.path.parent.relative_to(self.root)

    @property
    def python_modules(self) -> Path:
        return self.run_dir / "python_modules"


def load_project(cwd: Path, config: str | None, mode: str | None) -> Project:
    """ProjectNotFound with no pyproject.toml or no config from cwd up. WyndError
    for a config outside the pyproject directory or a bad [tool.wynd]."""
    raise NotImplementedError


# stage.py
@dataclass(frozen=True)
class StagedFile:
    path: Path
    text: str

    def warn_if_edited(self, source: Path) -> None:
        """Print the keys Wrangler added to the file, such as a binding written
        by `d1 create` (cli.js:222605), and name `source` as the file to copy
        them into."""
        raise NotImplementedError


def stage_run(project: Project) -> StagedFile:
    """Stage the config for dev and passthrough. Writes run_dir /
    source.staged_name(mode) with code_root = source.parent, and syncs the
    .dev.vars* and .env* copies. It writes nothing when nothing changed."""
    raise NotImplementedError


def stage_upload(project: Project) -> tuple[StagedFile, ShakePlan]:
    """Today's stage(): shake into .wynd/build/, copy the module root, then
    config.to_wrangler(build / "wrangler.json", code_root=build)."""
    raise NotImplementedError
```

### Load-bearing decisions

**The internal model is a typed view over the Wrangler dict.** `WranglerConfig` stores the dict and nothing else, and every field Wynd reads is computed from it. The fields and the dict can't disagree, because there is no second copy (per single source of truth). Unknown keys, per-entry fields, `migrations`, `unsafe` and `crons: []` reach Wrangler untouched, without any code that names them.

**The user's `Config` is not the internal model.** `cloudflare.config.py` compiles in one direction, into a Wrangler dict, and only `PythonConfigParser` imports `wynd.config`. Candidate C tried to use one class for both directions. That would need three changes to the user API:
- every field defaults to `None`, so `name` and `compatibility_date` stop being required for the type checker
- every class gains an `extra` mapping
- the parser needs a fallback that leaves a section raw when it can't rebuild that section exactly

Those costs land on every user to serve Wrangler-file round trips.

**`ConfigParser` stays an ABC, with the small overrides your sketch had.** The two sources differ in four things: file names, how to get the dict, whether Wrangler sees `-e`, and how the staged file is named. The subclasses set or override exactly those. Discovery and argument rewriting live once in the base class. That keeps per-source branches out of `cli` and `WranglerConfig`.

**`-e` belongs to the source.** A Wrangler file keeps its env blocks, and `-e` goes to Wrangler, which applies its own naming and inheritance rules. Wynd applies the env only for its own reads, through `_settings`. A Python config applies the mode while compiling. Wynd removes `-e` and `CLOUDFLARE_ENV` before calling Wrangler, so the Worker isn't renamed `name-<mode>`.

**`to_wrangler(path, *, code_root)` takes the destination.** That's because the relative `main` and `base_dir` depend on where the file lands. The same method serves dev, where `code_root` is the project, and upload, where it's the staged copy. The path table moves next to it, so one module knows Wrangler's path rules.

**Interface depth.** Callers see two calls, `load_project` and `ConfigParser.wrangler_args`, plus one model with eight typed fields and one write method. The model hides:
- JSONC and TOML parsing, and running the Python config
- env inheritance and the binding walk
- path rebasing and the D1 default
- the unknown-path check, and atomic writes that skip unchanged text

`Project` shrinks to identity, the parser, the model and the pyproject settings.

**Left out on purpose.** There's no Worker `name` field and no `python_modules.exclude` field, because nothing in Wynd reads them. Bindings aren't typed beyond what typegen reads. Wynd doesn't flatten env blocks for Wrangler, and it uses no symlinks.

## Synthesis decision

I compared two candidates.

- **Candidate C** took the proposed shape all the way. Both parsers produced the user-facing `Config`, with an `extra` mapping on every class so Wrangler files survived the round trip. `Config.to_wrangler()` was pure, and a separate `relocate` rewrote paths.
- **Candidate D** kept a narrow typed view over the Wrangler dict, with no ABC.

D is the base. C showed that one class for both directions makes required fields optional, adds `extra` to every user class, and needs a fallback when a section can't be rebuilt. D's view needs none of that, and its fields can't drift from the dict.

Taken from C:
- The `ConfigParser` ABC. D had replaced it with one `if` on the file name, plus a `forwards_env` property and a `staged_name` property that also checked the name. Those are per-source facts, so they belong on per-source classes.
- Warning when Wrangler writes into the staged file. C found that write in the bundle, and D missed it.
- The dev poll that restages on a source edit. D only listed it as an open question.
- The finding that `-e` renames a Worker even when the file has no env blocks.

Rejected from C:
- One staging directory and one full tree per mode. It costs disk, and it re-syncs nothing D's single run directory doesn't.
- The `.wrangler` symlink, because Wynd already handles Windows (`wrangler.py` finds `npx.cmd`), where symlinks need Developer Mode.
- A 36-key copy of Wrangler's inheritance rules. D's `_settings` reuses today's `INHERITED` for the few fields Wynd reads.

## Tradeoffs accepted

- We accept a model that doesn't type most of the Wrangler schema, in exchange for Wrangler files that reach Wrangler unchanged with no round-trip code.
- We accept moving the full tree from `<root>/python_modules` to `.wynd/run/python_modules`, in exchange for Wrangler finding it beside every staged file. CONTEXT.md's "full tree" entry needs updating.
- We accept that existing local D1 and KV data under `<root>/.wrangler/state` stays behind, with a one-time warning, in exchange for one state directory shared by dev and `--local` commands without a list of commands.
- We accept copying `.dev.vars` into the gitignored `.wynd/`, in exchange for Wrangler's own `.dev.vars.<env>` and `.env` selection.
- We accept a one-second poll during `wynd dev`, which re-runs the Python config in Wynd's process, in exchange for reload on config edits, as dev has today.
- We accept that the unknown-relative-path error now also fires for dev and passthrough, in exchange for no command silently resolving a path into `.wynd/run/`.
- We accept a config outside the pyproject directory being an error, in exchange for a run directory every config can name.

## Alternatives considered

- **The user's `Config` as the internal model (candidate C).** It exposes the whole Wrangler schema through user classes, or it loses keys. To stay exact, it needs `extra` everywhere, `None` defaults and a fallback for each section. It hides less behind a bigger public surface.
- **A typed model plus one `extra` dict.** Typed fields own some keys and `extra` owns the rest. Writing merges two owners, and a key Wynd starts typing has to move between them. That's split ownership, which the computed view avoids.
- **`--env-file` and `--persist-to` instead of a run directory.** `--env-file` changes how values load, and `--persist-to` would need a hand-kept list of about 17 commands.
- **The rendered file beside the source, the previous round's shape.** It leaves Wrangler's lookups alone, but it puts dotfiles in the project directory, and you asked for `.wynd/`.

## Open questions and risks

- Riskiest assumption: does any passthrough command read a path from the config directory that `PATH_FIELDS` misses? The list was built for uploads. A bare relative value under an unknown key, such as `"public"` rather than `"./public"`, would resolve into `.wynd/run/` with no error.
- Should Wynd move existing `<root>/.wrangler/state` into the run directory on first run, instead of only warning?
- Should a Python mode select `.dev.vars.<mode>`? Copying it over `.dev.vars` in the run directory would make two modes running at once fight over one file.
- Should passthrough parse the config at all? It now does, so a config Wynd can't read breaks `wynd whoami` inside a project.
- Two `wynd dev` runs on different Python targets share one full tree and resync against each other, as they do today. Is that acceptable?
- No step here has run against real Wrangler. Do `wrangler dev` and `d1 migrations apply --local` work on a staged file in `.wynd/run/`, with a `main` relative to it?

## Next implementation step

1. Write `WranglerConfig` with its typed fields and `to_wrangler`.
2. Write `WranglerConfigParser` and move `targets`, `typegen` and `sync` onto the model.
3. Make the round-trip test pass. Do all of this before touching `config/`.

## Implementation notes

The build follows this sketch, with these differences:

- `WranglerConfig.main` returns a `Path` and raises `WyndError` when the config sets none. Passthrough never reads it, so an assets-only Worker still stages.
- The exception is `ProjectNotFoundError`, because ruff's N818 wants the suffix.
- Wynd warns about `<root>/.wrangler/state` once by creating an empty `.wynd/run/.wrangler/state/`. It doesn't move existing data.
- A dev restage stages the config again but doesn't sync. A changed `compatibility_date` reaches `python_modules/` on the next `wynd dev`.
- `WranglerConfig.to_wrangler` raises the "can't encode" error that `_compile.render` used to raise, so a Python config and a TOML date share one JSON path.
- `required_secrets` now reach `env.py`, so a `bindings.Secret()` types as `str` without a `.dev.vars` entry.

Two open questions now have answers from `uv run pytest -m e2e`. `wrangler dev` serves a Worker from `.wynd/run/` with a `main` relative to it, on all three targets. `d1 migrations apply --local` reads `<root>/migrations` through the written-out `migrations_dir` and keeps its state in `.wynd/run/.wrangler/state/`. Wrangler still writes `.wrangler/cache/cf.json` in the working directory, which is harmless.
