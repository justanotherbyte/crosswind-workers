# `cloudflare.config.ts`

Researched 2026-10-22 for context on a Python equivalent. The sources are Cloudflare's docs pages, fetched over the web because no Cloudflare MCP server was connected:

- Programmatic configuration: https://developers.cloudflare.com/cf/projects/cloudflare-config/
- Config explorer (field reference, generated from `@cloudflare/config` 0.27.0, updated 2026-09-29): https://developers.cloudflare.com/cf/projects/config-explorer/
- Projects overview: https://developers.cloudflare.com/cf/projects/
- cf for Wrangler users: https://developers.cloudflare.com/cf/wrangler/

The format is in open beta and may change before the stable release.

## 1. What it is

`cloudflare.config.ts` is the project config file for the `cf` CLI. Its default export describes one Worker, its Container applications and the account defaults. It replaces `wrangler.json`/`wrangler.jsonc`/`wrangler.toml` for `cf` project commands.

Requirements:

- Node.js 22.18 or later. Bun is not supported.
- `"type": "module"` in `package.json`.
- The `cf` package as a dev dependency. `cf init` adds it.

The docs disagree on the package name. The programmatic configuration page imports from `cf/config`. The config explorer says its reference comes from `@cloudflare/config` 0.27.0. `cf/config` is probably a re-export, but the docs don't say so.

## 2. Minimal config

```ts
import { defineConfig } from "cf/config";
import * as entrypoint from "./src/index.ts" with { type: "cf-worker" };

export default defineConfig({
  worker: {
    name: "example-worker",
    entrypoint,
    compatibilityDate: "<COMPATIBILITY_DATE>",
  },
});
```

- `name` and `compatibilityDate` are required.
- `entrypoint` is required for a Worker that runs code. It is a path string or a module imported with the `cf-worker` import attribute. An assets-only Worker omits it.

## 3. Dynamic config and modes

`defineConfig`, `defineWorker` and `defineContainer` each accept an object, a promise of one, or a function. The function receives a context of `{ mode: string | undefined, isPreview: boolean }`.

```ts
export default defineConfig(({ mode }) => {
  const isStaging = mode === "staging";
  return {
    worker: {
      name: isStaging ? "example-staging" : "example-worker",
      env: { MESSAGE: bindings.text(isStaging ? "staging" : "production") },
      triggers: [triggers.scheduled({ schedule: "0 * * * *" })],
      // ...
    },
  };
});
```

- `--mode <NAME>` or `-m <NAME>` sets `mode`.
- Each mode produces one complete config. There are no Wrangler-style environment blocks, and `cf` merges nothing.
- The default mode depends on the command. It is `development` for `cf dev` with the Vite plugin, `production` for Vite builds and deploys, and `undefined` for Wrangler builds and API commands.
- The build output records the mode in its root `config.json`, so `cf deploy --prebuilt` must get the same mode.
- When `cf` runs a framework's own command, only Vite and Astro accept `--mode`. Other frameworks stop with an error.

## 4. Top-level fields (`defineConfig`)

| Field | Type | Notes |
|---|---|---|
| `accountId` | `string?` | `CLOUDFLARE_ACCOUNT_ID` overrides it |
| `complianceRegion` | `"public" \| "fedramp-high"`? | `CLOUDFLARE_COMPLIANCE_REGION` overrides it |
| `worker` | `ConfigInput<WorkerConfig>?` | Required for dev and builds |
| `containers` | `ConfigInput<ContainerConfig>[]?` | Defaults to `[]` |

`ConfigInput<T>` is the object, promise or function form from section 3.

## 5. `WorkerConfig` fields

| Field | Type / values | Default |
|---|---|---|
| `name` | `string`, required | |
| `compatibilityDate` | `string` (`yyyy-mm-dd`), required | |
| `entrypoint` | `string \| WorkerModule` | |
| `compatibilityFlags` | `string[]` | `[]` |
| `assets` | `htmlHandling`, `notFoundHandling`, `basePath`, `runWorkerFirst` | |
| `domains` | `Array<string \| CustomDomain>` | |
| `triggers` | `Trigger[]` | |
| `tailConsumers` | `Array<{ worker: string; streaming?: boolean }>` | `[]` |
| `cache` | `{ enabled: boolean; crossVersionCache?: boolean }` | |
| `placement` | `{ mode: "off" \| "smart"; hint? }`, or targeted by `region`, `host` or `hostname` | |
| `limits` | `{ cpuMs?: number; subrequests?: number }` | |
| `logpush` | `boolean` | |
| `observability` | `enabled`, `headSamplingRate`, `redactQueryString`, `issues`, `logs`, `traces` | |
| `access` | `{ dev?: { aud: string; identity?: Record<string, unknown> } }` | |
| `workersDev` | `boolean` | `true` |
| `previewUrls` | `boolean` | `false` |
| `unsafe` | `{ metadata?; capnp? }` | `{}` |
| `env` | `Record<string, Binding \| false \| null \| undefined>` | |
| `exports` | `Record<string, Export>` | |

