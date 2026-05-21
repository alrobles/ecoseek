# EcoSeek smoke test

> **Status: pre-alpha.** This smoke test verifies that the DIY end-to-end stack comes up under `docker compose up` and that an EcoCoder agent can answer a query through AgenticPlug using a local model. **Do not use real production data or real secrets during this test.**
>
> EcoSeek is built on top of [AgenticSeek](https://github.com/alrobles/agenticSeek) and follows the same disclaimer: it is not affiliated with or endorsed by AgenticSeek or DeepSeek.

This document is the reproducible bar for the **alpha demo**. If any step fails, the stack is not alpha yet — open an issue and link to the failing step.

## The canonical Phase 2 smoke command (issue #15)

After `bash setup.sh && docker compose up -d`, a single command proves the Phase 2 workflow end to end:

```bash
bash scripts/smoke.sh
```

It performs three load-bearing checks plus an Ollama diagnostic, and prints `Phase 2 smoke: PASS` on success:

1. AgenticPlug `/healthz` returns `200`.
2. AgenticPlug `/v1/connectors` returns well-formed JSON (the gateway's Phase 1 stable surface).
3. **`POST /v1/chat/completions` on AgenticPlug returns a non-empty assistant message.** This is the canonical Phase 2 product success criterion (EcoSeek issue #15): prompt → AgenticPlug → local Ollama → assistant text, with the broker's session/scope/audit layer in the loop.

Between steps 2 and 3 the script also probes Ollama `/api/tags` directly to confirm `${OLLAMA_MODEL}` is present locally — purely as a diagnostic prerequisite so that a missing model surfaces as `exit 3` (clear) rather than as a sanitized `502/503` from the broker (ambiguous). The Ollama probe is **not** the product success criterion; step 3 is.

The script reads ports, the model name, and the AgenticPlug session id from `.env`, never logs values of variables named like secrets, sends the session id as `Authorization: Bearer …` (passed via a `chmod 600` config file, never on the command line), talks only to `127.0.0.1`, and is idempotent (re-running is safe). See [Troubleshooting](#troubleshooting) below if any step fails.

**Honesty notes for Phase 2.** This is the **local DIY demo** — `docker compose` on a laptop with a public model (`tinyllama`) and no private credentials. It is not the reumanlab-connector path and not the KU-HPC production path; those live in lab-internal documentation and the AgenticPlug HPC test suite respectively (see [Deployment paths](#deployment-paths--what-this-smoke-covers-and-what-it-does-not) below). What this smoke now proves end-to-end is that model traffic genuinely traverses AgenticPlug's gateway via the OpenAI-compatible `/v1/chat/completions` route (added in [AgenticPlug PR #80](https://github.com/alrobles/agenticplug/pull/80)), not just that Ollama is alive on a sibling port.

### Obtaining an AgenticPlug session

`/v1/chat/completions` uses the same auth as every other `/v1/*` route — there is no smoke-mode bypass. To get an opaque session id for `scripts/smoke.sh`:

1. Add your GitHub login to the broker allowlist and recreate the broker so it picks up the env change:

   ```bash
   # in .env (created by setup.sh)
   AGENTICPLUG_ALLOWED_LOGINS=your-github-login
   ```

   ```bash
   docker compose up -d --force-recreate agenticplug
   ```

2. Mint a personal GitHub access token (`read:user` scope is enough — no repo access needed) and exchange it for an opaque AgenticPlug session id. The broker forgets the GitHub token immediately; the CLI persists only the returned `session_id`:

   ```bash
   source .env
   GITHUB_TOKEN=ghp_xxx \
     curl -sS -X POST "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/cli/session" \
          -H 'Content-Type: application/json' \
          -d "{\"github_access_token\":\"$GITHUB_TOKEN\"}" \
       | python -c "import json,sys; print(json.load(sys.stdin)['session_id'])"
   ```

3. Put the returned session id in `.env` as `AGENTICPLUG_SESSION=<session_id>` (the file is already mode `600`; the value is treated as a secret by `setup.sh` and `scripts/smoke.sh`) and rerun `bash scripts/smoke.sh`.

If you do not provide a session, `scripts/smoke.sh` fails step 3 with a copy of these instructions instead of pretending it passed.

**Swapping the model.** The default is the public `tinyllama`. To switch to EcoCoder once it is published in the public Ollama registry:

```bash
OLLAMA_MODEL=ecocoder bash setup.sh        # regenerates .env / config.ini
docker compose up -d
docker compose exec ollama ollama pull ecocoder
bash scripts/smoke.sh
```

No KU-HPC access, no reumanlab secrets, and no private model weights are required — the smoke is fully reproducible on a vanilla WSL/Linux box with Docker.

## Scope and honesty notes (Phase 1)

- **No browser UI ships in this compose file.** The base stack builds the AgenticSeek **FastAPI backend** (`Dockerfile.backend`) under the service name `ecoseek-api`, not the React frontend. Step 6 below verifies the API is reachable; Step 7 sends the test query through that API, which routes through AgenticPlug to the local model — the same end-to-end path a future UI would use. A real chat UI is Phase 2.
- **Local model defaults to `tinyllama`.** The sprint mentions `OLLAMA_MODEL=ecocoder`, but `ecocoder` is not yet on the public Ollama registry. `setup.sh` writes `OLLAMA_MODEL=tinyllama` so the seven steps can complete on a vanilla install. Override by editing `.env` (or `OLLAMA_MODEL=ecocoder bash setup.sh`) once that model is published.
- **All host ports bind to `127.0.0.1`** (loopback only). Examples below use `127.0.0.1:$PORT` accordingly.

## Prerequisites

- `git`, `docker`, `docker compose v2`, `curl`.
- Repo cloned and current working directory is the repo root.
- Ports `${ECOSEEK_API_PORT}`, `${AGENTICPLUG_PORT}`, `${ECOAGENT_PORT}`, `${OLLAMA_PORT}` free on `localhost`. If you use the `observability` profile, `${PHOENIX_PORT}` (default `6006`) must also be free.
- After step 1 the values of those variables are loaded into your shell via `source .env`.

Throughout the document the placeholders `$ECOSEEK_API_PORT` (`3000`), `$AGENTICPLUG_PORT` (`8080`), `$ECOAGENT_PORT` (`8000`), and `$OLLAMA_PORT` (`11434`) are the defaults written by `setup.sh`.

---

### Step 1 — `setup.sh` generates `.env` without errors

**Command:**

```bash
./setup.sh
```

On Windows (PowerShell):

```powershell
.\setup.ps1
```

**Expected result:**

- Script exits with code `0`.
- A `.env` file exists at the repo root with file mode `600` (POSIX) or restricted ACL (Windows) containing at minimum:
  - `COMPOSE_PROFILES=cpu`
  - `ECOSEEK_API_PORT=3000`
  - `AGENTICPLUG_PORT=8080`
  - `ECOAGENT_PORT=8000`
  - `OLLAMA_PORT=11434`
  - `PHOENIX_PORT=6006`
  - `OLLAMA_MODEL=tinyllama`
  - `ECOSEEK_AAR_ENABLED=false`
  - `ECOSEEK_JUDGE_MODEL=auto`
  - `PHOENIX_ENDPOINT=http://phoenix:6006`
  - `PHOENIX_PROJECT_NAME=ecoseek`
  - `BROKER_SESSION_STORE=sqlite` (Phase 2: persistent session store)
  - `DEEPSEEK_API_KEY=` (empty unless you provided one)
- Final summary lists the loopback URLs above. **No value of `DEEPSEEK_API_KEY` (or any variable whose name contains `KEY`, `TOKEN`, `SECRET`, or `PASSWORD`) is printed** — secret-named variables show only `configured (value hidden)` or `not set`.
- `.repos/agenticplug`, `.repos/agenticSeek`, and `.repos/ecoagent` exist.

Verify quickly:

```bash
grep -E '^(COMPOSE_PROFILES|ECOSEEK_API_PORT|AGENTICPLUG_PORT|ECOAGENT_PORT|OLLAMA_PORT|PHOENIX_PORT|OLLAMA_MODEL|ECOSEEK_AAR_ENABLED|ECOSEEK_JUDGE_MODEL|PHOENIX_ENDPOINT|PHOENIX_PROJECT_NAME|BROKER_SESSION_STORE|DEEPSEEK_API_KEY)=' .env
```

---

### Step 2 — `docker compose up -d` starts all services

**Command:**

```bash
docker compose up -d
```

The default `COMPOSE_PROFILES=cpu` (in `.env`) activates the CPU Ollama variant; the `gpu` profile is mutually exclusive and is not selected here.

**Expected result:**

- Command exits with code `0` (after image build, which can take 5–10 minutes on first run).
- `docker compose ps` shows the base-stack services running:
  - `ecoseek-api`
  - `agenticplug`
  - `ecoagent`
  - `ollama`
  - `searxng`
  - `redis`
- Healthchecked services (`ecoseek-api`, `agenticplug`, `ecoagent`, `ollama`, `searxng`, `redis`) reach the `healthy` state within ~2 minutes. Re-run until they do:

  ```bash
  docker compose ps
  ```

  Each row's `STATUS` column should end in `(healthy)`.

---

### Step 3 — AgenticPlug `/healthz` returns 200

**Command:**

```bash
source .env
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:${AGENTICPLUG_PORT}/healthz"
```

**Expected result:**

- Output is exactly `200`.
- `/healthz` is a public liveness probe with no authentication; because the port is bound to `127.0.0.1`, only the local host can reach it.

---

### Step 4 — EcoAgent `/v1/tools` returns JSON

**Command:**

```bash
source .env
curl -s "http://127.0.0.1:${ECOAGENT_PORT}/v1/tools" | head -c 400
```

**Expected result:**

- HTTP `200`.
- Body is a JSON document listing tools (top-level array or object with a `tools` key). The output begins with `[` or `{` and at least one EcoAgent tool name is visible.

Stricter check:

```bash
curl -s "http://127.0.0.1:${ECOAGENT_PORT}/v1/tools" | python -c "import json,sys; d=json.load(sys.stdin); print('ok' if d else 'empty')"
```

Should print `ok`.

---

### Step 5 — Ollama `/api/tags` returns the list of models

**Command:**

```bash
source .env
curl -s "http://127.0.0.1:${OLLAMA_PORT}/api/tags"
```

**Expected result:**

- HTTP `200`.
- JSON response of the form `{"models":[ ... ]}`.
- After pulling the local model (`docker compose exec ollama ollama pull "${OLLAMA_MODEL}"`), the `models` array contains an entry whose `name` starts with `${OLLAMA_MODEL}` (e.g. `tinyllama:latest`).

If the list is empty, pull the model first:

```bash
docker compose exec ollama ollama pull "${OLLAMA_MODEL}"
```

then re-run the curl command.

---

### Step 6 — EcoSeek API is reachable

**Command:**

```bash
source .env
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:${ECOSEEK_API_PORT}/"
```

**Expected result:**

- HTTP status is `200`, `301`, `302`, `307`, or `404` (a FastAPI app may return `404` on `/` if no root route is mounted; the API is still alive as long as the request resolves to the container).
- `docker compose ps ecoseek-api` reports `(healthy)`.

**Note on browser UI.** This compose file does not build the AgenticSeek React frontend. There is no chat input rendered by the base stack — Step 7 reaches the same end-to-end path via the API.

---

### Step 7 — Confirm AgenticPlug exposes its stable surface, and a local model answers a real prompt **through the broker**

**Tip:** The canonical Phase 2 smoke command (`bash scripts/smoke.sh`, documented at the top of this file) automates the three sub-checks below. Run it for the standard pass/fail; keep this step for the manual walk-through and as the reference for what `smoke.sh` actually verifies.

**Background.** AgenticPlug now exposes an OpenAI-compatible `/v1/chat/completions` route (added in [AgenticPlug PR #80](https://github.com/alrobles/agenticplug/pull/80), tracking AgenticPlug issue #79 and EcoSeek issue #15). The route reuses the broker's existing session/scope middleware — there is no smoke-mode bypass — and forwards a fixed `/api/chat` path to an operator-configured Ollama backend (`OLLAMA_BASE_URL` in `docker-compose.yml`). The client never picks the upstream URL.

**Sub-check 7a — gateway connector surface.**

In one terminal, tail AgenticPlug:

```bash
docker compose logs -f agenticplug
```

In another terminal, hit the connector listing through the gateway:

```bash
source .env
curl -s -o /tmp/ecoseek-connectors.json \
     -w "%{http_code}\n" \
     "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/connectors"
python -c "import json; d=json.load(open('/tmp/ecoseek-connectors.json')); print('ok' if isinstance(d, (list, dict)) else 'bad')"
```

Expected: the `curl` line prints `200`; the `python` line prints `ok`; the `agenticplug` log shows the inbound request with an actor, action, and decision; **no value of `DEEPSEEK_API_KEY`, `AGENTICPLUG_SESSION`, or any variable whose name contains `KEY`/`TOKEN`/`SECRET`/`PASSWORD` appears in the log.**

**Sub-check 7b — broker-mediated chat (the product success criterion).** Send a tiny prompt to AgenticPlug's `/v1/chat/completions` with the session id you obtained in [Obtaining an AgenticPlug session](#obtaining-an-agenticplug-session), and assert the broker returns a non-empty assistant message:

```bash
source .env
curl -sS --max-time 120 \
     -H "Authorization: Bearer ${AGENTICPLUG_SESSION}" \
     -H 'Content-Type: application/json' \
     -d "{\"model\":\"${OLLAMA_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly the single word: pong.\"}],\"temperature\":0,\"stream\":false}" \
     "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/chat/completions" \
  | python -c "import json,sys; d=json.load(sys.stdin); c=d['choices'][0]['message']['content']; assert c.strip(), 'empty content'; print('model says (via broker):', c.strip()[:240])"
```

Expected: prints `model says (via broker): <some text>`. A `401 no_session` means the session is missing or expired; a `403 scope_denied` means the session lacks the `model.chat` capability; a `503 model_route_unconfigured` means `OLLAMA_BASE_URL` is not set on the broker container; a `502 upstream_error` or `503 upstream_unavailable` means Ollama is down or the model name is wrong. See the troubleshooting matrix below for each.

`scripts/smoke.sh` is the canonical wrapper around the three sub-checks of Step 7 (`/healthz`, `/v1/connectors`, broker-mediated `/v1/chat/completions`) and additionally probes Ollama `/api/tags` as a diagnostic prerequisite so that a missing model is reported with a clearer message than the broker's sanitized error vocabulary can give on its own.

### Known follow-ups (tracked, not in scope for Phase 1)

- **Orchestrator wiring** (Phase 2 follow-up). The `ecoseek-api`
  orchestrator's `OLLAMA_URL` still points at Ollama directly. Routing
  the orchestrator's model traffic through `/v1/chat/completions`
  instead is the next step now that the broker exposes the route. It is
  out of scope for this smoke, which validates the contract at the
  smoke-test layer.
- **Durable broker session/audit store** (Phase 2). Default is now
  `BROKER_SESSION_STORE=sqlite` (persistent, survives broker restarts
  via the `broker-data` Docker volume). The legacy `memory` backend
  remains available for ephemeral tests but is **not suitable for
  production**.
- **Streaming chat completions**. `stream: true` is intentionally
  rejected by `/v1/chat/completions` today — streaming requires more
  careful audit-log hygiene than the MVP provides. Tracked upstream.

---

## Tearing down

```bash
docker compose down
```

Add `-v` to also remove the named volumes (`ollama-data`, `redis-data`, `broker-data`, `workspace`, `screenshots`). **Do not** delete `.env` if you want to re-run the smoke test later.

## Optional profiles

- GPU passthrough (replaces the CPU Ollama; requires NVIDIA Container Toolkit). The `cpu` and `gpu` profiles are mutually exclusive — `cpu` is the default; pass `--profile gpu` instead of (not alongside) it:

  ```bash
  COMPOSE_PROFILES=gpu docker compose up -d
  # or:
  docker compose --profile gpu up -d
  ```

- Observability (adds Arize Phoenix at `http://127.0.0.1:${PHOENIX_PORT}` — default `6006`, on top of the CPU or GPU profile):

  ```bash
  docker compose --profile observability up -d        # adds phoenix to CPU base
  docker compose --profile gpu --profile observability up -d   # GPU + phoenix
  ```

## When the smoke test fails

- `docker compose logs <service>` for the specific service that failed its healthcheck.
- `docker compose ps` to confirm which containers never reached `(healthy)`.
- For step 7, also check `docker compose logs ecoseek-api` and `docker compose logs ecoagent` — most end-to-end failures are wiring problems between those two.

Reproducibility note: a passing run of all 7 steps satisfies alpha-checklist criteria 1–3 (`DIY mode without real secrets`, `EcoAgent loads a small EcoCoder agent`, `the agent makes at least one call through AgenticPlug to a local model`). Criteria 4 (audit log fidelity) and 5 (deterministic re-run) are tracked in Phase 2.

**Phase 2 update:** AgenticPlug now defaults to persistent SQLite session storage (`BROKER_SESSION_STORE=sqlite`), which survives broker restarts via the `broker-data` Docker volume. See Step 8 below for session persistence verification. For ephemeral testing, set `BROKER_SESSION_STORE=memory` in `.env` before running `docker compose up`.

---

### Step 8 — Session persistence across broker restart (Phase 2)

This step verifies that AgenticPlug sessions survive a broker container restart when using the SQLite backend (default for alpha).

**Prerequisites:**
- Steps 1-7 completed successfully.
- `BROKER_SESSION_STORE=sqlite` in `.env` (default after running `setup.sh`).
- You have a GitHub access token for testing (obtain via GitHub Device Flow or personal access token for smoke testing).

**Test procedure:**

1. **Create a test session:**

   ```bash
   source .env
   # Exchange a GitHub token for a session ID (mock for smoke test)
   # In a real flow, the client would complete GitHub Device Flow first.
   # For this smoke test, we verify the session store persists data.

   # Check the AgenticPlug session endpoint (if available)
   curl -s "http://127.0.0.1:${AGENTICPLUG_PORT}/admin/sessions" \
     -H "Authorization: Bearer mock-test-session" || echo "Session endpoint not accessible (expected for smoke test)"
   ```

2. **Verify the SQLite database exists:**

   ```bash
   docker compose exec agenticplug ls -lh /data/sessions.db || echo "SQLite file not yet created (will be created on first session)"
   ```

3. **Restart the broker container:**

   ```bash
   docker compose restart agenticplug
   # Wait for healthcheck to pass
   sleep 15
   docker compose ps agenticplug | grep healthy
   ```

4. **Verify the SQLite database persists:**

   ```bash
   docker compose exec agenticplug ls -lh /data/sessions.db
   docker compose exec agenticplug cat /data/sessions.db > /dev/null && echo "✓ SQLite file readable after restart"
   ```

5. **Check AgenticPlug logs for session store initialization:**

   ```bash
   docker compose logs agenticplug | grep -i "session" | tail -5
   ```

**Expected result:**

- The broker restarts successfully and reaches `(healthy)` state.
- The SQLite database file (`/data/sessions.db`) persists across the restart.
- AgenticPlug logs mention initializing the SQLite session store with no errors.
- If any sessions were active before the restart, they remain valid after (assuming they haven't expired).

**Testing with a real session (optional):**

To verify session validity across restart with a real GitHub token:

1. Complete GitHub Device Flow and exchange for a session ID.
2. Make an authenticated request to AgenticPlug with the session ID.
3. Restart the broker (`docker compose restart agenticplug`).
4. Repeat the authenticated request — it should succeed with the same session ID.
5. Wait for the session TTL to expire (default 24 hours, configurable).
6. Restart the broker again.
7. Verify that the expired session is now rejected (expired sessions should not be "resurrected").

For detailed session store documentation, including expiry, revocation, and corrupted store handling, see [`session-store.md`](./session-store.md).

---

## Troubleshooting

Common failure modes when running `bash scripts/smoke.sh` (or the manual
Steps 1–7) and the fastest way to unstick each one.

| Symptom | Likely cause | What to do |
|---|---|---|
| `Missing prerequisite: docker` or `docker compose v2 plugin not found` | Docker Desktop / Docker Engine is not installed or the v2 compose plugin is missing. | Install Docker (Linux / macOS / WSL): https://docs.docker.com/get-docker/. On Linux, ensure the user is in the `docker` group or invoke via `sudo` once to verify. Re-run `bash setup.sh`. |
| `docker: Cannot connect to the Docker daemon` (setup.sh or compose) | Docker Desktop is installed but not running, or on Linux the daemon is stopped. | Start Docker Desktop, or `sudo systemctl start docker`. Confirm with `docker info`. |
| `[1/3] AgenticPlug /healthz ...` returns `000` or `502` | `agenticplug` container is not running, not healthy, or the host port is shadowed. | `docker compose ps agenticplug` then `docker compose logs --tail=200 agenticplug`. If healthy but unreachable from host, see "port collision" below. |
| `[2/3] AgenticPlug /v1/connectors ...` returns non-JSON or 5xx | Broker started but its config is wrong (e.g. unreadable `BROKER_SESSION_STORE`, missing connector manifest). | `docker compose logs agenticplug \| tail -200`. Most often this is a broken `.env` — re-run `bash setup.sh` to regenerate. |
| `[diag] Ollama model '...' not present` and pull fails | The default `tinyllama` requires network egress from the Ollama container, or you set `OLLAMA_MODEL=ecocoder` before it is published. | For `tinyllama`, confirm `docker compose exec ollama curl -s https://ollama.ai/` works. For `ecocoder`, **EcoCoder is not yet in the public Ollama registry** — keep `OLLAMA_MODEL=tinyllama` until it ships. Once published, `OLLAMA_MODEL=ecocoder bash setup.sh && docker compose exec ollama ollama pull ecocoder`. |
| `[3/3] AGENTICPLUG_SESSION is not set` (exit 4) | The broker-mediated chat route requires a session — there is no smoke-mode bypass. | Follow [Obtaining an AgenticPlug session](#obtaining-an-agenticplug-session) to mint one and put it in `.env` as `AGENTICPLUG_SESSION=<session_id>`. |
| `[3/3] /v1/chat/completions returned HTTP 401` (`no_session`) | The session id is missing, expired, or for a user no longer in `AGENTICPLUG_ALLOWED_LOGINS`. | Re-issue the session via `POST /v1/cli/session`. If the broker was recreated and `BROKER_SESSION_STORE=memory`, all sessions were lost — switch to the default `sqlite` backend. |
| `[3/3] /v1/chat/completions returned HTTP 403` (`scope_denied` or `forbidden`) | The session was issued with `scopes.capabilities` that does not include `model.chat`, OR the broker's `userAuthorizer` denied the user for that capability. | Re-issue the session without `scopes.capabilities` (unscoped sessions are backward compatible), or add `model.chat` to the scope list. Confirm your GitHub login is in `AGENTICPLUG_ALLOWED_LOGINS`. |
| `[3/3] /v1/chat/completions returned HTTP 503` (`model_route_unconfigured`) | The broker container does not have `OLLAMA_BASE_URL` set. The route fails closed by design. | Confirm `OLLAMA_BASE_URL: "http://ollama:${OLLAMA_PORT:-11434}"` is present in the `agenticplug` service of `docker-compose.yml`, then `docker compose up -d --force-recreate agenticplug`. |
| `[3/3] /v1/chat/completions returned HTTP 503` (`upstream_unavailable`) or `502` (`upstream_error`) | Broker reached upstream Ollama but Ollama refused or returned a non-2xx. Most often the model name does not exist on the Ollama side, or Ollama is still warming up. | `docker compose ps ollama`; pull the model (`docker compose exec ollama ollama pull "${OLLAMA_MODEL}"`); retry. First call after a cold pull can time out — re-run. |
| `[3/3] /v1/chat/completions returned HTTP 400` (`invalid_model`, `streaming_not_supported`, `invalid_role`, …) | The request body shape is wrong: model name fails the `[A-Za-z0-9_.:/-]+` regex, `stream: true` was sent, or a message role/content is invalid. | Use the unmodified `scripts/smoke.sh`. If you patched it, verify `OLLAMA_MODEL` is a plain identifier and `stream` is `false` or omitted. |
| `[3/3] /v1/chat/completions ... empty assistant 'content'` | Model loaded but generated nothing (rare with `tinyllama`), or the prompt is too short for the model to produce text. | Re-run with a clearer prompt: `SMOKE_PROMPT="Write one sentence about ecology." bash scripts/smoke.sh`. If still empty, `docker compose logs ollama`. |
| `bind: address already in use` during `docker compose up` (port collision) | Another process on the host is bound to one of `${ECOSEEK_API_PORT}`, `${AGENTICPLUG_PORT}`, `${ECOAGENT_PORT}`, `${OLLAMA_PORT}`, or `${PHOENIX_PORT}`. | Find the offender: `ss -ltnp \| grep :${PORT}` (Linux) or `lsof -iTCP:${PORT} -sTCP:LISTEN` (macOS/WSL). Either stop it or pick a free port by editing `.env` (e.g. `AGENTICPLUG_PORT=8081`) and re-running `docker compose up -d`. Smoke reads ports from `.env`, so no other edits are needed. |
| `bind: permission denied` when binding < 1024 | A non-root user trying to publish on a privileged port. | Set a port ≥ 1024 in `.env` (the defaults already are). Avoid 80/443 for the smoke. |
| AgenticPlug `401 no_session` on a manual `/v1/tasks` POST | `POST /v1/tasks` requires a CLI session obtained from `POST /v1/cli/session` with a real GitHub access token and the user listed in `AGENTICPLUG_ALLOWED_LOGINS`. | The Phase 2 smoke does **not** exercise this path — it is documented in the upstream gateway and requires a non-secret GitHub token for the test user. For session lifecycle and persistence, see Step 8 above and [`session-store.md`](./session-store.md). |
| Session vanishes between requests / `expired_session` after restart | `BROKER_SESSION_STORE=memory` was set in `.env`, or the broker container was recreated (not just restarted) and the named volume `broker-data` was removed. | The alpha default is `BROKER_SESSION_STORE=sqlite`. Re-run `bash setup.sh` to regenerate `.env`. Do **not** pass `-v` to `docker compose down` between smoke runs if you want sessions to persist. See [`session-store.md`](./session-store.md) for the full lifecycle, expiry, and corruption-recovery behavior. |
| `[5/...] EcoSeek API not reachable` (soft warning) | `ecoseek-api` is still building or its healthcheck is still in `start_period`. The full Phase 2 smoke does not require the orchestrator for a pass — it is informational. | `docker compose ps ecoseek-api`; if it is `(healthy)` re-run smoke. To make this a hard failure: `SMOKE_REQUIRE_API=1 bash scripts/smoke.sh`. |
| `.env not found` from `scripts/smoke.sh` | You ran the smoke before `bash setup.sh`. | `bash setup.sh && docker compose up -d` then re-run. |

If a row above does not match the failure you are seeing, attach
`docker compose ps`, the last 200 lines of `docker compose logs
<failing-service>`, and the full output of `bash scripts/smoke.sh` to an
issue against this repository.

## Deployment paths — what this smoke covers and what it does not

The smoke test in this document is **only** for the local DIY demo. It is
intentionally scoped to laptops/workstations and never reaches any
private infrastructure.

| Path | What it is | What this smoke covers |
|---|---|---|
| **Local DIY demo** (this doc) | `docker compose up -d` on WSL / Linux / macOS with a public model. No private credentials. | Yes — this is what `bash scripts/smoke.sh` validates. |
| **reumanlab connector** | EcoSeek wired to a private reumanlab AgenticPlug deployment and connector manifest. Requires lab-issued credentials and an entry in `AGENTICPLUG_ALLOWED_LOGINS`. | Not covered. The local smoke must pass *without* any reumanlab secrets, by design. The reumanlab connector path lives in lab-internal documentation. |
| **KU-HPC production path** | AgenticPlug routes tasks to KU-HPC clusters via HPC connectors. Requires KU-HPC accounts, signed connector manifests, and the broker's allowlist. | Not covered. KU-HPC integration is exercised in the AgenticPlug repository's HPC test suite (`test:hpc`, `test:remote-symlink`) and through real cluster runs, not from this repo. |

If you cannot get the local DIY smoke to pass on a clean machine, do not
attempt to wire the reumanlab connector or the KU-HPC path. The local
DIY smoke is the precondition for both.

---
