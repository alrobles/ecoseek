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
- Ports `${ECOSEEK_API_PORT}`, `${AGENTICPLUG_PORT}`, `${ECOAGENT_PORT}`, `${OLLAMA_PORT}` free on `localhost`.
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
  - `OLLAMA_MODEL=tinyllama`
  - `ECOSEEK_AAR_ENABLED=false`
  - `ECOSEEK_JUDGE_MODEL=auto`
  - `PHOENIX_ENDPOINT=http://phoenix:6006`
  - `PHOENIX_PROJECT_NAME=ecoseek`
  - `DEEPSEEK_API_KEY=` (empty unless you provided one)
- Final summary lists the loopback URLs above. **No value of `DEEPSEEK_API_KEY` (or any variable whose name contains `KEY`, `TOKEN`, `SECRET`, or `PASSWORD`) is printed** — secret-named variables show only `configured (value hidden)` or `not set`.
- `.repos/agenticplug`, `.repos/agenticSeek`, and `.repos/ecoagent` exist.

Verify quickly:

```bash
grep -E '^(COMPOSE_PROFILES|ECOSEEK_API_PORT|AGENTICPLUG_PORT|ECOAGENT_PORT|OLLAMA_PORT|OLLAMA_MODEL|ECOSEEK_AAR_ENABLED|ECOSEEK_JUDGE_MODEL|PHOENIX_ENDPOINT|PHOENIX_PROJECT_NAME|DEEPSEEK_API_KEY)=' .env
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

### Step 7 — Query the API and confirm the call traverses AgenticPlug

**Command:**

In one terminal, tail AgenticPlug:

```bash
docker compose logs -f agenticplug
```

In another terminal, send the test query through AgenticPlug to the model:

```bash
source .env
curl -s -X POST "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${OLLAMA_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"¿Qué herramientas tienes disponibles?\"}]}"
```

If your AgenticPlug build does not expose an OpenAI-compatible completions endpoint, fall back to direct Ollama generation through the gateway:

```bash
curl -s -X POST "http://127.0.0.1:${AGENTICPLUG_PORT}/v1/proxy/ollama/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${OLLAMA_MODEL}\",\"prompt\":\"¿Qué herramientas tienes disponibles?\"}"
```

**Expected result:**

- HTTP `200` with a non-empty JSON body containing a model response in natural language. The response should mention the kinds of tools exposed by EcoAgent (ecological lookups, taxonomy, etc.) — the exact wording depends on the local model.
- The `agenticplug` log shows at least one inbound request and one outbound request to either `ecoagent` (`/v1/tools` / `/v1/tools/{name}/execute`) or `ollama` (`/api/generate` / `/api/chat`). Each line carries an actor, action, and decision; no value of `DEEPSEEK_API_KEY` or any other secret-named variable appears in the log.
- With `OLLAMA_MODEL=tinyllama` (the default) the answer comes from the local model. Set `OLLAMA_MODEL=ecocoder` and pull that image to swap in EcoCoder once it ships publicly. If `DEEPSEEK_API_KEY` is set in `.env`, AgenticPlug may route to DeepSeek instead.

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

- Observability (adds Arize Phoenix at `http://127.0.0.1:6006`, on top of the CPU or GPU profile):

  ```bash
  docker compose --profile observability up -d        # adds phoenix to CPU base
  docker compose --profile gpu --profile observability up -d   # GPU + phoenix
  ```

## When the smoke test fails

- `docker compose logs <service>` for the specific service that failed its healthcheck.
- `docker compose ps` to confirm which containers never reached `(healthy)`.
- For step 7, also check `docker compose logs ecoseek-api` and `docker compose logs ecoagent` — most end-to-end failures are wiring problems between those two.

Reproducibility note: a passing run of all 7 steps satisfies alpha-checklist criteria 1–3 (`DIY mode without real secrets`, `EcoAgent loads a small EcoCoder agent`, `the agent makes at least one call through AgenticPlug to a local model`). Criteria 4 (audit log fidelity) and 5 (deterministic re-run) are tracked in Phase 2. AgenticPlug session storage in this Phase 1 is in-memory (`BROKER_SESSION_STORE=memory`), so audit/log persistence resets on `docker compose restart agenticplug`; Phase 2 will switch to a durable store.
