# Remote Mode — Thin Client for EcoSeek PoC

Run EcoSeek as a **thin local client** that connects to a remote AgenticPlug
broker and Hermes backend. No local EcoAgent, Ollama, SearxNG, or Redis
required.

## Architecture

```
Laptop
  ecoseek-client (CLI)
      │
      │  Authorization: Bearer <session_id>
      ▼
AgenticPlug broker (remote, e.g. reumanlab)
      │
      │  /v1/orchestrate → Hermes forwarding
      ▼
Hermes (remote on reumanlab)
      │
      ▼
cluster / EcoAgent / execution backends (later)
```

## Quick Start (CLI only — recommended)

The simplest path: install `ecoseek-client` and use the CLI directly.

```bash
# 1. Install
cd ecoseek-client
pip install -e .

# 2. Login with GitHub
ecoseek login --broker https://your-agenticplug-url

# 3. Verify identity
ecoseek agenticplug me

# 4. Use Hermes
ecoseek hermes orchestrate "Run SDM for monarch butterfly in Mexico"
ecoseek hermes chat "What ecological tools are available?"
```

## Quick Start (Docker remote profile)

If you prefer running the EcoSeek API locally in a container:

```bash
# 1. Configure
cp .env.remote.example .env
# Edit .env — set AGENTICPLUG_URL to your remote broker

# 2. Start (only ecoseek-api, no heavy dependencies)
docker compose --profile remote up

# 3. The API is at http://127.0.0.1:3000
```

## What Starts in Remote Mode

| Service | Remote profile | Full stack (default) |
|---------|---------------|---------------------|
| ecoseek-api | ✓ | ✓ |
| AgenticPlug | ✗ (remote) | ✓ (local container) |
| EcoAgent | ✗ | ✓ |
| Ollama | ✗ | ✓ |
| SearxNG | ✗ | ✓ |
| Redis | ✗ | ✓ |

## Configuration

### Required

| Variable | Description |
|----------|-------------|
| `AGENTICPLUG_URL` | URL of the remote AgenticPlug broker |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_ENABLED` | `true` | Enable Hermes forwarding (via broker) |
| `ECOSEEK_API_PORT` | `3000` | Local API port |
| `UPSTREAM_TIMEOUT_S` | `120` | Timeout for upstream requests |
| `LOCAL_LLM_URL` | — | Optional local LLM fallback |
| `PHOENIX_ENABLED` | `false` | Enable Phoenix tracing |

## Session Management

Sessions are stored at `~/.config/agenticplug/session.json` (v2 format).

```bash
ecoseek login                  # GitHub OAuth → saves session
ecoseek agenticplug me         # Verify authenticated identity
ecoseek logout                 # Delete session + notify broker
```

The session file contains a bearer token. It is created with `0600` permissions
(owner-only read/write). The token is sent as `Authorization: Bearer <id>` on
each request to the broker.

## Troubleshooting

### "No session token found"
Run `ecoseek login --broker <url>` to authenticate.

### "Connection refused"
Verify `AGENTICPLUG_URL` points to a reachable broker. Test with:
```bash
curl -s https://your-broker-url/healthz | jq .
```

### "503 hermes_disabled"
The broker has `HERMES_ENABLED=false`. Ask the broker admin to set
`HERMES_ENABLED=true`, `HERMES_URL`, and `HERMES_API_KEY`.
