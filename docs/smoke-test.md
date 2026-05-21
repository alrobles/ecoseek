# EcoSeek smoke test

> **Status: pre-alpha.** This smoke test verifies that the DIY end-to-end stack comes up under `docker compose up` and that an EcoCoder agent can answer a query through AgenticPlug using a local model. **Do not use real production data or real secrets during this test.**
>
> EcoSeek is built on top of [AgenticSeek](https://github.com/alrobles/agenticSeek) and follows the same disclaimer: it is not affiliated with or endorsed by AgenticSeek or DeepSeek.

This document is the reproducible bar for the **alpha demo**. If any step fails, the stack is not alpha yet — open an issue and link to the failing step.

## Prerequisites

- `git`, `docker`, `docker compose v2`, `curl`.
- Repo cloned and current working directory is the repo root.
- Ports `${ECOSEEK_UI_PORT}`, `${AGENTICPLUG_PORT}`, `${ECOAGENT_PORT}`, `${OLLAMA_PORT}` free on `localhost`.
- After step 1 the values of those variables are loaded into your shell via `source .env`.

Throughout the document the placeholders `$ECOSEEK_UI_PORT` (`3000`), `$AGENTICPLUG_PORT` (`8080`), `$ECOAGENT_PORT` (`8000`) and `$OLLAMA_PORT` (`11434`) are the defaults written by `setup.sh`.

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
- A `.env` file exists at the repo root containing at minimum:
  - `ECOSEEK_UI_PORT=3000`
  - `AGENTICPLUG_PORT=8080`
  - `ECOAGENT_PORT=8000`
  - `OLLAMA_PORT=11434`
  - `OLLAMA_MODEL=ecocoder`
  - `ECOSEEK_AAR_ENABLED=false`
  - `ECOSEEK_JUDGE_MODEL=auto`
  - `PHOENIX_ENDPOINT=http://phoenix:6006`
  - `PHOENIX_PROJECT_NAME=ecoseek`
  - `DEEPSEEK_API_KEY=` (empty unless you provided one)
- Final summary lists the local URLs above. **No value of `DEEPSEEK_API_KEY` (or any variable whose name contains `KEY`, `TOKEN`, `SECRET`, or `PASSWORD`) is printed.**
- `.repos/agenticplug`, `.repos/agenticSeek`, and `.repos/ecoagent` exist.

Verify quickly:

```bash
grep -E '^(ECOSEEK_UI_PORT|AGENTICPLUG_PORT|ECOAGENT_PORT|OLLAMA_PORT|OLLAMA_MODEL|ECOSEEK_AAR_ENABLED|ECOSEEK_JUDGE_MODEL|PHOENIX_ENDPOINT|PHOENIX_PROJECT_NAME|DEEPSEEK_API_KEY)=' .env
```

---

### Step 2 — `docker compose up -d` starts all services

**Command:**

```bash
docker compose up -d
```

**Expected result:**

- Command exits with code `0` (after image build, which can take 5–10 minutes on first run).
- `docker compose ps` shows the base-stack services running:
  - `ecoseek-ui`
  - `agenticplug`
  - `ecoagent`
  - `ollama`
  - `searxng`
  - `redis`
- Healthchecked services (`ecoseek-ui`, `agenticplug`, `ecoagent`, `ollama`, `redis`) reach the `healthy` state within ~2 minutes. Re-run `docker compose ps` until they do:

  ```bash
  docker compose ps
  ```

  Each entry under the `STATUS` column should end in `(healthy)` for the services above.

---

### Step 3 — AgenticPlug `/healthz` returns 200

**Command:**

```bash
source .env
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:${AGENTICPLUG_PORT}/healthz"
```

**Expected result:**

- Output is exactly `200`.
- A `GET /healthz` request to AgenticPlug succeeds without authentication (it is a liveness probe).

---

### Step 4 — EcoAgent `/v1/tools` returns JSON

**Command:**

```bash
source .env
curl -s "http://localhost:${ECOAGENT_PORT}/v1/tools" | head -c 400
```

**Expected result:**

- HTTP `200`.
- Response body is a JSON document containing a list of tools (e.g. a top-level array or an object with a `tools` key). The output begins with `[` or `{` and at least one tool name from the EcoAgent catalogue is visible.

For a stricter check:

```bash
curl -s "http://localhost:${ECOAGENT_PORT}/v1/tools" | python -c "import json,sys; d=json.load(sys.stdin); print('ok' if d else 'empty')"
```

Should print `ok`.

---

### Step 5 — Ollama `/api/tags` returns the list of models

**Command:**

```bash
source .env
curl -s "http://localhost:${OLLAMA_PORT}/api/tags"
```

**Expected result:**

- HTTP `200`.
- JSON response of the form `{"models":[ ... ]}`.
- After pulling the EcoCoder model (`docker compose exec ollama ollama pull "${OLLAMA_MODEL}"`), the `models` array contains an entry whose `name` starts with `${OLLAMA_MODEL}` (e.g. `ecocoder:latest`).

If the list is empty, pull the model first:

```bash
docker compose exec ollama ollama pull "${OLLAMA_MODEL}"
```

then re-run the curl command.

---

### Step 6 — EcoSeek UI is accessible

**Command:**

```bash
source .env
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:${ECOSEEK_UI_PORT}/"
```

**Expected result:**

- HTTP status is `200`, `301`, `302`, or `307` (the UI may redirect to its app entry point).
- Opening `http://localhost:${ECOSEEK_UI_PORT}` in a browser loads the EcoSeek interface (AgenticSeek-based UI with EcoSeek personality).

---

### Step 7 — Query the UI and receive a response through AgenticPlug

**Command:**

1. Open `http://localhost:${ECOSEEK_UI_PORT}` in a browser.
2. In the chat input, send the literal query:

   ```
   ¿Qué herramientas tienes disponibles?
   ```

3. While the agent answers, tail AgenticPlug to confirm the call traverses the gateway:

   ```bash
   docker compose logs -f agenticplug
   ```

**Expected result:**

- The UI returns a natural-language answer that **enumerates EcoAgent tools** (e.g. the kind of tools exposed by `/v1/tools` in Step 4 — ecological data lookups, taxonomy queries, etc.).
- The `agenticplug` log shows at least one inbound request from `ecoseek-ui` and one outbound request to either `ecoagent` (`/v1/tools` or `/v1/tools/{name}/execute`) or `ollama` (`/api/generate` / `/api/chat`). Each line carries an actor, action, and decision; no value of `DEEPSEEK_API_KEY` or any other secret-named variable appears in the log.
- The answer is generated by the **local** EcoCoder model (`OLLAMA_MODEL=ecocoder`) unless you set `DEEPSEEK_API_KEY` in `.env`, in which case it may come from DeepSeek instead.

---

## Tearing down

```bash
docker compose down
```

Add `-v` to also remove the named volumes (`ollama-data`, `redis-data`, `broker-data`, `workspace`, `screenshots`). **Do not** delete `.env` if you want to re-run the smoke test later.

## Optional profiles

- GPU passthrough (replaces CPU Ollama with `ollama-gpu`, requires NVIDIA Container Toolkit):

  ```bash
  docker compose --profile gpu up -d
  ```

- Observability (adds Arize Phoenix at `http://localhost:6006`):

  ```bash
  docker compose --profile observability up -d
  ```

## When the smoke test fails

- `docker compose logs <service>` for the specific service that failed its healthcheck.
- `docker compose ps` to confirm which containers never reached `(healthy)`.
- For step 7, also check `docker compose logs ecoseek-ui` and `docker compose logs ecoagent` — most end-to-end failures are wiring problems between those two.

Reproducibility note: a passing run of all 7 steps satisfies the alpha-checklist criteria 1–3 (`DIY mode without real secrets`, `EcoAgent loads a small EcoCoder agent`, `the agent makes at least one call through AgenticPlug to a local model`). Criteria 4 (audit log fidelity) and 5 (deterministic re-run) are tracked in Phase 2.
