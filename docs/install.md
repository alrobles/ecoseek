# Install

> **Status: pre-alpha.** This document describes how to install and run EcoSeek locally. **Do not use real production data with EcoSeek at this stage.**

**Last updated:** 2026-05-18

## Prerequisites

- **Git** (any recent version)
- **Docker** and **Docker Compose v2** (Docker Desktop on Windows/macOS, or docker-ce on Linux)
- **DeepSeek API key** — get one at https://platform.deepseek.com/api_keys

No Node.js, Python, or npm required on the host. Everything runs inside containers.

## Quick start (any OS)

Works identically on Linux, macOS, and Windows (WSL or native Docker Desktop).

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
DEEPSEEK_API_KEY=sk-your-key-here bash setup.sh
```

The script will:
1. Clone dependency repos (agenticplug, agenticSeek) using your git auth
2. Build all Docker images (~5-10 min first time, cached after)
3. Start the full stack (6 services)
4. Open `http://localhost:3000` in your browser to start working

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
| **AgenticSeek UI** | `http://localhost:3000` | Web interface — start here |
| AgenticSeek API | `http://localhost:7777` | Agent backend (API + task execution) |
| AgenticPlug broker | `http://localhost:3100` | Security gateway — auth, sessions, scopes |
| SearxNG | `http://localhost:8080` | Private web search for agents |
| Ollama | `http://localhost:11434` | Local model inference |
| Redis | (internal) | Task queue |

### Stop / restart / logs

```bash
docker compose down          # stop
docker compose up -d         # restart (detached)
docker compose logs -f       # follow logs
bash setup.sh                # rebuild after upstream changes
```

### Changing the API key

```bash
# Option 1: edit .env file
echo "DEEPSEEK_API_KEY=sk-new-key" > .env
docker compose up -d

# Option 2: re-run setup
DEEPSEEK_API_KEY=sk-new-key bash setup.sh
```

## Manual setup (for development)

Use this if you need to edit source code across repos.

### 1. Clone all repositories

```bash
mkdir ecoseek-stack && cd ecoseek-stack

git clone https://github.com/alrobles/ecoseek.git
git clone https://github.com/alrobles/agenticSeek.git
git clone https://github.com/alrobles/agenticplug.git
git clone https://github.com/alrobles/ecoagent.git
git clone https://github.com/alrobles/ecocoder.git
git clone https://github.com/alrobles/knowledgebase.git   # read-only reference
```

### 2. Set up AgenticPlug (gateway)

```bash
cd agenticplug
npm install
BROKER_SESSION_STORE=memory node broker/server.js
```

> **WSL users:** Make sure `which node` returns `/usr/bin/node` (Linux), not `/mnt/c/.../node.exe` (Windows). If it returns the Windows path, install Node.js inside WSL: `curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install -y nodejs`

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
# AgenticPlug (308 tests across 6 suites)
cd agenticplug
npm run test:scoped-sessions    # 52 tests
npm run test:remote-symlink     # 29 tests
npm run test:approval-workflow  # 32 tests
npm run test:mock-gateway-security  # 89 tests
npm run test:hpc                # 86 tests
npm run test:connector-discovery    # 20 tests

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
