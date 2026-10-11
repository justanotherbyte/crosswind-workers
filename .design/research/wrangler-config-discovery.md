# Wrangler config discovery and environment overrides

Researched 2026-10-11. Ticket from `.design/wynd.md`. Source is workers-sdk at `f8085545` (wrangler 4.127.1). `wu/` means `packages/workers-utils/src/`, `wr/` means `packages/wrangler/src/`. Links resolve as `https://github.com/cloudflare/workers-sdk/blob/f8085545bcaa2c639f171c25e4424685036a0e10/packages/<path>#L<n>`.

## 1. Discovery (high confidence)

- `-c`/`--config` is a global flag (`wr/index.ts:587-588`). When it is set, Wrangler uses that path as is and skips all searching and redirects (`wu/config/config-helpers.ts:41-48`).
- Otherwise the search starts at `dirname(script)` if a positional script was given, else `process.cwd()` (`config-helpers.ts:50`).
- The search walks upward. Each name gets a full walk to `/` before Wrangler tries the next name, in the order `wrangler.json`, then `wrangler.jsonc`, then `wrangler.toml` (`config-helpers.ts:63-66`). It uses `empathic/find.file`, which walks parent directories (empathic 2.0.0 `find.mjs`, `file()`).
- In one directory, `wrangler.json` beats `wrangler.jsonc`, which beats `wrangler.toml`. A `wrangler.json` in a parent directory also beats a `wrangler.toml` in the cwd.
- Deploy commands can redirect to `.wrangler/deploy/config.json`, which Wrangler also finds by walking upward (`wu/constants.ts:9`, `config-helpers.ts:102-116`).

## 2. Environment inheritance (high confidence)

`inheritable()` returns the env value, else the top-level value, else a default (`wu/config/validation-helpers.ts:61-80`). `notInheritable()` returns only the env value. If the key exists at the top level but not in the env, it warns and returns the default (`validation-helpers.ts:101-123`). Both use `??`, so an env value replaces the whole top-level value. Nothing is merged.

- Inheritable, so an env can override them: `compatibility_date` and `compatibility_flags` (`wu/config/validation.ts:1549-1563`), `main` (1598-1615), `rules` (2274-2285), `assets` (845-857), `python_modules` (2185-2191), and `build`, which comes from `rawEnv.build ?? topLevelEnv.build` (1539-1544).
- Not inheritable: `vars` (1661), `durable_objects` (1691), `workflows` (1703), `kv_namespaces` (1732), `containers` (1752), `queues` (1775), `r2_buckets` (1795), `d1_databases` (1805), `vectorize` (1815), `hyperdrive` (1865), `services` (1875), `analytics_engine_datasets` (1885), `ai` (1955), `images` (1965) and `ratelimits` (2055).
- Top level only, so an env cannot set it: `site` (validation.ts:538), and also `alias`, `wasm_modules`, `text_blobs` and `data_blobs` (544-560).

## 3. `python_modules/` location (high confidence)

`find-additional-modules.ts` resolves `path.resolve(entry.projectRoot, "python_modules")` (`wr/deployment-bundle/find-additional-modules.ts:137`). It throws if a `python_modules` directory exists in `moduleRoot` while `moduleRoot !== projectRoot` (143-155).

How `projectRoot` is set:
- When the entry comes from `main`, it is `dirname(config.userConfigPath)`, the user's config directory even when Wrangler follows a redirect (`wr/deployment-bundle/resolve-entry.ts:25`).
- When the entry is a positional script, `resolveEntryWithScript` sets no root (5-12) and `getEntry` falls back to `process.cwd()` (`wr/deployment-bundle/entry.ts:107`).
- `moduleRoot` comes from `--module-root`, then `base_dir`, then `dirname(main)` (`entry.ts:151-152`).

## 4. Paths resolved against the config directory

High confidence. These are normalized in `wu/config/validation.ts`:
- `main` (659-674), `base_dir` (679-694) and `pages_build_output_dir` (699-714) become absolute paths.
- `tsconfig` (2255-2269), `build.watch_dir` (637-650), `site.entry-point` (930-934) and `wasm_modules`, `text_blobs`, `data_blobs` values (991-1006) are rewritten relative to the cwd.
- `containers[].image` (when it is a Dockerfile path) and `image_build_context` (3712-3717).

High confidence. These are resolved when used:
- `assets.directory` (`wr/assets.ts:22-28, 78-79`). A CLI `--assets` value is resolved against the cwd instead.
- `site.bucket` (`wr/sites.ts:463-467`).
- `d1_databases[].migrations_dir` (`wr/d1/migrations/helpers.ts:30-31, 61`).

Implicit files relative to the config directory, which matter when copying a config:
- `.dev.vars` and `.env` (`wr/dev/dev-vars.ts:73`).
- `.wrangler/state` (`wr/dev/get-local-persistence-path.ts:38-47`).
- `python_modules/`.
- `alias` targets, which Wrangler resolves from `projectRoot` (`wr/deployment-bundle/bundle.ts:352-356`).

Medium confidence: `build.cwd` is not config-relative. Validation leaves it as written (validation.ts:613-652) and `runCommand` passes it to execa unchanged, so it resolves against the process cwd (`wr/deployment-bundle/run-custom-build.ts:94-99`).

## Unverified

- I did not scan every key. `dev.*`, `unsafe`, `previews`, `containers[].configuration.image` and the `migrations_pattern` details may hold more paths.
- I read the empathic behaviour from the 2.0.0 tarball. `^2.0.0` could resolve to a later 2.x.
- Not run. Everything above comes from reading the source.
