# EcoSeek remote smoke test (Phase 3, issue #22)

> **Status: scaffold.** This document and the accompanying
> `scripts/remote-smoke.sh` are a *deliberate scaffold* — they verify
> everything we can verify today (broker reachability, edge health,
> token-safe request construction, graceful-degradation behavior),
> but the load-bearing Phase 3 capabilities live behind
> [agenticplug#83](https://github.com/alrobles/agenticplug/issues/83)
> and that PR is **not yet merged**. Until it lands, this smoke is
> expected to report `waiting for AgenticPlug #83` and exit 0 in the
> default (non-strict) mode.
>
> Tracking issue: [ecoseek#22](https://github.com/alrobles/ecoseek/issues/22).
> Contract reference:
> [`kuhpc-connector-contract.md`](https://github.com/alrobles/agenticplug/blob/main/docs/kuhpc-connector-contract.md)
> on AgenticPlug.

---

## Why a separate smoke?

`scripts/smoke.sh` proves the **local DIY** path end-to-end (issue #15):
laptop → AgenticPlug → local Ollama. It uses only public models, no
secrets, and `127.0.0.1` everywhere. That is the right bar for a public
alpha.

The Phase 3 product also has two **remote** paths that the DIY smoke
does *not* exercise:

1. **reumanlab remote connector** — a persistent Node.js service on
   the `reumanlab` workstation, exposed via Cloudflare. EcoSeek talks
   to it through AgenticPlug (HTTPS, OAuth). See
   [`reumanlab-connector-deploy.md`](./reumanlab-connector-deploy.md).
2. **KU-HPC production** — bounded read-only commands that the
   reumanlab connector relays to KU-HPC over SSH. EcoSeek itself
   never SSHes anywhere; that key lives only on reumanlab.

`scripts/remote-smoke.sh` is the operator-side verifier for those two
paths.

## What the three deployment modes prove

| Mode | Script | Talks to | Requires |
|------|--------|----------|----------|
| **Local DIY** | `scripts/smoke.sh` | `127.0.0.1` only | Docker, a local Ollama model |
| **reumanlab remote** | `scripts/remote-smoke.sh` | local broker → reumanlab edge | AgenticPlug session, network egress |
| **KU-HPC production** | `scripts/remote-smoke.sh` | local broker → reumanlab → KU-HPC | Above, plus reumanlab connector wired to KU-HPC |

`remote-smoke.sh` covers the second and third modes from the EcoSeek
client side. The connector side has its own tests (see
[`test/reumanlab-connector.test.js`](../test/reumanlab-connector.test.js)).

## What the scaffold verifies *today*

Today — meaning before [agenticplug#83][p83] is merged — the script
verifies five things:

1. **Local AgenticPlug broker /healthz** is reachable. If you're
   running `docker compose up`, this is the same `/healthz` that
   `scripts/smoke.sh` already checks.
2. **Edge health endpoint** (`https://reumanlab.ecoseek.org/healthz`
   by default) returns 200. Today this is served by a *temporary*
   health server on reumanlab; once #83 lands, the same URL will be
   served by the real connector. The smoke does not depend on which
   one is behind the URL.
3. **Token-safe request construction.** The session is sent as a
   `Bearer` header via a `chmod 600` curl config file — never on the
   command line, never in the URL, never logged.
4. **Graceful degradation when capabilities are missing.** The
   broker may return any of: HTTP 404, HTTP 501, or HTTP 200 with
   `{"error": {"code": "capability_not_ready"}}` (or
   `capability_not_found`, `capability_disabled`, `not_implemented`,
   `no_such_connector`, `connector_not_ready`, `unknown_capability`).
   All of these are classified as **waiting for #83** and reported
   non-fatally in the default mode. This is a deliberate
   choice — the alternative ("hard fail until #83 ships") would
   give the operator zero signal about *what* is missing.
5. **Real failures still fail.** If the connector returns an actual
   failure (`ssh_failed`, `hpc_unreachable`, `command_timeout`,
   `permission_denied`), or the broker returns a 5xx that is *not*
   one of the documented "not ready" shapes, the script exits
   non-zero with the broker's sanitized error code in the output.

[p83]: https://github.com/alrobles/agenticplug/issues/83

## What the scaffold will verify once #83 lands

Once #83 ships the read-only KU-HPC capabilities, the same three
probes will return `ready`:

- `remote.health` — connector is alive and the broker can reach it.
- `hpc.status`   — KU-HPC reachable from the connector via SSH.
- `hpc.queue`    — bounded read of the user's Slurm queue.

When all three return `ready`, the script prints
`Phase 3 remote smoke: PASS`. When some return `ready` and others
`not_yet`, it prints `PARTIAL` — useful during the rollout window
when capabilities are landing one at a time.

## Running

```bash
# Minimal — uses defaults (local broker on 8080, default reumanlab edge URL)
AGENTICPLUG_SESSION="<your-session-id>" bash scripts/remote-smoke.sh

# Strict mode — '#83 not ready' becomes a hard failure. Use this once
# #83 is merged and you expect the capabilities to be live.
SMOKE_REMOTE_STRICT=1 \
  AGENTICPLUG_SESSION="<your-session-id>" \
  bash scripts/remote-smoke.sh

# Pinned to a different broker (e.g. a lab-internal staging instance).
AGENTICPLUG_URL=https://broker.lab.example.org \
  AGENTICPLUG_SESSION="<your-session-id>" \
  bash scripts/remote-smoke.sh

# Skip the edge health leg entirely (e.g. when running offline against a
# local mock broker).
ECOSEEK_REMOTE_HEALTH_URL="" \
  AGENTICPLUG_SESSION="<your-session-id>" \
  bash scripts/remote-smoke.sh
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTICPLUG_URL` | `http://127.0.0.1:${AGENTICPLUG_PORT:-8080}` | Base URL for the AgenticPlug broker. |
| `AGENTICPLUG_PORT` | `8080` | Port for the local broker. Ignored when `AGENTICPLUG_URL` is set. |
| `AGENTICPLUG_SESSION` | *(required)* | Opaque session id (Bearer). Treated as a secret — never echoed. |
| `ECOSEEK_REMOTE_HEALTH_URL` | `https://reumanlab.ecoseek.org/healthz` | Edge health URL to probe. Empty string skips this leg. Must be `https://` or loopback. |
| `ECOSEEK_REMOTE_CONNECTOR` | `reumanlab` | Connector id to dispatch tasks to. |
| `ECOSEEK_REMOTE_TIMEOUT` | `15` | Per-request timeout (seconds). |
| `SMOKE_REMOTE_STRICT` | `0` | When `1`, "AgenticPlug #83 not ready" is a hard failure (exit 5). |

## Obtaining a session

Same procedure as the local smoke — see
[`smoke-test.md` → "Obtaining an AgenticPlug session"](./smoke-test.md).
The session for a remote-smoke run must come from the *same broker* you
intend to probe (i.e. don't paste a local-broker session into a
production-broker probe).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All required legs passed. Capabilities are READY, or "not ready yet" with `SMOKE_REMOTE_STRICT=0`. |
| 1 | Prerequisite missing (`curl`, `python3`). |
| 2 | Local AgenticPlug broker `/healthz` failed. |
| 3 | Edge health probe failed (only when explicitly configured). |
| 4 | `AGENTICPLUG_SESSION` missing, or task dispatch had an HTTP-level failure (401/403/etc.). |
| 5 | `SMOKE_REMOTE_STRICT=1` and at least one capability is still "not ready yet". |
| 6 | Connector reported a real failure (e.g. `ssh_failed`, `hpc_unreachable`). |

## Security invariants

These properties hold for every code path in `scripts/remote-smoke.sh`,
and are exercised by `scripts/remote_smoke_selftest.sh`:

- **No secrets in argv.** The session token is written to a
  `chmod 600` curl config file (`-K`); it never appears in `ps`.
- **No secrets in URLs.** The session is *only* sent as a `Bearer`
  header, never as a query parameter. The selftest's mock records
  every request and asserts `auth_in_url == false` for every call.
- **No secrets in logs.** The script never prints the value of any
  env var whose name contains `KEY`/`TOKEN`/`SECRET`/`PASSWORD`/
  `SESSION`. The selftest greps every script-output log for the
  fixture session and fails if it appears.
- **No SSH from EcoSeek.** This script does not run `ssh`, does not
  read any private key, and does not require a KU-HPC password.
  All remote calls go through AgenticPlug HTTPS.
- **No arbitrary command execution.** The script invokes a small,
  hard-coded set of read-only capabilities (`remote.health`,
  `hpc.status`, `hpc.queue`). It does not accept a capability name
  from the user.
- **HTTPS or loopback only for the edge.** The edge health URL must
  start with `https://` or point to `127.0.0.1` / `localhost`.
  Anything else is rejected up-front (exit 3).

## Troubleshooting

### Missing prerequisites

`curl` and `python3` are required. The script intentionally avoids
`jq` — Python is already a dependency of the existing local smoke,
and using only built-in `json` keeps the dependency surface small.

### Broker /healthz fails (exit 2)

The local AgenticPlug broker isn't up. Either start the local stack
(`docker compose up -d agenticplug`) or point the script at a
different broker with `AGENTICPLUG_URL=...`.

### Edge /healthz fails (exit 3)

Today this is the temporary health server on reumanlab.
Cloudflare may be down, the tunnel may have flapped, or the
temporary server may have been replaced ahead of #83 landing.
To skip this leg entirely while you investigate: `ECOSEEK_REMOTE_HEALTH_URL="" bash scripts/remote-smoke.sh`.

### Session missing or invalid (exit 4)

Set `AGENTICPLUG_SESSION` in `.env` (mode 600) or in your shell.
See [`smoke-test.md`](./smoke-test.md) for the GitHub-token →
session-id exchange.

### "Waiting for AgenticPlug #83" (exit 0 in default mode)

This is the **expected** state today. The capabilities aren't
implemented in the broker yet. Re-run the script once
[agenticplug#83][p83] is merged and deployed.

### Connector reported a real failure (exit 6)

The broker dispatched the task, the connector received it, and the
connector returned an error code in its sanitized error vocabulary.
Inspect the connector logs on reumanlab — see
[`reumanlab-connector-deploy.md`](./reumanlab-connector-deploy.md)
for log locations.

## Self-test (no Docker, no network)

```bash
bash scripts/remote_smoke_selftest.sh
```

This stands up an in-process Python mock for the broker and the edge
URL, then runs `scripts/remote-smoke.sh` against the mock for eight
cases:

1. Session missing → exit 4.
2. Broker returns 404 for /v1/tasks → "not ready" path, exit 0.
3. Broker returns 501 → "not ready", exit 0.
4. Broker returns 200 + `capability_not_ready` → "not ready", exit 0,
   output mentions "waiting for AgenticPlug #83".
5. Same as 4 but with `SMOKE_REMOTE_STRICT=1` → exit 5.
6. Broker returns 200 success for all capabilities → PASS (exit 0).
7. Mixed (one ready, two not) → PARTIAL (exit 0).
8. Connector returned `ssh_failed` → exit 6.

The selftest also asserts that the session id never appears in the
script's output and never appears in the URL of any recorded call to
`/v1/tasks` — the two security invariants this scaffold most needs to
defend.

## Relationship to issue #22 and AgenticPlug #83

This scaffold lands ahead of #83 deliberately. The reasoning:

- The temporary Cloudflare health server is already up at
  `https://reumanlab.ecoseek.org/healthz`. We want a script that can
  smoke that surface *today* so operators can detect tunnel flaps
  and Cloudflare misconfigurations independently of the broker work.
- The token-safe request construction and the JSON envelope for
  `/v1/tasks` are stable per the connector contract (see the
  reference link at the top of this document). #83 is implementing
  the *behavior* behind those capabilities, not changing the request
  shape.
- Splitting the work this way means operators can drop a green
  "remote smoke" check into ops dashboards now and re-run with
  `SMOKE_REMOTE_STRICT=1` the moment #83 ships. No further EcoSeek
  changes needed.

Until #83 lands, this PR **does not close #22**. The PR description
uses `Refs #22`, not `Closes #22`.
