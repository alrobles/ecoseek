# Security posture

EcoSeek is pre-alpha. This document describes the **current** security posture — what is implemented, what is tested, and what remains open. If a rule here conflicts with code in the repository, the rule wins and the code is a bug.

**Last updated:** 2026-05-18, after P0 stabilization.

For the complete threat model with 24 scenarios, 12 assets, 6 threat actor profiles, and risk matrix, see the [full-stack threat model](https://github.com/alrobles/knowledgebase/blob/main/plans/ecoSeek/threat-model.md) in the knowledgebase.

## No secrets in the repository

- No API keys, no tokens, no signed URLs, no private tunnel hostnames, no `.env` files with real values, no service-account JSON.
- This applies to commits, PR descriptions, issue comments, code comments, and docs.
- Use placeholders (`YOUR_DEEPSEEK_API_KEY`) and document the *shape* of a secret, never an example value that could be mistaken for a real one.
- If a secret is committed by accident, rotate it first, then remove it from history. Do not assume that deleting the file is sufficient.
- `alrobles/agenticSeek` has TruffleHog pre-commit scanning to catch secrets before they are committed.

## BYOK key rules

For users who supply their own keys (e.g. DeepSeek):

1. **Custody.** Keys are stored locally on the user's machine using Fernet encryption (AES-128-CBC + HMAC-SHA256). The keystore prefers the OS keychain (macOS Keychain, Linux Secret Service, Windows Credential Manager) and falls back to an encrypted file at `~/.config/ecoseek/keys.json`. Keys are never committed, logged, or transmitted to EcoSeek infrastructure.
2. **Fail-closed.** If the `cryptography` library is not installed, the keystore raises `KeystoreCryptoUnavailable` with an actionable error message. It never silently downgrades to base64 or plaintext storage.
3. **Scope.** A key is bound to the local keystore instance. It is not synced, backed up to a third party, or transmitted to any service other than the provider it targets.
4. **Lifecycle.** Keys can be managed via CLI: `python -m sources.keystore {set|get|list|delete}`. Revocation is immediate.
5. **Visibility.** The keystore can list which keys are stored without exposing key material.
6. **Lab-managed exception.** In lab-managed mode, the lab's operator holds the keys on behalf of users. Users still never see raw keys.

**Implementation:** [agenticSeek PR #23](https://github.com/alrobles/agenticSeek/pull/23), [agenticSeek PR #33](https://github.com/alrobles/agenticSeek/pull/33). 41 keystore tests.

## AgenticPlug auth model

> GitHub proves who the user is. AgenticPlug decides what the user can do.

### Dual-layer authentication

1. Client obtains a GitHub access token via Device Flow.
2. Client exchanges the GitHub token for an opaque AgenticPlug session ID.
3. AgenticPlug verifies the GitHub token against GitHub's API, maps the identity to a role (`admin`, `operator`, `read_only`), and issues a 128-bit crypto-random session ID.
4. All subsequent requests use only the session ID. Raw GitHub tokens are rejected as bearer tokens.

### Session security

- Sessions expire after a configurable TTL and can be revoked.
- Session IDs are never logged in full (redacted in audit output).
- Persistent SQLite store (WAL mode) survives broker restarts.
- Scoped sessions restrict access to specific connectors and capabilities; scopes are immutable per session.

### Role-based access control

- `admin`: full access including session management and approval decisions.
- `operator`: task execution and read access; cannot manage sessions.
- `read_only`: read-only access; cannot execute tasks or approve actions.
- Role is server-side only; client-side `X-Role` or body `role` fields are ignored.

### Approval workflow

Six capabilities are approval-gated: `hpc.submit`, `hpc.cancel`, `hpc.write`, `hpc.delete`, `hpc.credential`, `hpc.systemd`. The authorizer runs before the approval gate — `read_only` users get `forbidden` before any approval request is created. SHA-256 request binding prevents approving one action and executing another. Approvals expire after a configurable TTL (default 15 min).

**Implementation:** AgenticPlug PRs [#49](https://github.com/alrobles/agenticplug/pull/49), [#57](https://github.com/alrobles/agenticplug/pull/57), [#58](https://github.com/alrobles/agenticplug/pull/58), [#66](https://github.com/alrobles/agenticplug/pull/66), [#67](https://github.com/alrobles/agenticplug/pull/67), [#68](https://github.com/alrobles/agenticplug/pull/68), [#74](https://github.com/alrobles/agenticplug/pull/74). 600+ tests.

## Risky actions are gated

The following are considered risky and must go through the gateway:

- Any outbound network call.
- Any use of a stored secret (BYOK key, OAuth token, signed identity).
- Any filesystem write outside the agent's declared workspace.
- Any shell or process exec.
- Any action that can spend money, send a message, or otherwise affect a third party.

The gateway makes an explicit, auditable decision based on the caller, the requested action, and the active policy. "Allow all" is not a valid default — the gateway fails closed when no policy matches.

## Client-side security

### Path traversal protection

`Tool.save_block()` resolves all paths against the agent's `work_dir` using `os.path.realpath()` + `os.path.commonpath()`. Blocked: `../` traversal, absolute paths outside work_dir, symlink escapes. Re-validates after directory creation to close TOCTOU windows. Error messages omit host paths.

**Implementation:** [agenticSeek PR #33](https://github.com/alrobles/agenticSeek/pull/33). 12 jail tests.

### Unsafe command filtering

`safety.py` maintains allowlists/blocklists for shell commands. P0 fix corrected a missing comma that concatenated `"route"` and `"--force"` into a single entry, bypassing both filters.

**Implementation:** [agenticSeek PR #33](https://github.com/alrobles/agenticSeek/pull/33). 11 safety tests.

### Known client gaps

- Python `exec()` in the code interpreter runs with full `os`/`sys`/`__builtins__`. No process-level sandbox.
- `safe_mode` defaults to `False` — the safety filter is opt-in, not opt-out.
- See the [sandbox security review](https://github.com/alrobles/agenticSeek/blob/main/docs/sandbox-security-review.md) for full findings.

## HPC log containment

Three-layer defense for remote file access:

1. **Input validation:** 8 independent checks (length cap, null byte rejection, percent-decoding, segment-wise `..` check, absolute path, POSIX allowlist, `path.resolve`, local realpath).
2. **Remote symlink resolution:** `readlink -f` over SSH before `tail` catches remote symlinks escaping allowed roots. Fails closed on SSH failure, timeout, or non-POSIX output.
3. **Shell safety:** All SSH commands use `execFileSync` with argument arrays, not string concatenation.

`HPC_ALLOWED_LOG_PATHS` validated at startup; invalid entries (including `/`) prevent the connector from starting.

**Implementation:** AgenticPlug PRs [#69](https://github.com/alrobles/agenticplug/pull/69), [#74](https://github.com/alrobles/agenticplug/pull/74). 29 symlink tests + 86 HPC tests.

## Threat model summary

| Layer | Threats | Status |
|-------|---------|--------|
| Client | API key theft, raw token misuse, sandbox escape | Partial — keystore implemented, sandbox not fully hardened |
| Gateway | Unauth access, session hijack, role escalation, scope bypass, approval bypass, replay | Implemented and tested (600+ tests) |
| Compute | Path traversal, job injection, token leak, SSH credential exposure | Implemented with defense in depth |
| Infrastructure | Supply chain, GitHub OAuth, workstation compromise, SQLite corruption | Minimal deps, WAL mode, process controls |
| Human | Secrets in git, tokens in chat, misconfigured allowlists | Process controls, startup validation, TruffleHog |

For the complete catalog with mitigations, residual risk, and recommendations, see the [full-stack threat model](https://github.com/alrobles/knowledgebase/blob/main/plans/ecoSeek/threat-model.md).

## Reporting

EcoSeek does not yet have a dedicated public security contact. Until one is published here, report suspected issues by opening a **private** issue in the relevant repository, or contacting the maintainers directly through the channel they used to invite you to the project.
