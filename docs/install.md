# Install

> **Status: pre-alpha.** EcoSeek is not yet a single installable product. This document describes how to set up the companion components for local development and review. **Do not use real secrets, real API keys, or real production data with EcoSeek at this stage.**

**Last updated:** 2026-05-18, after P0 stabilization.

## Prerequisites

**Docker path (recommended — works on any OS):**

- **Git** (any recent version)
- **Docker** and **Docker Compose v2** (Docker Desktop on Windows/macOS, or docker-ce on Linux)

No Node.js, Python, or npm required on the host. Everything runs inside containers.

**Manual path (for development):**

- **Git** (any recent version)
- **Python 3.10+** with pip
- **Node.js 18+** with npm (**must be the Linux version inside WSL**, not the Windows one)
- **Ollama** (optional, for local model inference)

## Quick start — Docker (any OS)

This is the recommended path. Works identically on Linux, macOS, and Windows (WSL or native Docker Desktop).

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
bash setup.sh
```

Or manually:

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
git clone --depth 1 https://github.com/alrobles/agenticplug.git .repos/agenticplug
docker compose up --build
```

The setup script clones dependency repos into `.repos/` using your existing git auth (works with private repos), then Docker builds from those local checkouts. First build takes 2-5 minutes. Subsequent runs use cached images.

### Using `gh` CLI (WSL / Windows)

```bash
gh repo clone alrobles/ecoseek
cd ecoseek
bash setup.sh
```

### What starts

| Service | URL | What it does |
|---------|-----|-------------|
| AgenticPlug broker | `http://localhost:3000` | Gateway — auth, sessions, scopes, approvals |
| Ollama | `http://localhost:11434` | Local model inference |

The EcoSeek client (agenticSeek) runs directly on the host — see "Manual setup" below.

### Stop / restart / logs

```bash
docker compose down          # stop
docker compose up -d         # restart (detached)
docker compose logs -f       # follow logs
docker compose up --build    # rebuild after upstream changes
```

## Quick start — manual (for development)

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
pip install -r requirements.txt
python -m sources.ecoseek_entrypoint --version
```

## What you can do today

- Run AgenticPlug with the mock gateway and verify dual-layer auth, session management, and scope enforcement.
- Run EcoAgent's 30+ ecological tools via the HTTP server.
- Run EcoCoder's OpenAI-compatible endpoint against a local Ollama model.
- Run the EcoSeek client with local providers (DIY mode).
- Use the DeepSeek BYOK provider with your own API key stored in the Fernet-encrypted keystore.

## What you should not do today

- Connect EcoSeek to a shared lab AgenticPlug in production.
- Use EcoSeek to handle data you would not be comfortable losing or leaking.
- Expose any EcoSeek component on a public network without additional hardening.

## BYOK setup (DeepSeek)

The BYOK provider is functional. Keys are stored locally using Fernet encryption.

```bash
cd agenticSeek
# Store your API key (encrypted locally, never transmitted to EcoSeek infra)
python -m sources.keystore set deepseek_api_key
# Verify it's stored
python -m sources.keystore list
```

See [deepseek-byok.md](https://github.com/alrobles/agenticSeek/blob/main/docs/deepseek-byok.md) for the full guide.

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
