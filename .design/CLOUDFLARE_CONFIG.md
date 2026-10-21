# cloudflare.config.ts, and a Python equivalent for Wynd

This doc researches what Wynd needs for a `cloudflare.config.py` that covers everything `cloudflare.config.ts` does, including the `env` type inference. I wrote it on 2026-10-21. [Decided](#decided) lists what is settled. The rest is research.

Sources, all read on that date:

- [Programmatic configuration](https://developers.cloudflare.com/cf/projects/cloudflare-config/), [Configuration explorer](https://developers.cloudflare.com/cf/projects/config-explorer/), [Develop, build, and deploy](https://developers.cloudflare.com/cf/projects/), [Migrate a Wrangler project](https://developers.cloudflare.com/cf/wrangler/migrate/) and [Wrangler to cf reference](https://developers.cloudflare.com/cf/wrangler/reference/).
- `@cloudflare/config` 0.27.0 from npm, the package behind `cf/config`. Its `.d.ts` files and `index.mjs` are the source for every field and builder below. Cloudflare generated the docs' explorer from 0.25.0.
- `cf` 1.0.0-beta.20, which depends on `@cloudflare/config` 0.27.0.
- `wrangler` 4.151.3 (latest, bundles `@cloudflare/config` 0.27.0) and 4.129.0 (Wynd's pin, bundles 0.10.0).

## Summary

- `cloudflare.config.ts` is a TypeScript module whose default export describes one Worker, its Container applications and two account settings. It replaces `wrangler.jsonc` for the new `cf` CLI. It is in open beta.
- Every builder (`bindings.kv()`, `triggers.queue()`, `exports.durableObject()` and the rest) returns a plain object with a literal `type` field and camelCase keys. The loader resolves functions and promises, validates the result with zod, and converts it to a Wrangler config with `convertToWranglerConfig`.
- TypeScript computes the Worker's `Env` type from the config's own type, through `InferEnv<typeof config>`. Nothing generates a binding table. Python can't compute a type from a value's type, so a Python config needs a different mechanism.
- A class whose attributes are builder descriptors gives the same inference in Pyright and mypy, both in strict mode, with no code generation. That includes `Queue[Job]`, `DurableObjectNamespace[Counter]` and `X | None` for a binding that only some modes define. See [Typing env in Python](#typing-env-in-python).
- Wynd loads `cloudflare.config.py` by path, builds the config from plain Python objects, validates it, and converts it to the staged `wrangler.json` itself. Wynd stages no TypeScript. See [Decided](#decided).
- Wynd's pinned Wrangler 4.129.0 validates every top-level key the conversion produces, including `exports`, except `k2` and `analytics`. Those two need a newer pin. See [Converting to wrangler.json](#converting-to-wranglerjson).

## Decided

These decisions date from 2026-10-21.

- The Python config file is `cloudflare.config.py`. It is an alternative to `wrangler.jsonc`, and it holds configuration only.
- Wynd loads it from its path with `importlib.util.spec_from_file_location`, so the dot in the name doesn't matter.
- `Env` lives in the user's source code, such as `src/env.py`, and `cloudflare.config.py` imports it. Worker code never imports the config file.
- Wynd looks for four config files: `cloudflare.config.py`, `wrangler.jsonc`, `wrangler.json` and `wrangler.toml`. Finding more than one is an error.
- Wynd builds the config from plain Python objects and types, then validates and converts it in Python. It doesn't stage a `cloudflare.config.ts` or run `wrangler --experimental-new-config`.

## What the file is

`cloudflare.config.ts` is in the project root. Its default export is the result of `defineConfig()`. The file is an ordinary ES module, so it can import other files, read `process.env`, call functions and await values.

Node.js 22.18 or later loads it through module hooks (`module.registerHooks`). The loader rejects Bun with `cloudflare.config.ts loading is not supported on Bun`. The project's `package.json` needs `"type": "module"`.

These tools read the file:

| Reader | What it reads | Where it looks |
| --- | --- | --- |
| `cf dev`, `cf build`, `cf deploy` and other project commands | The whole config, through the Vite plugin or Wrangler | Only the directory the command runs in |
| `cf` API commands, such as `cf d1 list` | `accountId` and `complianceRegion` only. They don't call nested `worker` and `containers` factories. | The nearest file from the working directory up to the filesystem root |
| `wrangler --experimental-new-config` | The whole config, plus an optional `wrangler.config.ts` for build settings | Only the working directory. It rejects `--config`. |

A syntax error, import error or top-level exception breaks every reader, including API commands that only need the account ID.

Build settings don't go in `cloudflare.config.ts`. A Wrangler-built project keeps them in `wrangler.config.ts`, whose top-level keys are `noBundle`, `minify`, `keepNames`, `alias`, `define`, `findAdditionalModules`, `preserveFileNames`, `baseDir`, `rules`, `wasmModules`, `textBlobs`, `dataBlobs`, `tsconfig`, `jsxFactory`, `jsxFragment`, `pythonModules`, `uploadSourceMaps`, `build`, `assetsDirectory`, `types`, `dev` and `sendMetrics`. `baseDir`, `rules` and `pythonModules` are the keys a Python Worker uses today.

## Evaluation

### Values, promises and factories

`defineConfig()`, `defineWorker()` and `defineContainer()` each accept `ConfigInput<T>`, which is one of these:

- a `T`
- a `Promise<T>`
- a function `(ctx) => T | Promise<T>`

All three helpers return their argument unchanged. They exist so TypeScript keeps literal types (`const` type parameters) and checks the shape.

The context has two fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `mode` | `string \| undefined` | Set with `--mode` (or `-m`). Wrangler takes it from `--env`, then from `CLOUDFLARE_ENV`. |
| `isPreview` | `boolean` | `true` when building for `cf previews deploy` |

The default mode depends on the tool:

| Command | Default mode |
| --- | --- |
| `cf dev` through the Vite plugin | `development` |
| `cf build`, `cf deploy` through the Vite plugin | `production` |
| Anything built with Wrangler | `undefined` |
| API commands | `undefined` |

A mode returns one complete configuration. Nothing merges the way Wrangler's `env.<NAME>` blocks inherit top-level keys. `cf migrate` turns each Wrangler environment into a `case` of `switch (ctx.mode)`. A mode deploys a separate Worker only when it returns a different `name`.

### Resolution order

`resolveAndParseConfig(input, ctx)` in `@cloudflare/config` does this, in order:

1. Resolves the root `ConfigInput`.
2. Resolves every entry of `containers`.
3. Resolves `worker`.
4. Replaces an imported entrypoint module with its `default` export. A `cf-worker` import's default export is the module's absolute path (see below), so `entrypoint` ends up a string.
5. Drops `env` entries whose value is `false`, `null` or `undefined`.
6. For `worker`, `durable-object` and `workflow` bindings whose `worker` is a definition, resolves the definition and replaces it with its `name`.
7. For Durable Object exports with a `container`, resolves the definition and replaces it with its `name`. A string `container` is an error, and so is a definition missing from the `containers` array.
8. Parses the result with a strict zod schema. Unknown keys are errors.
9. Checks that Container names are unique, that at most one Durable Object links to each Container, and that the singleton binding types (`ai`, `assets`, `browser`, `analytics`, `images`, `media`, `stream`, `version-metadata`) appear at most once.

Each definition object resolves once per load, so a factory shared by two bindings runs once.

### The cf-worker import attribute

```ts
import * as entrypoint from "./src/index.ts" with { type: "cf-worker" };
```

The loader's hook never loads or runs the imported module. It synthesizes a module whose default export is the specifier, made absolute for relative paths. The import exists only so TypeScript sees the module's type, which drives inference of the main module's exports, Durable Object classes and RPC methods. Changes to the entrypoint don't count as config changes for reload.

A plain string such as `entrypoint: "src/index.ts"` also works. TypeScript still infers binding types, but not the module's export types.

## The default export

| Field | Type | Notes |
| --- | --- | --- |
| `accountId` | `string` | `CLOUDFLARE_ACCOUNT_ID` takes priority |
| `complianceRegion` | `"public" \| "fedramp-high"` | `CLOUDFLARE_COMPLIANCE_REGION` takes priority |
| `worker` | `ConfigInput<WorkerConfig>` | Required by dev and builds, optional for API commands |
| `containers` | `ConfigInput<ContainerConfig>[]` | Defaults to `[]` |

## Worker fields

| Field | Type | Wrangler key it becomes |
| --- | --- | --- |
| `name` | `string`, required | `name` |
| `compatibilityDate` | `string`, required | `compatibility_date` |
| `compatibilityFlags` | `string[]` | `compatibility_flags` |
| `entrypoint` | `string` or a `cf-worker` module | `main`. Optional for an assets-only Worker. |
| `assets` | `{ htmlHandling?, notFoundHandling?, basePath?, runWorkerFirst? }` | `assets.*` in snake_case. The directory is a build setting. |
| `domains` | `Array<string \| { hostname, production, previews }>` | `routes` entries with `custom_domain: true`. A string serves production only. |
| `triggers` | `Trigger[]` | `routes`, `triggers.crons`, `queues.consumers`, `addresses`, `connect` |
| `tailConsumers` | `Array<{ worker, streaming? }>` | Tail and streaming tail consumers in one list |
| `cache` | `{ enabled, crossVersionCache? }` | `cache` |
| `placement` | `{ mode: "off" \| "smart", hint? }`, or targeted by `region`, `host` or `hostname` | `placement` |
| `limits` | `{ cpuMs?, subrequests? }` | `limits.cpu_ms`, `limits.subrequests` |
| `logpush` | `boolean` | `logpush` |
| `observability` | `{ enabled?, headSamplingRate?, redactQueryString?, issues?, logs?, traces? }` | `observability.*` in snake_case |
| `access` | `{ dev?: { aud, identity? } }` | `access`. Local Cloudflare Access simulation. New since 0.25.0. |
| `workersDev` | `boolean`, default `true` | `workers_dev` |
| `previewUrls` | `boolean`, default `false` | `preview_urls` |
| `unsafe` | `{ metadata?, capnp? }` | `unsafe` |
| `env` | `Record<string, Binding \| false \| null \| undefined>` | One Wrangler section per binding kind, listed below |
| `exports` | `Record<string, Export>` | `exports` |
| `firstPartyWorker` | `boolean`, internal | `first_party_worker` |

## Bindings

Each key of `worker.env` is a binding name. The builder picks the kind. Every builder returns `{ type: "<kind>", ...options }`, and the loader reads nothing else. A hand-written object with the same keys behaves the same, which the [experiment](#experiment-a-python-worker-on-the-new-config-path) relies on.

Almost every resource binding takes `dev?: { remote?: boolean }`, which becomes Wrangler's `remote`. The table leaves it out.

| Builder | `type` | Options | Runtime type in `Env` | Wrangler section |
| --- | --- | --- | --- | --- |
| `text<T>(value)` | `text` | the string | `T`, the literal | `vars` |
| `json<T>(value)` | `json` | any JSON value | `T`, the literal shape | `vars` |
| `secret()` | `secret` | none | `string` | `secrets.required` |
| `kv<TKey>()` | `kv` | `id?` | `KVNamespace<TKey>` | `kv_namespaces` |
| `d1()` | `d1` | `id?`, `name?` | `D1Database` | `d1_databases` |
| `r2()` | `r2` | `name?`, `jurisdiction?`, `dev.experimentalS3Credentials?` | `R2Bucket` | `r2_buckets` |
| `queue<TBody>()` | `queue` | `name?`, `deliveryDelay?` | `Queue<TBody>` | `queues.producers` |
| `hyperdrive()` | `hyperdrive` | `id`, `dev.connectionString?` | `Hyperdrive` | `hyperdrive` |
| `analyticsEngineDataset()` | `analytics-engine-dataset` | `name?` | `AnalyticsEngineDataset` | `analytics_engine_datasets` |
| `analytics()` | `analytics` | none | `AnalyticsSQLBinding` | `analytics` (singleton) |
| `artifacts()` | `artifacts` | `namespace` | `Artifacts` | `artifacts` |
| `pipeline<TRecord>()` | `pipeline` | `name` | `Pipeline<TRecord>` | `pipelines` |
| `k2()` | `k2` | `stream` | `K2Producer` | `k2`. New since 0.25.0. |
| `ai<TModels>()` | `ai` | none | `Ai<TModels>` | `ai` (singleton) |
| `aiSearch()` | `ai-search` | `name` | `AiSearchInstance` | `ai_search` |
| `aiSearchNamespace()` | `ai-search-namespace` | `namespace` | `AiSearchNamespace` | `ai_search_namespaces` |
| `agentMemory()` | `agent-memory` | `namespace` | `AgentMemoryNamespace` | `agent_memory` |
| `browser()` | `browser` | none | `BrowserRun` | `browser` (singleton) |
| `images()` | `images` | none | `ImagesBinding` | `images` (singleton) |
| `media()` | `media` | none | `MediaBinding` | `media` (singleton) |
| `stream()` | `stream` | none | `StreamBinding` | `stream` (singleton) |
| `vectorize()` | `vectorize` | `name` | `VectorizeIndex` | `vectorize` |
| `sendEmail()` | `send-email` | one of `destinationAddress` or `allowedDestinationAddresses`, and `allowedSenderAddresses?` | `SendEmail` | `send_email` |
| `assets()` | `assets` | none | `Fetcher` | `assets.binding` (singleton) |
| `dispatchNamespace()` | `dispatch-namespace` | `namespace?`, `outbound?: { worker, parameters? }` | `DispatchNamespace` | `dispatch_namespaces` |
| `durableObject()` | `durable-object` | `worker`, `exportName` | `DurableObjectNamespace<Class>` | `durable_objects.bindings` |
| `worker()` | `worker` | `worker`, `exportName?`, `props?` | `Fetcher<Entrypoint>` | `services` |
| `workerLoader()` | `worker-loader` | none | `WorkerLoader` | `worker_loaders` |
| `workflow()` | `workflow` | `name`, `worker`, `exportName` | `Workflow<Payload>` | `workflows` |
| `mtlsCertificate()` | `mtls-certificate` | `id` | `Fetcher` | `mtls_certificates` |
| `rateLimit()` | `rate-limit` | `namespace`, `simple: { limit, period: 10 \| 60 }` | `RateLimit` | `ratelimits` |
| `secretsStoreSecret()` | `secrets-store-secret` | `storeId`, `secretName` | `SecretsStoreSecret` | `secrets_store_secrets` |
| `vpcNetwork()` | `vpc-network` | one of `tunnelId` or `networkId` | `Fetcher` | `vpc_networks` |
| `vpcService()` | `vpc-service` | `id` | `Fetcher` | `vpc_services` |
| `flagship()` | `flagship` | `id?` | `Flagship` | `flagship` |
| `logfwdr()` | `logfwdr` | `destination` | `any` | `logfwdr.bindings` |
| `versionMetadata()` | `version-metadata` | none | `WorkerVersionMetadata` | `version_metadata` (singleton) |
| no builder | `unsafe:<kind>` | anything, plus `dev.plugin` | `any` | `unsafe.bindings` |

Options without `?` are required. `kv`, `d1`, `r2` and `queue` can omit the resource ID, and `cf deploy` provisions the resource without writing the ID back to the config.

`worker`, `durableObject` and `workflow` accept either a Worker name or a Worker definition from another config file, imported with its `.ts` extension. With a definition, TypeScript rejects an `exportName` that the target doesn't export, and the runtime type carries the target class. With a name, the type falls back to `Fetcher`, `DurableObjectNamespace` or `Workflow`. The converted Wrangler config always sets `script_name`, even when a Durable Object binding names its own Worker.

## Triggers

Triggers decide which events invoke the Worker. They create no `env` bindings.

| Builder | Options | Wrangler key |
| --- | --- | --- |
| `fetch()` | `pattern`, `zone?` (a zone name if it contains a dot, otherwise a zone ID) | `routes` |
| `queue()` | `name`, `deadLetterQueue?`, `maxBatchSize?`, `maxBatchTimeout?`, `maxConcurrency?`, `maxRetries?`, `retryDelay?`, `visibilityTimeoutMs?` | `queues.consumers` |
| `scheduled()` | `schedule`, one cron string per trigger | `triggers.crons` |
| `email()` | `addresses`, literal addresses or `*@domain` | `addresses` |
| `connect()` | `protocol: "tcp" \| "udp"`, `port`, `address?`, and for UDP `idleTimeoutMs?`, `maxPendingBytes?` | `connect` |

## Exports

`worker.exports` maps each export name of the entrypoint to how the platform manages it. The builders don't create code exports. The entrypoint must still export every live class it names.

| Builder | Options | Purpose |
| --- | --- | --- |
| `exports.worker()` | `cache?: { enabled }` | A `WorkerEntrypoint`, or `default` |
| `exports.durableObject()` | `state?` plus the options for that state | A Durable Object class and its namespace lifecycle |
| `exports.workflow()` | `name`, `limits?: { steps? }`, `concurrency?: { limit? }`, `schedules?`, `defaultRetention?: { successRetention?, errorRetention? }` | A `WorkflowEntrypoint` class. Retention takes milliseconds or a string such as `"3 days"`. |

The map replaces Wrangler's ordered `migrations`. A config can't set both. The `state` field picks the options:

| `state` | Options | Meaning |
| --- | --- | --- |
| omitted or `created` | `storage: "sqlite"` with `container?`, or `storage: "legacy-kv"` | A live class |
| `deleted` | none | Retires the namespace. Every binding to it must be gone, and the code must not export the class. |
| `renamed` | `renamedTo` | The target must be a live entry in the same map |
| `expecting-transfer` | `transferFrom`, plus storage as for `created` | The first of two deploys that move a namespace between Workers in one account |
| `transferred` | `transferredTo` | The second of those deploys |

Tombstones stay until a deployment response reports them as stale. `ctx.exports` types the live and incoming classes, so a Worker can reach its own Durable Object without an `env` binding. Lifecycle changes apply at deployment, and the platform rejects a split deployment whose versions disagree about `exports`.

## Containers

`defineContainer()` defines a Container once. A Durable Object export references the definition with `container`, and the same definition goes in the top-level `containers` array.

Every Container has `name`, `ssh?: { enabled, port? }`, `authorizedKeys?` and a hidden `unsafe?`. There are two kinds:

- A standard Container has `image` (`{ dockerfile, buildContext?, buildVars? }` or `{ reference }`), `maxInstances?` (default 20), `instanceType?` (a named size from `lite` to `standard-4`, or `{ vcpu?, memoryMib?, diskMb? }`), `schedulingPolicy?: "default" | "regional"`, `constraints?: { regions?, jurisdiction? }`, `rollout?: { kind?, stepPercentage?, activeGracePeriod? }` and `observability?` with instance targeting.
- A Durable Object Container has `schedulingPolicy: "durable-object"`, named `images?` and application-wide `observability?`. It is new since 0.25.0.

## Type inference

### How TypeScript computes Env

`cf workers types`, and the Vite plugin on every dev run and build, write `.cloudflare/types/index.d.ts`. The `generateTypes()` function produces this text:

```ts
type __Config = import("cf/config").UnwrapConfig<typeof import("../../cloudflare.config").default>;
type __WorkerConfig = import("cf/config").UnwrapConfig<__Config["worker"]>;
type __Env = import("cf/config").InferEnv<__WorkerConfig>;

declare namespace Cloudflare {
	interface GlobalProps {
		mainModule: import("cf/config").InferMainModule<__WorkerConfig>;
		durableNamespaces: import("cf/config").InferDurableNamespaces<__WorkerConfig>;
	}
	interface Env extends __Env {}
}
interface Env extends Cloudflare.Env {}
```

The file holds no binding names. The type checker derives them from the config file every time it runs, so there is nothing to regenerate when a binding changes. These type-level functions do the work:

- `UnwrapConfig<T>` unwraps factories and promises, recursively.
- `InferEnv<T>` maps each `env` entry's `type` literal through `BindingTypeMap` to a runtime type. The parameterized builders (`text`, `json`, `kv`, `queue`, `pipeline` and `ai`) carry their type argument in a phantom `__typeParams` field, which the map reads back.
- `MergeEnv` makes a key optional when a factory's branches disagree, either because the key is missing from some branch or because some branch sets it to `false`, `null` or `undefined`. A key present and enabled in every branch is required.
- For `worker`, `durable-object` and `workflow` bindings whose `worker` is a definition, `InferBindingType` looks up `exportName` in that Worker's entrypoint module type. It gives `Fetcher<EntrypointInstance>` (typed RPC), `DurableObjectNamespace<DurableObjectInstance>`, or `Workflow<P>` where `P` is the payload type of the class's `run` method.
- `InferMainModule` and `InferDurableNamespaces` type `ctx.exports`. They leave out tombstoned Durable Objects.
- `unsafe:*` bindings are `any`.

### What inference catches

- A misspelled binding name on `env`.
- A wrong message type for `env.JOBS.send()`, from `bindings.queue<Job>()`.
- A JSON var read with the wrong shape, because `bindings.json({ search: true })` types as `{ search: true }`.
- An `exportName` that the referenced Worker doesn't export, or that names the wrong kind of export.
- An RPC method or argument that doesn't exist on the bound Worker's entrypoint.
- Options that don't fit a builder, such as `sendEmail` with both `destinationAddress` and `allowedDestinationAddresses`.

`bindings.secret()` also changes tooling. When a config declares secrets, type generation stops inferring them from `.dev.vars` or `.env`, and local dev warns about missing ones.

## How the config reaches the platform

`convertToWranglerConfig()` turns the parsed config into a Wrangler `RawConfig`. Both `cf` and `wrangler --experimental-new-config` use it, then run Wrangler's normal validation. In Wrangler 4.151.3 the flow is:

1. Load `cloudflare.config.ts` from the working directory and parse it with `{ mode: --env ?? CLOUDFLARE_ENV, isPreview }`.
2. Load `wrangler.config.ts` if it exists. It may also be a factory.
3. Convert both and merge them, with tooling keys over Worker keys and the two `assets` objects merged.
4. Validate with `normalizeAndValidateConfig`, as for any `wrangler.jsonc`.

Builds through `cf` write Build Output to `.cloudflare/output/v0/`, which `cf deploy --prebuilt` uploads. Its root `config.json` records `accountId`, `complianceRegion` and `buildContext: { isPreview, mode }`. Each Worker's `worker.config.json` has a module manifest whose module types include `python` and `python-requirement`. Cloudflare documents the format only in the `@cloudflare/config` schema.

### Versions

| Package | `@cloudflare/config` it carries |
| --- | --- |
| Docs explorer | 0.25.0 |
| `cf` 1.0.0-beta.20 | 0.27.0 |
| `wrangler` 4.151.3 | 0.27.0 |
| `wrangler` 4.129.0, Wynd's pin | 0.10.0 |

Between 0.25.0 and 0.27.0, `access`, object-form `domains`, `k2`, `analytics`, `unsafe:*` bindings and Durable Object Containers appeared. A Python config tracks one of these versions, and the Wrangler pin has to carry the same one.

## Experiment: a Python Worker on the new-config path

A directory held `src/main.py` (a `Default` `WorkerEntrypoint` and a `Counter` Durable Object), `package.json` with `"type": "module"`, and a `cloudflare.config.ts` that imports nothing:

```ts
export default {
  worker: {
    name: "py-new-config",
    compatibilityDate: "2026-09-08",
    compatibilityFlags: ["python_workers"],
    entrypoint: "src/main.py",
    env: {
      GREETING: { type: "text", value: "hi" },
      FLAGS: { type: "json", value: { beta: true } },
      CACHE: { type: "kv", id: "0123456789abcdef0123456789abcdef" },
      API_KEY: { type: "secret" },
      COUNTER: { type: "durable-object", worker: "py-new-config", exportName: "Counter" },
    },
    exports: { Counter: { type: "durable-object", storage: "sqlite" } },
    triggers: [{ type: "scheduled", schedule: "0 * * * *" }],
  },
};
```

`npx wrangler@4.151.3 deploy --dry-run --experimental-new-config --outdir out` on Node 24.13.0 listed the `COUNTER`, `CACHE`, `GREETING` and `FLAGS` bindings and wrote `out/main.py`. So:

- Plain objects work without `cf/config` installed, because Wrangler bundles the loader.
- A `.py` entrypoint goes through the existing Python upload path.
- `exports` works in place of `migrations` for a Python Durable Object.

The run didn't cover `python_modules/`, `wrangler dev`, or a deploy with real credentials. Wynd doesn't use this path, because it converts the config itself (see [Decided](#decided)).

## Requirements for cloudflare.config.py

Parity with `cloudflare.config.ts` means a Python config can do each of these:

1. Declare the three sections: account settings, one Worker and Containers.
2. Set every Worker field in [Worker fields](#worker-fields).
3. Declare every binding kind in [Bindings](#bindings) with its options, including `dev` options and `unsafe:*` bindings.
4. Declare every trigger and export, including all five Durable Object states.
5. Define a Container once and reference it from both a Durable Object export and `containers`.
6. Give a value, an awaitable or a factory of the context at the root, Worker and Container levels.
7. Return a different configuration for each mode and for previews, with no merging.
8. Omit a binding by setting it to `None` or `False`, so a binding can be conditional.
9. Reference another Worker's definition from a binding, so Wynd checks the name and export.
10. Get a typed `Env` from the config, with no step that can drift: KV, D1, R2, queue message types, JSON shapes, Durable Object classes, Workflow payloads and service RPC methods.
11. Report every validation error that the TypeScript loader reports.
12. Fail API commands only on errors in the account settings, if Wynd ever forwards them.

## Python constraints

- Python's type system has no mapped or conditional types. Nothing like `InferEnv<typeof config>` can turn a dict of builder results into a `Protocol`. The type has to come from something the checker already understands, such as a class body.
- TypeScript's type arguments, as in `bindings.queue<Job>()`, vanish at runtime. Python has no syntax to pass a type argument to a function call. A Python builder takes the type as a value (`queue(Job)`), or the builder is a generic class that the user subscripts (`DurableObject["Counter"](...)`).
- The host can't import Worker code. An entrypoint imports `js`, `pyodide` and the SDK's runtime-only modules, so nothing can stand in for `cf-worker`. `entrypoint` is a path string, and the config names classes such as `Counter` in strings that only type checkers resolve.
- The config imports `Env` from the source directory, so that module runs on the host. It can import `workers.bindings` and the builders, but anything runtime-only, such as `js` or the Worker's own classes, has to stay under `TYPE_CHECKING`.
- Text values widen. `text("https://api.example.com")` types as `str` in both checkers, where TypeScript keeps the literal. JSON values type as their inferred Python type, so `json({"search": True})` gives `dict[str, bool]`.
- The checker can't validate one Worker's `export_name` against another Worker's `exports` keys, because Python can't derive a `Literal` from a dict's keys. Wynd has to check it while evaluating the config.

## Typing env in Python

### The descriptor approach

Each builder returns a `Spec[R]`, a descriptor whose `__get__` returns `R` when read on an instance. The env is a class of these specs. A handler annotated `env: Env` reads `env.DATABASE` as `D1Database`, while `Env.DATABASE` is still the spec Wynd serializes.

```python
class Spec[R]:
    def __init__(self, type: str, **options: Any) -> None:
        self.type, self.options = type, options

    @overload
    def __get__(self, instance: None, owner: type) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type) -> R: ...
    def __get__(self, instance: object | None, owner: type) -> Self | R:
        raise AttributeError


def d1(*, name: str | None = None) -> Spec[D1Database]: ...
def kv(*, id: str | None = None) -> Spec[KVNamespace]: ...
def queue[T](body: type[T], *, name: str | None = None) -> Spec[Queue[T]]: ...
def text[T: str](value: T) -> Spec[T]: ...
def json[T](value: T) -> Spec[T]: ...


class DurableObject[T](Spec[DurableObjectNamespace[T]]):
    def __init__(self, *, export_name: str, worker: str | None = None) -> None: ...
```

```python
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from worker import Counter


class Job(TypedDict):
    id: str


class Env:
    API_ORIGIN = text("https://api.example.com")
    FEATURES = json({"search": True})
    DATABASE = d1(name="db")
    JOBS = queue(Job, name="jobs")
    CACHE = kv() if staging else None
    COUNTER = DurableObject["Counter"](export_name="Counter")
```

Pyright (latest, strict) and mypy (`--strict`, Python 3.12) gave the same results:

| Expression | Inferred type |
| --- | --- |
| `env.API_ORIGIN` | `str` |
| `env.FEATURES` | `dict[str, bool]` |
| `env.DATABASE` | `D1Database` |
| `env.JOBS` | `Queue[Job]` |
| `env.CACHE` | `KVNamespace \| None` |
| `env.COUNTER` | `DurableObjectNamespace[Counter]` |
| `Env.DATABASE` | `Spec[D1Database]` |

Both checkers reported `env.JOBS.send({"id": 1})` as a wrong TypedDict value, `env.DATABSE` as a missing attribute (mypy suggested `DATABASE`), and `env.COUNTER.get_by_name("x").increment("two")` as a wrong argument type.

`DurableObject["Counter"]` with `Counter` imported only under `TYPE_CHECKING` runs on CPython 3.12. The subscript makes a generic alias around a forward reference, and calling it builds the spec without importing `worker`. The same form fits a typed service binding, `Service["Admin"](worker="api-worker")`, and a typed Workflow, `Workflow["OrderWorkflow"](...)`.

A conditional binding (`kv() if staging else None`) types as `KVNamespace | None`. That is close to TypeScript's optional key, because the checker forces a `None` check. At runtime the env wrapper has to return `None` for a binding the deployed mode doesn't define, not raise `AttributeError`.

### Where Env lives

`Env` is in a module under the source directory, such as `src/env.py`. Wynd puts the source directory on `sys.path` before it loads `cloudflare.config.py`, and the config imports `Env` from there.

Mode-dependent bindings then need the mode while the class body runs. One way is a context that Wynd sets before it loads the config. The env module reads it with a call such as `config_context()`. On the Worker runtime the class body runs again if `main.py` imports `env` outside `TYPE_CHECKING`, with the context's defaults and no Wynd. The builders must be cheap and side-effect free for that reason, or Worker code must import `Env` under `TYPE_CHECKING` only.

### The codegen alternative

Wynd could keep `wynd types` and generate `src/env.py` from the evaluated config, as it does from `wrangler.jsonc` today. The builders would still carry types as values (`queue(Job)`, `DurableObject["Counter"]`) so the generator can print them. This keeps the existing typegen design, but it brings back the drift `--check` exists to catch. It also types only the mode Wynd evaluated, where TypeScript types every branch at once. And `Job` must still live in an importable module, because the generated file imports it.

## Converting to wrangler.json

Wynd evaluates `cloudflare.config.py` and writes the result as the staged `wrangler.json`, the file it already hands to Wrangler. The builders return Python objects with snake_case fields. Nothing has to match the camelCase shape of the TypeScript builders, because no TypeScript reads them.

Wynd then does what `@cloudflare/config` does, in Python:

- Resolves values, awaitables and factories of the context at the root, Worker and Container levels.
- Drops bindings set to `None` or `False`.
- Replaces Worker and Container references with their names.
- Runs the checks in [Resolution order](#resolution-order): unknown or missing fields, unique Container names, one Durable Object per Container, and the singleton binding types.
- Checks that a referenced Worker's `exports` includes each `export_name`. Python's type checkers can't catch that.
- Maps every field to its Wrangler key, as in the tables above. Domains become custom-domain routes, `exports` replaces `migrations`, and Durable Object bindings always get `script_name`.

The cost is keeping this port in step with `@cloudflare/config` releases. To test the port, Wynd can run `convertToWranglerConfig` from the npm package on a TypeScript config with the same contents and compare the JSON with its own output. That test needs Node.js and the package only in Wynd's own test suite.

I read each release's `cli.js` and compared the top-level keys that `normalizeAndValidateEnvironment` validates in Wrangler 4.129.0 and 4.151.3. Of the keys the conversion can produce, 4.129.0 lacks only `k2` and `analytics`, which arrived in later releases. A Python config that uses either needs a newer pin. 4.129.0 already validates `exports`, `secrets`, `cache`, `access`, `artifacts`, `flagship`, `agent_memory`, `ai_search`, `ai_search_namespaces`, `vpc_networks`, `vpc_services` and `worker_loaders`. No 4.129.0 dry run used these keys.

### Dev config in .wynd

I tested this layout with Wrangler 4.129.0 on Node 24.13.0, with crosswind-workers copied into `python_modules/`. The test linked `python_modules/` from the project root. With `wynd sync` installing straight into `.wynd/dev/python_modules/`, the link isn't needed.

```
proj/
  src/main.py
  python_modules/
  .wynd/dev/
    wrangler.json        "main": "/abs/path/proj/src/main.py"
    python_modules -> ../../python_modules
```

- `deploy --dry-run -c .wynd/dev/wrangler.json` uploaded the files under the linked `python_modules/`.
- `dev -c .wynd/dev/wrangler.json` served a response from a module in `python_modules/`.
- An edit to `src/main.py` reloaded the Worker.
- Adding a var to `.wynd/dev/wrangler.json` reloaded the Worker with the new binding.
- An edit inside `python_modules/` didn't reload within 30 seconds. With the config in the project root and no link, it didn't either, so the link isn't the cause.

## Code structure

Wynd reads each config format with its own parser. Each parser returns the same `Config`, so the rest of Wynd doesn't know which file the project uses.

```python
@dataclass(frozen=True)
class Config:
    path: Path
    main: str | None
    base_dir: str | None
    compatibility_date: str | None
    compatibility_flags: tuple[str, ...]
    # The dictionary stage.py rewrites and writes as .wynd/<dir>/wrangler.json.
    wrangler: dict[str, Any]
    # What Wynd passes to Wrangler as --env. None for a Python config, which
    # applied the mode itself and stages no env blocks.
    wrangler_env: str | None


class ConfigParser(ABC):
    @property
    @abstractmethod
    def filenames(self) -> tuple[str, ...]: ...

    @abstractmethod
    def parse(self, path: Path, env: str | None) -> Config: ...


class PythonConfigParser(ConfigParser):
    filenames = ("cloudflare.config.py",)


class WranglerConfigParser(ConfigParser):
    # Shared by JSON and TOML: env selection and the INHERITED keys.
    @abstractmethod
    def load(self, text: str) -> dict[str, Any]: ...


class JSONConfigParser(WranglerConfigParser):
    filenames = ("wrangler.jsonc", "wrangler.json")  # jsonc parses both


class TOMLConfigParser(WranglerConfigParser):
    filenames = ("wrangler.toml",)


PARSERS = (PythonConfigParser(), JSONConfigParser(), TOMLConfigParser())
```

`parse` takes the environment as well as the path. A Python config needs the mode while it evaluates its factories. A Wrangler config needs it to pick the `env` table that `main` and the compatibility settings come from.

`WranglerConfigParser` is between the base class and the JSON and TOML parsers, which departs from the flat hierarchy of the first sketch. The two formats differ only in how they turn text into a dictionary. After that they share `_environment` and `INHERITED` from today's `project.py`.

One function over `PARSERS` finds the config. It walks up from the working directory and stops at the first directory that holds any of the parsers' file names. More than one file there is an error. `-c` skips the walk, and the file name picks the parser.

`Project` keeps the `pyproject.toml` settings and the paths, and gains a `config: Config` field. `main`, `base_dir`, the compatibility settings and today's `config` and `settings` dictionaries move onto `Config`. These callers change:

| File | Reads today | Reads after |
| --- | --- | --- |
| `targets.py`, `host.py`, `sync.py` | `project.compatibility_date`, `project.compatibility_flags` | `project.config.compatibility_date`, `project.config.compatibility_flags` |
| `stage.py` | `project.config`, `project.main` | `project.config.wrangler`, `project.config.main` |
| `typegen.py` | `project.settings`, `project.main` | `WranglerConfig.settings`, `project.config.main` |
| `cli.py` | Forwards `-e` unchanged | Forwards `project.config.wrangler_env` |
| `scaffold.py` | `CONFIG_NAMES` | The file names of every parser in `PARSERS` |

`typegen.py` is the one caller that needs the env-selected table, not the full config, and it only runs for Wrangler configs. So `WranglerConfigParser.parse` returns a `WranglerConfig`, a `Config` subclass with a `settings` field, and `typegen.py` accepts only that.

## Effects on current Wynd decisions

These parts of [decisions.md](decisions.md) and the code would change:

- `project.py` splits into the parsers in [Code structure](#code-structure). Today it has `CONFIG_NAMES = ("wrangler.json", "wrangler.jsonc", "wrangler.toml")` and walks up from the working directory once per name, so a `wrangler.json` in a parent beats a `wrangler.toml` in the project. Under the new rule, `cloudflare.config.py` joins the list. The walk stops at the first directory that holds any of the four, and two or more in that directory are an error. Today Wynd silently picks `wrangler.json` over a `wrangler.toml` beside it, and that becomes an error too.
- `-c` can name a `cloudflare.config.py`. `-e` becomes the mode in the config's context. Wynd can't forward `--env` to Wrangler for a Python config, because the staged `wrangler.json` has no `env` blocks.
- `stage.py` keeps its shape. It rewrites path keys in the converted dictionary. They resolve from the directory of `cloudflare.config.py`, as they do from the Wrangler config's directory today.
- Every command Wynd hands to Wrangler gets `-c` pointing at a converted `wrangler.json` in `.wynd/`. That includes commands passed straight through, such as `wynd d1 migrations apply` or `wynd tail`, which today let Wrangler find the config itself. Nothing staged lands in the user's tree.
- `wynd dev` would run `wrangler dev -c .wynd/dev/wrangler.json`. Wrangler 4.129.0 sets the project root to the config's directory and collects `python_modules/` from there. So `wynd sync` installs into `.wynd/dev/python_modules/` instead of the project's `python_modules/`. Only the `Project.python_modules` property changes, because every caller gets the path from it. See [Dev config in .wynd](#dev-config-in-wynd). Wrangler doesn't watch `cloudflare.config.py`, so Wynd watches it and rewrites the dev config.
- `typegen.py` generates `src/env.py` from a Wrangler config. A Python config already declares `Env`, so `wynd types` has nothing to generate for it.
- The Wrangler pin and the Node.js requirement stay as they are, unless a config uses `k2` or `analytics`.
- `wynd init` writes `wrangler.json`. It could write `cloudflare.config.py` and `src/env.py` instead.
- `crosswind-workers` would ship the builders, since `src/env.py` imports them and Worker code imports `Env`. The shaker keeps the builder module only when something imports it at runtime.

## Open questions

- Which module ships the builders: `crosswind-workers` (`workers.config`), Wynd, or a third package? Worker code needs the spec types, and users run Wynd through `uvx`, so it isn't installed in the project.
- How does the env class get the mode? Options are a context Wynd sets before import, a factory that builds the class, or one class per mode.
- Which `@cloudflare/config` version does the port track? 0.27.0 matches the latest Wrangler, but `k2` and `analytics` from 0.27.0 need a newer pin than 4.129.0.
- Does `wynd types` stay for Wrangler configs once Python configs exist?
- Should Wynd forward `cf` API commands at all, given `cf` reads account settings only from `cloudflare.config.ts`?
- Does the stock SDK get any `Env` support, given it has no `workers.bindings`?
