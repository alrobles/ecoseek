# AgenticPlug session store

EcoSeek's gateway layer (AgenticPlug) manages authentication sessions after GitHub Device Flow completes. Sessions are identified by a 128-bit crypto-random opaque ID and can be stored in multiple backends depending on your deployment scenario.

**Last updated:** 2026-05-21, Phase 2 persistent session store.

## Session lifecycle

1. **Authentication:** User completes GitHub Device Flow and obtains a GitHub access token.
2. **Exchange:** Client sends the GitHub token to AgenticPlug's `/auth/exchange` endpoint.
3. **Verification:** AgenticPlug verifies the token with GitHub's API, extracts the user's identity, and maps it to a role (`admin`, `operator`, `read_only`).
4. **Issue:** AgenticPlug generates a 128-bit crypto-random session ID and stores it in the configured session store along with metadata (GitHub username, role, scopes, expiry).
5. **Subsequent requests:** All API calls to AgenticPlug use the opaque session ID as a bearer token. Raw GitHub tokens are rejected.

Sessions expire after a configurable TTL (default 24 hours) and can be revoked by an admin at any time.

## Storage backends

AgenticPlug supports three session store backends, configured via the `BROKER_SESSION_STORE` environment variable:

### `memory` — In-memory (ephemeral)

**Use case:** Development, automated tests, smoke demos.

**Characteristics:**
- Fastest performance (no disk I/O).
- Sessions lost when the broker process restarts.
- No setup required.
- **Not suitable for production or any scenario where users expect login state to persist across restarts.**

**Example:**
```bash
BROKER_SESSION_STORE=memory node broker/server.js
```

**When to use:**
- Running unit tests that mock authentication flows.
- Short-lived smoke tests where re-authentication after a restart is acceptable.
- Local development when you don't mind logging in again each time you restart the broker.

### `sqlite` — Local SQLite database (persistent, default for alpha)

**Use case:** Docker DIY mode, single-user alpha, local installations.

**Characteristics:**
- Persistent storage in a local SQLite file (default path: `/data/sessions.db`).
- WAL (Write-Ahead Logging) mode enabled for crash safety.
- Sessions survive broker restarts.
- Suitable for single-user or small-team deployments where the broker runs on a single host.
- No external dependencies (SQLite is embedded in Node.js via `better-sqlite3`).

**Docker volume mount:**
The default `docker-compose.yml` configuration mounts a named volume at `/data` in the broker container:

```yaml
volumes:
  - broker-data:/data
```

This ensures that the SQLite database file persists even if the container is recreated.

**Example:**
```bash
BROKER_SESSION_STORE=sqlite node broker/server.js
```

**When to use:**
- Docker DIY deployments where users expect login state to survive container restarts.
- Alpha/beta testing with a small number of users on a single host.
- Any scenario where you want persistent sessions without setting up an external database.

**Security notes:**
- The SQLite file contains session metadata (GitHub usernames, roles, scopes, expiry timestamps) but **no raw GitHub access tokens, PEM keys, or upstream connector secrets**. The broker never persists the GitHub token after verifying it during the exchange step.
- The session ID itself is opaque and useless without access to the session store. If an attacker gains read access to the SQLite file, they can see which users have active sessions but cannot impersonate them without also compromising the broker process.
- The SQLite file permissions should be `0600` (owner read/write only). The broker enforces this at startup and fails if the permissions are too permissive.

**Backup and recovery:**
To back up sessions, copy the SQLite file:
```bash
docker compose exec agenticplug sqlite3 /data/sessions.db ".backup /data/sessions-backup.db"
docker cp agenticplug:/data/sessions-backup.db ./sessions-backup.db
```

To restore:
```bash
docker cp ./sessions-backup.db agenticplug:/data/sessions.db
docker compose restart agenticplug
```

**Corruption handling:**
SQLite's WAL mode provides crash recovery. If the database becomes corrupted (rare but possible if the host's filesystem fails), the broker will:
1. Log a fatal error at startup.
2. Refuse to start until the issue is resolved.
3. Suggest deleting the corrupted file (which will force all users to re-authenticate).

The broker does not attempt automatic recovery by deleting the file, to avoid silently discarding sessions in case the corruption is recoverable.

### External store (future)

**Use case:** Multi-instance broker deployments, lab-managed mode, high availability.

**Characteristics:**
- Sessions stored in an external database (e.g., PostgreSQL, Redis) or distributed cache.
- Multiple broker instances can share the same session store.
- Requires additional infrastructure and configuration.

