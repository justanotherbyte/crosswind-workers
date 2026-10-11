# First Wrangler release supporting compatibility date 2026-09-08

Researched 2026-10-11. Ticket from `.design/wynd.md`.

## Answer

**wrangler 4.129.0** is the first release whose bundled workerd accepts `compatibility_date = "2026-09-08"`.

| | |
|---|---|
| wrangler | 4.129.0, published 2026-09-03T17:50:56Z |
| workerd | 1.20260903.1 (exact pin, also pinned by miniflare 5.20260903.0-alpha) |
| Newest date it accepts | 2026-09-10 |
| Latest wrangler today | 4.149.0, published 2026-10-08, workerd 1.20261006.1 |

Pin `wrangler@>=4.129.0`. Any current release works.

## Evidence

Source for versions and dates: the npm registry documents at `https://registry.npmjs.org/wrangler`, `/miniflare` and `/workerd` (`versions[v].dependencies` and `time[v]`). Wrangler pins an exact workerd version, and its miniflare dependency pins the same one.

| wrangler | published | workerd | newest accepted date |
|---|---|---|---|
| 4.127.1 | 2026-08-28 | 1.20260828.1 | 2026-09-04 |
| 4.128.0 | 2026-09-01 | 1.20260831.1 | 2026-09-07 |
| 4.129.0 | 2026-09-03 | 1.20260903.1 | 2026-09-10 |

No other wrangler versions were published between 4.128.0 and 4.129.0.

I measured the "newest accepted date" column by running each `@cloudflare/workerd-linux-64` binary from npm. Each run used `workerd serve` with a one-module config, and I varied `compatibilityDate` over 2026-09-04, 05, 08, 10 and 11. A rejected date fails with the error the ticket quotes, for example under 1.20260831.1:

```
This Worker requires compatibility date "2026-09-08", but the newest date supported by this server binary is "2026-09-07".
```

1.20260903.1 started for every date up to 2026-09-10 and rejected 2026-09-11.

In all three binaries, the newest accepted date is the workerd version date plus 7 days. A rule of thumb based on the version date alone would be wrong by a week. By that rule 4.130.0 (workerd 1.20260908.1) would be first, but 4.129.0 already works.

## Confidence

High. The dependency mapping comes from the registry, and I tested the dates against the real binaries. Limits:

- I tested only the linux-x64 binary. Other platforms build from the same source and date constant, so they should match.
- I did not run wrangler itself (`wrangler dev`). Wrangler also checks the date against its own bundled workerd, so its result should be the same.
