# Install

> **Status: pre-alpha.** EcoSeek is not yet a single installable product. This document describes how to set up the companion components for local development and review. **Do not use real secrets, real API keys, or real production data with EcoSeek at this stage.**

**Last updated:** 2026-05-18, after P0 stabilization.

## Prerequisites

- **Git** (any recent version)
- **Python 3.10+** with pip
- **Node.js 18+** with npm
- **Docker** and **Docker Compose** (optional, for containerized setup)
- **Ollama** (optional, for local model inference)

## Quick start (DIY mode)

### 1. Clone the repositories

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
# Start the broker in local-only mode (no real secrets)
BROKER_SESSION_STORE=memory node broker/server.js
```

The broker starts on `http://localhost:3000` by default. No external accounts are needed for local-only mode.

### 3. Set up EcoAgent (ecological tool server)

```bash
cd ecoagent
pip install -e ".[dev]"
# Start the tool server
python -m ecoagent.tool_server --port 8100
```

The tool server exposes `/v1/tools` and `/v1/tools/{name}/execute` for AgenticPlug connector discovery.

### 4. Set up EcoCoder (inference endpoint)

```bash
cd ecocoder
pip install -e ".[dev]"
# Start the OpenAI-compatible endpoint (requires Ollama running with a model)
python -m ecocoder.api --port 8200
```

### 5. Set up the EcoSeek client

```bash
cd agenticSeek
pip install -r requirements.txt
# Verify the entry point works
python -m sources.ecoseek_entrypoint --version
```

### 6. Run with Docker Compose (alternative)

From the `ecoseek` repo root:

```bash
docker compose up
```

This starts AgenticPlug (broker), EcoAgent (tool server), and an Ollama instance. See [`docker-compose.yml`](../docker-compose.yml) for configuration.

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
