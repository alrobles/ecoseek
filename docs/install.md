# Install

> **Status: pre-alpha.** This document describes how to install and run EcoSeek locally. **Do not use real production data with EcoSeek at this stage.**

**Last updated:** 2026-09-04

## Prerequisites

- **Git** (any recent version)
- **Docker** and **Docker Compose v2** (Docker Desktop on Windows/macOS, or docker-ce on Linux)
- **Optional:** DeepSeek API key (BYOK) — get one at https://platform.deepseek.com/api_keys
- **Optional:** `OLLAMA_BASE_URL` for local inference via the stack's Ollama container (`http://ollama:11434`)

No Node.js, Python, or npm required on the host. Everything runs inside containers.

## Quick start (any OS)

Works identically on Linux, macOS, and Windows (WSL or native Docker Desktop).

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
DEEPSEEK_API_KEY=sk-your-key-here bash setup.sh
```

The script will:
1. Clone the `ecoagent` dependency repo using your git auth
2. Generate `.env` with the Docker stack defaults (ports, Emily gateway access, LLM provider)
3. Leave you ready to start the stack with `docker compose up -d`

If you don't pass the API key, the script will prompt you interactively.

### Using `gh` CLI

```bash
gh repo clone alrobles/ecoseek
cd ecoseek
DEEPSEEK_API_KEY=sk-your-key-here bash setup.sh
```

### Windows (PowerShell, no WSL)

```powershell
$env:DEEPSEEK_API_KEY="sk-your-key-here"
.\setup.ps1
```

### What starts

| Service | URL | What it does |
|---------|-----|-------------|
| **Emily** (Hermes gateway) | `http://127.0.0.1:8642` | Primary AI backend — Hermes Agent API server (`/health`, `/v1/chat/completions`) |
| **EcoSeek API** | `http://127.0.0.1:3000` | Lightweight FastAPI router (`/`, `/v1/query`) |
| **EcoAgent** | `http://127.0.0.1:8000/v1/tools` | Ecological/scientific tool server (30+ tools) |
| **Ollama** | `http://127.0.0.1:11434` | Default local OpenAI-compatible model backend |
| **SearxNG** | (internal) | Private web search for the agent |
| **Redis** | (internal) | Task queue / cache |

### Stop / restart / logs

```bash
docker compose down          # stop
docker compose up -d         # restart (detached)
docker compose logs -f       # follow logs
bash setup.sh                # rebuild after upstream changes
```

### How LLM routing is configured

Provider selection is configured through the **Emily** (Hermes gateway) environment. `setup.sh` writes these into `.env` and the Docker stack reads them directly:

- `DEEPSEEK_API_KEY` — DeepSeek cloud BYOK. Set it before running `bash setup.sh`, or add it to `.env` and re-create Emily: `docker compose up -d emily`.
- `OLLAMA_BASE_URL` — local inference via the stack's Ollama container (`http://ollama:11434`). Pull a model first: `docker compose exec ollama ollama pull tinyllama`.
- `GATEWAY_ALLOW_ALL_USERS=true` — the Hermes gateway denies all chat requests by default; this setting allows local chat with Emily. Keep it on for a single-user self-hosted stack (all ports bind to 127.0.0.1).
- `EMILY_API_KEY` — shared secret between the Emily backend (`API_SERVER_KEY`) and the frontend nginx proxy (`EMILY_HERMES_KEY` defaults to it).
- `LOCAL_LLM_URL` — optional direct OpenAI-compatible local fallback for the EcoSeek API router.
- `UPSTREAM_TIMEOUT_S` — timeout applied to every upstream call.

EcoSeek API routes chat to **Emily directly** (`/v1/chat/completions`) — no broker in the loop. `POST /v1/query` accepts `text` (plus optional `mode`, `session_id`, `metadata`). In alpha, `stream=true` returns `501`.

### Changing the API key

```bash
# Option 1: re-run setup (regenerates .env)
DEEPSEEK_API_KEY=sk-new-key bash setup.sh

# Option 2: edit .env manually, then re-create the affected services so
# they pick up the new value (do NOT `echo > .env` — that would wipe the file)
docker compose up -d emily ecoseek-api
```

## Manual setup (for development)

Use this if you need to edit source code across repos.

### 1. Clone all repositories

```bash
mkdir ecoseek-stack && cd ecoseek-stack

git clone https://github.com/alrobles/ecoseek.git
git clone https://github.com/alrobles/agenticSeek.git
git clone https://github.com/alrobles/ecoagent.git
git clone https://github.com/alrobles/ecocoder.git
git clone https://github.com/alrobles/knowledgebase.git   # read-only reference
```

### 2. Emily gateway (no host setup — Docker)

Emily runs inside the compose stack (build context `./emily`); there is no host-side installation or Node.js required.

> **AgenticPlug removed:** the legacy dockerized broker was removed from the stack on 2026-09-04 (no compose service, no published port). Do not start one for local development — the EcoSeek API routes chat to Emily directly.

### 3. Set up EcoAgent (ecological tool server)

```bash
cd ecoagent
pip install -e ".[dev]"
python -m ecoagent.tool_server --port 8100
```

### 4. Set up EcoCoder (inference endpoint)

```bash
cd ecocoder
pip install -e ".[dev]"
python -m ecocoder.api --port 8200
```

### 5. Set up the EcoSeek client

```bash
cd agenticSeek
python3 -m venv .venv
source .venv/bin/activate
sudo apt install portaudio19-dev python3-dev   # Linux only
pip install -r requirements.txt
python api.py
```

## Upstream tracking

EcoSeek's agenticSeek fork tracks upstream [Fosowl/agenticSeek](https://github.com/Fosowl/agenticSeek). See [upstream.md](upstream.md) for the sync strategy and TODO list.

## Running tests

Each component has its own test suite:

```bash
# AgenticSeek / EcoSeek client (72 P0 tests)
cd agenticSeek
python -m pytest tests/test_safety.py tests/test_keystore.py \
    tests/test_tool_save_block_jail.py tests/test_ecoseek_entrypoint.py -v

# EcoAgent
cd ecoagent
python -m pytest tests/ -v

# EcoCoder
cd ecocoder
python -m pytest tests/ -v
```

## Reporting setup issues

If something here is wrong, unclear, or unsafe, open an issue against this repository. Do not include logs that contain secrets; redact aggressively.
