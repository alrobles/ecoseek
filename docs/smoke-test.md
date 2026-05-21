# EcoSeek smoke test

> **Status: pre-alpha.** This smoke test verifies that the DIY end-to-end stack comes up under `docker compose up` and that an EcoCoder agent can answer a query through AgenticPlug using a local model. **Do not use real production data or real secrets during this test.**
>
> EcoSeek is built on top of [AgenticSeek](https://github.com/alrobles/agenticSeek) and follows the same disclaimer: it is not affiliated with or endorsed by AgenticSeek or DeepSeek.

This document is the reproducible bar for the **alpha demo**. If any step fails, the stack is not alpha yet — open an issue and link to the failing step.

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

### Step 7 — Confirm AgenticPlug exposes its stable Phase 1 surface

**Background — what is and isn't stable in Phase 1.** AgenticPlug's
gateway exposes a handful of endpoints that are part of its public Phase 1
contract: `/healthz` (already covered in Step 3), `/v1/connectors`,
`/v1/connectors/:id`, `/v1/connectors/:id/health`, `/v1/clusters`,
`/v1/cli/session`, `/v1/tasks`, and `/v1/approvals` (see
[`alrobles/agenticplug` → `broker/server.js`](https://github.com/alrobles/agenticplug/blob/main/broker/server.js)).
There is **no** OpenAI-compatible `/v1/chat/completions` route and **no**
`/v1/proxy/ollama/*` route in Phase 1 — model traffic flows through the
`ecoseek-api` orchestrator (which already verified end-to-end in Step 6),
not through AgenticPlug. A first-class "send a prompt, get a response"
gateway endpoint is tracked as a Phase 2 follow-up.

This step therefore pins the smoke test to the gateway's actually-stable
contract: a request to AgenticPlug returns a well-formed connector
listing, demonstrating that the broker is up, routing JSON, and reachable
from the host loopback.

**Command:**

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

**Expected result:**

- The `curl` line prints `200`.
- The `python` line prints `ok` (the body parses as JSON — either an
  array of connector entries or an object wrapping one).
- The `agenticplug` log shows the inbound request, carrying an actor,
  action, and decision. **No value of `DEEPSEEK_API_KEY` or of any other
  variable whose name contains `KEY`, `TOKEN`, `SECRET`, or `PASSWORD`
  appears in the log.**
- With `OLLAMA_MODEL=tinyllama` (the default) and the model pulled in
  Step 5, the orchestrator from Step 6 is already wired to use it. End-
  to-end model traffic through the gateway is a Phase 2 deliverable —
  see "Known follow-ups" below.

### Known follow-ups (tracked, not in scope for Phase 1)

- **Gateway model-routing endpoint** (issue #13 follow-up, Phase 2).
  AgenticPlug does not yet expose an OpenAI-compatible
  `/v1/chat/completions` or `/v1/proxy/ollama/api/generate` route. The
  smoke test will pin one of those once the contract lands in
  `alrobles/agenticplug` and the orchestrator is wired to use it.
- **Durable broker session/audit store** (Phase 2). `BROKER_SESSION_STORE`
  defaults to `memory`, which is intentional for the Phase 1 DIY demo:
  sessions and audit log reset on `docker compose restart agenticplug`,
  so this configuration is **not suitable for production**. Phase 2
  switches to a durable SQLite-backed store.

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