Assets values:

- `htmlHandling` is `auto-trailing-slash`, `drop-trailing-slash`, `force-trailing-slash` or `none`.
- `notFoundHandling` is `single-page-application`, `404-page` or `none`.
- `runWorkerFirst` is `string[] | boolean`.
- There is no `assets.directory`. Vite projects use Vite's client build output. Wrangler-bundled projects set the directory in a generated `wrangler.config.ts`.

Observability has `logs` and `traces` sub-objects. Each has `enabled`, `headSamplingRate`, `persist` (default `true`) and `destinations` (default `[]`). `logs` also has `invocationLogs`.

## 6. Bindings (`worker.env`)

`cf` builds each binding with a builder from `bindings`:

```ts
env: {
  API_ORIGIN: bindings.text("https://api.example.com"),
  FEATURES: bindings.json({ search: true }),
  DATABASE: bindings.d1({ name: "application-db" }),
  JOBS: bindings.queue<Job>({ name: "application-jobs" }),
  API_KEY: bindings.secret(),
},
```

- `cf` drops entries set to `false`, `null` or `undefined`, so `FLAG && bindings.kv()` gives a conditional binding.
- Every builder that takes options also takes `dev?: BindingDevOptions`.
- `cf workers types` or the Vite plugin generates binding types into `.cloudflare/types`. Add that directory to `tsconfig.json` `include`. Projects with `.ts` imports also need `allowImportingTsExtensions`.

The builders and their options:

- Values: `text(value)`, `json(value)`, `secret()`, `secretsStoreSecret({ storeId, secretName })`.
- Storage: `d1({ id?, name? })`, `kv({ id? })`, `r2({ name?, jurisdiction? })`, `hyperdrive({ id })`, `vectorize({ name })`.
- Messaging: `queue({ name?, deliveryDelay? })`, `pipeline({ name })`, `sendEmail({ destinationAddress | allowedDestinationAddresses, allowedSenderAddresses? })`, `k2({ stream })`, `logfwdr({ destination })`.
- Workers: `worker({ worker, exportName?, props? })`, `durableObject({ worker, exportName })`, `workflow({ name, worker, exportName })`, `dispatchNamespace({ namespace?, outbound? })`, `workerLoader()`, `versionMetadata()`, `assets()`.
- AI: `ai()`, `aiSearch({ name })`, `aiSearchNamespace({ namespace })`, `agentMemory({ namespace })`.
- Media: `browser()`, `images()`, `media()`, `stream()`.
- Other: `analytics()`, `analyticsEngineDataset({ name? })`, `artifacts({ namespace })`, `flagship({ id? })`, `mtlsCertificate({ id })`, `rateLimit({ namespace, simple: { limit, period: 10 | 60 } })`, `vpcNetwork({ tunnelId | networkId })`, `vpcService({ id })`.

`d1`, `kv`, `r2` and `queue` take optional IDs and names. The docs don't say how `cf` resolves or creates a missing resource.

## 7. Cross-Worker references

One Worker can export its definition so that another config can import it. The importing config then gets compile-time checks on export names.

```ts
// api/cloudflare.config.ts
export const apiWorker = defineWorker({ /* ... */ });
export default defineConfig({ worker: apiWorker });

// web/cloudflare.config.ts
import { apiWorker } from "../api/cloudflare.config.ts";
// env:
COUNTERS: bindings.durableObject({ worker: apiWorker, exportName: "Counter" }),
```

Imports need the `.ts` extension because Node.js doesn't add one.

## 8. Triggers (`worker.triggers`)

Triggers decide which events invoke the Worker. They don't create `env` bindings.

- `fetch({ pattern, zone? })` adds a route. Custom domains go in `domains`.
- `queue({ name, deadLetterQueue?, maxBatchSize?, maxBatchTimeout?, maxConcurrency?, maxRetries?, retryDelay?, visibilityTimeoutMs? })` adds a queue consumer.
- `scheduled({ schedule })` takes a cron string.
- `email({ addresses })`.
- `connect({ protocol: "tcp" | "udp", port, address?, idleTimeoutMs?, maxPendingBytes? })`. `address` defaults to `127.0.0.1`.

