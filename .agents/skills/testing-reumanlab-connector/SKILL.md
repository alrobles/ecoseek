---
name: testing-reumanlab-connector
description: Test the reumanlab connector runtime end-to-end. Use when verifying connector changes, security invariants, or capability dispatch.
---

# Testing the reumanlab Connector

The connector is a zero-dependency Node.js HTTP server at `connector/reumanlab/`.

## Prerequisites

- Node.js >= 18
- No npm install needed (stdlib only)

## Unit Tests

```bash
cd /path/to/ecoseek
node test/reumanlab-connector.test.js
```

Expected: 47 passed, 0 failed. Tests cover config validation, sanitization, capability dispatch (all 6 read + 4 write-disabled), path validation, timeout handling, audit events, and HTTP integration. All tests use mocks — no SSH or HPC access needed.

## Local E2E Testing

Start the server with test config (pick an unused port):

```bash
HPC_USER=testuser HPC_HOST=test.example.edu CONNECTOR_TOKEN=test-secret-42 \
  CONNECTOR_PORT=9877 HPC_ALLOWED_LOG_PATHS=/tmp/test-logs \
  node connector/reumanlab/main.js &
```

Verify startup log contains `"event":"connector_started"` on stdout.

### Key curl checks

```bash
TOKEN="test-secret-42"
BASE="http://127.0.0.1:9877"

# Healthz (unauthenticated)
curl -s $BASE/healthz
# Expected: {"status":"ok","connector_id":"reumanlab"}

# Auth enforcement
curl -s -w '%{http_code}' -X POST $BASE/v1/capabilities \
  -H 'Content-Type: application/json' \
  -d '{"capability":"remote.health"}'
# Expected: 401

# Allowed capability
curl -s -X POST $BASE/v1/capabilities \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"capability":"remote.health","payload":{}}'
# Expected: 200 with status, connector_id, version, uptime_seconds

# Write cap rejection
curl -s -w '%{http_code}' -X POST $BASE/v1/capabilities \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"capability":"hpc.submit","payload":{}}'
# Expected: 501 capability_disabled

# Path traversal
curl -s -X POST $BASE/v1/capabilities \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"capability":"hpc.logs.read","payload":{"path":"/tmp/test-logs/../../etc/shadow"}}'
# Expected: 400 path_traversal

# Unknown capability
curl -s -X POST $BASE/v1/capabilities \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"capability":"arbitrary.shell.exec","payload":{"cmd":"whoami"}}'
# Expected: 400 invalid_payload
```

### Audit log verification

Check the server stdout — every capability invocation emits a JSON line with:
`event`, `timestamp`, `connector_id`, `capability`, `result_status`, `duration_ms`.
Error events also include `error_code` and `error_message`.

## What Requires Real Deployment

The SSH-based capabilities (`hpc.status`, `hpc.queue`, `hpc.logs.read`, `remote.list_home`) require real SSH connectivity to KU-HPC. These can only be tested after deploying to reumanlab following `docs/reumanlab-connector-deploy.md`.

## Known Gotchas

- Port 9876 may be occupied by the Devin remote process. Use 9877 or another free port.
- The fail-closed test (starting without env vars) exits immediately — use `timeout 5 node main.js 2>&1` to capture stderr.
- `remote.info` should always show `[REDACTED]` for `node_name`, `hpc_user`, `hpc_host` — if real values appear, the redaction is broken.
- The connector binds to 127.0.0.1 by default. Don't change this to 0.0.0.0 for testing.

## Devin Secrets Needed

None for local testing. For live reumanlab deployment testing:
- `OPENCLAW_API_KEY` — to send commands to reumanlab via OpenClaw
- `OPENCLAW_BASE_URL` — Cloudflare tunnel URL to reumanlab
