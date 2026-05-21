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
  - `BROKER_SESSION_STORE=sqlite` (alpha default — persistent across broker restarts)
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
- **Broker session store.** As of issue #14, `BROKER_SESSION_STORE`
  defaults to `sqlite` (persistent, backed by the `broker-data` volume)
  — see Step 8 below for the restart-persistence check. The `memory`
  backend is still available as an explicit override for tests/dev
  (`BROKER_SESSION_STORE=memory` in `.env`) but is **not suitable for
  production**.

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

**Session store note:** AgenticPlug defaults to persistent SQLite session storage (`BROKER_SESSION_STORE=sqlite`) for the alpha. The SQLite file lives in the `broker-data` Docker volume and survives `docker compose restart agenticplug` (verified by Step 8 below). For ephemeral testing, set `BROKER_SESSION_STORE=memory` in `.env` before running `docker compose up`.

---

### Step 8 — Session store persistence across broker restart (alpha)

This step verifies the **infrastructure** for persistent sessions: the
SQLite-backed store is selected, the file is created in the
`broker-data` volume, and its contents survive a broker restart. It does
**not** mint authenticated sessions, because Phase 1 of this compose
file does not expose a usable GitHub Device Flow exchange surface from
the smoke-test host — claiming an end-to-end "session survives restart"
result here would be misleading. End-to-end validation (real session ID
remains valid after restart, expired session stays rejected after
restart) lives in `alrobles/agenticplug` and is referenced under
"Known follow-ups" below.

**Prerequisites:**
- Steps 1–7 completed successfully.
- `BROKER_SESSION_STORE=sqlite` in `.env` (default after running `setup.sh` / `setup.ps1`).

**Test procedure:**

1. **Confirm the broker booted with the SQLite backend** (not memory):

   ```bash
   docker compose exec agenticplug printenv BROKER_SESSION_STORE
   ```

   Expected output: `sqlite`.

2. **Confirm the broker-data volume is mounted at `/data`:**

   ```bash
   docker compose config | grep -A1 'broker-data'
   docker compose exec agenticplug sh -c 'test -d /data && echo "/data mounted"'
   ```

   Expected: the compose config shows the named volume `broker-data`
   bound to `/data`, and the shell check prints `/data mounted`.

3. **Wait for the SQLite file to be created and capture its inode +
   size + a content hash.** The file is created on broker startup once
   the SQLite store initializes; if it is not present yet, wait briefly
   and re-run.

   ```bash
   docker compose exec agenticplug sh -c '
     for i in 1 2 3 4 5; do
       [ -f /data/sessions.db ] && break
       sleep 2
     done
     ls -lh /data/sessions.db &&
     stat -c "inode=%i size=%s" /data/sessions.db &&
     sha256sum /data/sessions.db
   ' | tee /tmp/ecoseek-sessdb-before.txt
   ```

   Expected: the file exists at `/data/sessions.db`, has mode `0600`
   (owner read/write only — security invariant from `session-store.md`),
   and the command prints an inode, size, and SHA-256.

4. **Restart the broker container and wait for healthcheck:**

   ```bash
   docker compose restart agenticplug
   # Wait for /healthz to return 200, up to ~30s.
   for i in $(seq 1 30); do
     code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${AGENTICPLUG_PORT}/healthz" || true)
     [ "$code" = "200" ] && break
     sleep 1
   done
   docker compose ps agenticplug
   ```

   Expected: `STATUS` ends in `(healthy)`.

5. **Confirm the SQLite file survived the restart with identical
   inode and content** (same volume, same bytes — not a fresh DB):

   ```bash
   docker compose exec agenticplug sh -c '
     ls -lh /data/sessions.db &&
     stat -c "inode=%i size=%s" /data/sessions.db &&
     sha256sum /data/sessions.db
   ' | tee /tmp/ecoseek-sessdb-after.txt

   diff /tmp/ecoseek-sessdb-before.txt /tmp/ecoseek-sessdb-after.txt \
     && echo "OK: sessions.db inode + content unchanged across restart" \
     || echo "FAIL: sessions.db differs after restart — store is not persistent"
   ```

   Expected: the `diff` is empty and the success line prints. A
   differing inode or SHA would indicate the volume mount was lost or
   the broker recreated the database — that is a regression of issue
   `#14` and should be filed.

6. **Confirm AgenticPlug logged a sqlite (not memory) session-store
   init line and that no secret-named variable leaked:**

   ```bash
   docker compose logs agenticplug | grep -iE 'session.*store|sqlite' | tail -10
   docker compose logs agenticplug | grep -iE 'DEEPSEEK_API_KEY|KEY=|TOKEN=|SECRET=|PASSWORD=' \
     && echo "FAIL: secret-named variable appeared in logs" \
     || echo "OK: no secret-named variable in logs"
   ```

   Expected: at least one log line mentions the SQLite session store
   (or `/data/sessions.db`) and **no** raw value of a `KEY`/`TOKEN`/
   `SECRET`/`PASSWORD` variable appears in the log.

**What this step does and does not prove:**

- ✅ Proves: SQLite is the active backend; the `broker-data` volume is
  mounted; the database file is created with `0600` permissions; its
  inode and bytes are identical before and after a `docker compose
  restart agenticplug`.
- ❌ Does **not** prove: that a real session ID (issued via GitHub
  Device Flow) remains accepted after the restart, or that an expired
  / revoked session stays rejected after the restart. Those require
  the broker's `/auth/exchange` surface and live in the upstream
  AgenticPlug test suite — see "Known follow-ups" below.

### Known follow-ups (tracked, not in scope for Phase 1)

- **Gateway model-routing endpoint** (issue #13 follow-up, Phase 2).
  AgenticPlug does not yet expose an OpenAI-compatible
  `/v1/chat/completions` or `/v1/proxy/ollama/api/generate` route. The
  smoke test will pin one of those once the contract lands in
  `alrobles/agenticplug` and the orchestrator is wired to use it.
- **End-to-end session expiry / revocation / corrupted-store tests**
  (issue #14 follow-up). The behavioural guarantees called out in
  `docs/session-store.md` — a session that is expired or revoked
  before a broker restart must remain invalid after the restart, and
  a corrupted SQLite file must cause the broker to refuse to start
  rather than silently discard sessions — are tested in the
  `alrobles/agenticplug` repository (its `scoped-sessions` and
  `mock-gateway-security` suites referenced in `session-store.md`).
  An EcoSeek-level smoke step that exercises them through this
  compose file is **not yet implemented** because it requires a
  scriptable session-mint path that doesn't exist in Phase 1; track
  it as a follow-up to issue #14 alongside the gateway routing
  endpoint above.

For detailed session store documentation, including expiry,
revocation, and corrupted-store handling, see
[`session-store.md`](./session-store.md).

---