**Status:** Planned for a future release. The session store abstraction in AgenticPlug is designed to support pluggable backends, but only `memory` and `sqlite` are implemented as of Phase 2.

## Migration path

The recommended progression as your EcoSeek deployment evolves:

| Scenario | Recommended backend | Why |
|----------|---------------------|-----|
| **Initial smoke test** (5 min demo) | `memory` | Fastest, no setup, acceptable for throwaway sessions |
| **Docker DIY alpha** (single user, local) | `sqlite` (default) | Persistent, no external deps, survives restarts |
| **Lab-managed beta** (small team, shared host) | `sqlite` | Still acceptable for small teams with a single broker instance |
| **Production multi-user** (many users, HA) | External store (future) | Required for horizontal scaling and HA |

**Default for EcoSeek alpha:** `sqlite`. The setup script (`setup.sh`) generates a `.env` file with `BROKER_SESSION_STORE=sqlite` by default.

**Override for development:**
```bash
BROKER_SESSION_STORE=memory bash setup.sh
docker compose up -d
```

Or edit `.env` before running `docker compose up`.

## Session expiry and revocation

Sessions expire automatically after their TTL (default 24 hours). Expired sessions are:
- Rejected by the broker with a `401 Unauthorized` response.
- Cleaned up from the session store by a periodic garbage collection task (runs every 1 hour).

**After a restart:**
- `memory` store: all sessions lost, expired or not.
- `sqlite` store: only non-expired sessions remain; expired sessions are still rejected.

**Revocation (admin only):**
An admin can revoke a session before it expires:
```bash
curl -X DELETE http://127.0.0.1:8080/admin/sessions/{sessionId} \
  -H "Authorization: Bearer {adminSessionId}"
```

Revoked sessions are immediately removed from the store (both memory and SQLite) and rejected on subsequent requests.

**Security invariant:** A session that is expired or revoked before a broker restart remains expired/revoked after the restart. The broker never "resurrects" an invalid session.

## Testing

AgenticPlug includes 600+ tests across 26 suites, including extensive session-related tests:

**Scoped session tests (52 tests):**
```bash
npm run test:scoped-sessions
```
Covers session creation, scope enforcement, scope immutability, and isolation between sessions.

**Mock gateway security tests (89 tests):**
```bash
npm run test:mock-gateway-security
```
Covers authentication, authorization, role-based access control, session hijacking prevention, and token validation.

**Additional smoke tests in EcoSeek:**
See [`docs/smoke-test.md`](./smoke-test.md) for an end-to-end test that includes:
1. Authenticating via GitHub Device Flow.
2. Exchanging the token for a session ID.
3. Restarting the broker (with SQLite backend).
4. Verifying that the session is still valid.
5. Waiting for the session to expire and verifying rejection.

## Troubleshooting

**Problem:** Sessions are lost after a broker restart.

**Solution:** Verify that `BROKER_SESSION_STORE=sqlite` in your `.env` file and that the `broker-data` Docker volume is mounted. Check `docker compose config` to confirm the volume mount.

**Problem:** Broker fails to start with "SQLite file permissions too permissive".

**Solution:** The broker enforces `0600` permissions on the SQLite file. If the file is world-readable, the broker will refuse to start. Delete the file and let the broker recreate it, or run:
```bash
docker compose exec agenticplug chmod 600 /data/sessions.db
```

**Problem:** Broker fails to start with "SQLite database is corrupted".

**Solution:** This usually indicates a filesystem issue. Options:
1. Restore from a backup (see "Backup and recovery" above).
2. Delete the corrupted file (forces all users to re-authenticate):
   ```bash
   docker compose exec agenticplug rm /data/sessions.db
   docker compose restart agenticplug
   ```

**Problem:** I want to switch from SQLite back to memory for testing.

**Solution:** Edit `.env` and change `BROKER_SESSION_STORE=sqlite` to `BROKER_SESSION_STORE=memory`, then restart:
```bash
docker compose restart agenticplug
```

Existing sessions in the SQLite file are ignored (but not deleted) while the broker runs with the memory backend.

## References

- **Threat model:** [security.md](./security.md) — session hijacking, token theft, replay attacks.
- **AgenticPlug PRs:** [#49](https://github.com/alrobles/agenticplug/pull/49), [#57](https://github.com/alrobles/agenticplug/pull/57), [#58](https://github.com/alrobles/agenticplug/pull/58) — authentication foundation.
- **Alpha checklist:** [alpha-checklist.md](./alpha-checklist.md) — persistent SQLite session store status.