## 9. Exports (`worker.exports`)

`exports` maps each exported class name to its config. Live exports appear on `ctx.exports`, separate from `env`.

```ts
exports: {
  default: exports.worker({ cache: { enabled: false } }),
  Counter: exports.durableObject({ storage: "sqlite" }),
  OrderWorkflow: exports.workflow({ name: "order-workflow", limits: { steps: 100 } }),
},
```

- `exports.worker({ cache? })` declares a `WorkerEntrypoint`.
- `exports.workflow({ name, limits?: { steps? }, concurrency?: { limit? }, schedules?, defaultRetention? })`.
- `exports.durableObject(...)` takes a `state`. This field replaces Wrangler's `migrations` list:
  - `created` is a live class with `storage: "sqlite" | "legacy-kv"` and an optional `container`. New classes should use `sqlite`.
  - `deleted` retires a removed class.
  - `renamed` takes `renamedTo`.
  - `expecting-transfer` takes `transferFrom`, `storage` and an optional `container`. The destination Worker deploys this first.
  - `transferred` takes `transferredTo`. The source Worker deploys this second, and that deploy commits the transfer. Both Workers must be in the same account.
- Lifecycle changes apply on deploy, not on upload. A version that changes `exports` must go to 100% of traffic before any split, because the platform rejects split deployments whose versions disagree about `exports`.

## 10. Containers

- `defineContainer` declares a container with a name, an image source such as `image: { dockerfile: "./Dockerfile" }`, an instance type and a maximum instance count.
- A container goes in the top-level `containers` array, and a `sqlite` Durable Object export attaches to it with its `container` option.
- Container names must be unique. Each container links to one Durable Object export.
- `cf deploy` applies Container changes. `cf workers versions create` builds images but doesn't apply them.

## 11. Who reads the file

- `cf` finds the nearest `cloudflare.config.ts` by walking from the cwd up to `/`.
- Project commands (`cf dev`, `cf build`, `cf deploy`, `cf workers versions create`, `cf workers triggers deploy`, `cf workers check`, `cf previews deploy`, `cf workers types`) load the whole file through a build tool. The build tool is the framework's own command, the Cloudflare Vite plugin, or Wrangler 4.136.0 or later.
- API commands such as `cf d1 list` read only `accountId` and `complianceRegion`. They skip the `worker` and `containers` factories and don't validate Worker fields. A syntax, import or top-level runtime error in the file still breaks them.
- Builds write to `.cloudflare/output/v0/`.
- `cf` never reads `wrangler.json`, `wrangler.jsonc` or `wrangler.toml`. A plain Worker project without `cloudflare.config.ts` fails with an error, and `cf migrate` converts it. In a framework project, `cf` writes a new `cloudflare.config.ts` and ignores the Wrangler file's entrypoint and bindings.
- The "cf for Wrangler users" page says "Wrangler does not read `cloudflare.config.ts`" and tells users to keep `wrangler dev` and `wrangler deploy` until they migrate. That conflicts with the projects page, which lists Wrangler 4.136.0+ as a build tool for the file. Section 12 has the likely explanation.

## 12. `wrangler.config.ts`

- `cf migrate` writes this file when the project bundles with Wrangler. It also writes it for a static-assets project with an `index.html`.
- It holds Wrangler build settings that `cloudflare.config.ts` lacks, such as `rules`, `tsconfig`, `no_bundle` and the assets directory, and `cf migrate` adds `types: { generate: false }`.
- The docs call it experimental.
- The page that says Wrangler doesn't read `cloudflare.config.ts` probably refers to plain `wrangler` commands. Wrangler 4.136.0+ loading the file as `cf`'s bundler would be a separate code path. This is unconfirmed.
- A `cf` error message mentions `--experimental-new-config`: "cloudflare.config.ts is required when --experimental-new-config is enabled". The docs don't describe the flag.

## 13. Notes for a Python config

- The config model has four parts: one Worker, a list of containers, account defaults and a mode function. Bindings, triggers and exports are tagged values built by helper functions.
- Conditional bindings work because `cf` drops falsy `env` entries. A Python version could drop `None` and `False` the same way.
- Durable Object migrations become per-class `state` values. There is no ordered `migrations` list with tags.
- The docs don't document how `cf` converts a config to Wrangler's JSON shape. Reading the `@cloudflare/config` 0.27.0 source would answer that.
- The reverted commit `2011e29` added `.design/CLOUDFLARE_CONFIG.md`, a 561-line earlier pass at this research, and `git show 2011e29:.design/CLOUDFLARE_CONFIG.md` recovers it.
