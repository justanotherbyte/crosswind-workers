# Absolute paths in staged config

Resolution of the "Absolute paths in staged config" task in the [Wynd map](../wynd.md), run on 2026-10-11 with wrangler 4.129.0, the version Wynd pins.

## Method

A fixture project held `src/main.py`, `public/`, `migrations/`, `site/`, `ctx/`, `tsconfig.json` and a `Dockerfile`. A staged copy in `.wynd/build/` held `src/main.py`, `python_modules/` (one small package and `pyvenv.cfg`) and a generated `wrangler.json`. Each case ran this from the project root:

```bash
npx --yes wrangler@4.129.0 deploy --dry-run --outdir <out> -c .wynd/build/wrangler.json [--env staging]
```

Each path key was set to an absolute path into the project. Where it mattered, a control case set the same key to the original relative path.

## Results

| Case | Exit | What happened |
| --- | --- | --- |
| Staged config, no extra keys | 0 | The output held the staged `main.py` and `python_modules/` with the package and `pyvenv.cfg` |
| `base_dir: "src"` | 0 | Resolved to the staged `src/` |
| `assets.directory`, absolute | 0 | "Read 1 file from the assets directory" with the absolute path |
| `assets.directory`, relative | 1 | "The directory specified by the "assets.directory" field ... does not exist: .../project/.wynd/build/public" |
| `env.staging.assets.directory`, absolute | 0 | Same as top level |
| `env.staging.assets.directory`, relative | 1 | Same error as top level |
| `containers[].image` (Dockerfile) and `image_build_context`, absolute | 0 | Wrangler built the image with Docker |
| Same, relative | 1 | "The image "./Dockerfile" does not appear to be a valid path to a Dockerfile, or a valid image registry path" |
| `d1_databases[].migrations_dir`, absolute | 0 | Accepted. Deploy doesn't read migrations |
| `tsconfig`, `alias`, `build.watch_dir`, absolute | 0 | Accepted. Python Workers don't use the JS bundler, and `watch_dir` only affects dev |
| `site.bucket`, absolute and relative | 0 and 0 | The dry run skips Workers Sites, so neither case proves anything |
| `text_blobs`, absolute | 1 | "You cannot configure [text_blobs] with an ES module worker". Python Workers are module Workers, so this key and its siblings `wasm_modules` and `data_blobs` are never valid |

## Areas the config research didn't cover

These come from wrangler 4.129.0's `config-schema.json`, not from a run.

- `dev.*` has no path keys. `dev.container_engine` takes a Docker socket URI.
- `unsafe` has no schema, so Wynd can't know its contents.
- `containers[].configuration` doesn't exist in 4.129.0. `authorized_keys` and `trusted_user_ca_keys` hold inline public keys, not file paths.
- `previews` has its own `containers` and `d1_databases`, with the same path keys as the top level.
- `d1_databases[].migrations_pattern` is a glob "relative to the Wrangler config file", which the config research missed.

## Answer

Wrangler accepts an absolute path for every key it resolves from the config directory. The stager rule becomes:

- **Keep relative,** so they resolve into the staged tree: `main` and `base_dir`.
- **Rewrite to absolute** at the top level, in every `env` section and in `previews`: `assets.directory`, `containers[].image` when it is a Dockerfile path, `containers[].image_build_context`, `d1_databases[].migrations_dir`, `d1_databases[].migrations_pattern` (prefix the glob), `tsconfig`, `build.watch_dir`, `alias` targets, `site.bucket` and `site.entry-point`.
- **Never rewrite** `wasm_modules`, `text_blobs` or `data_blobs`. Wrangler rejects them for every Python Worker anyway.

`site.bucket` is still unverified, because only a real deploy reads it.
