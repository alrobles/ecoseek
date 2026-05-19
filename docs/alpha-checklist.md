# Alpha checklist

EcoSeek is pre-alpha. This checklist is the honest accounting of where things stand and the gate for the first public alpha. It is meant to be uncomfortable: nothing here is a marketing claim, and "mocked" and "unsafe" appear on purpose.

**Last updated:** 2026-05-18, after P0 stabilization (agenticSeek#33, agenticplug#74).

## What works

- The documentation shell in this repository.
- The high-level architecture (three layers: client, gateway, intelligence) is articulated, consistent across docs, and backed by [canonical architecture](https://github.com/alrobles/knowledgebase/blob/main/plans/ecoSeek/architecture.md) and 5 ADRs.
- The product modes (DIY / BYOK / Lab-managed) are defined.
- The relationship to upstream AgenticSeek is acknowledged, attributed, and license-aware.
- **AgenticPlug gateway is functional** — dual-layer auth (GitHub Device Flow → opaque session), role-based access control, scoped sessions, approval workflow for 6 risky capabilities, connector discovery API, persistent SQLite session store, rate limiting. 600+ tests across 26 suites.
- **DeepSeek BYOK provider** — Fernet-encrypted local keystore (`cryptography>=42`), OS keychain preferred with encrypted file fallback, fails closed without crypto library. 41 keystore tests.
- **EcoCoder local provider** — wraps Ollama with model validation and auto-resolution of generic model names to `ecocoder`.
- **EcoCoder cluster provider** — routes inference through AgenticPlug to remote clusters via OpenAI-compatible API.
- **EcoAgent tool server** — 30+ ecological tools exposed via HTTP (`/v1/tools`, `/v1/tools/{name}/execute`), discoverable by AgenticPlug connector manifest. Docker-packaged.
- **Security hardening** — path traversal jail on `save_block` (realpath + commonpath), remote symlink containment on HPC logs (readlink -f over SSH), safety.py unsafe command list fix, rate limiting, secret redaction in audit logs.
- **Landing page** — live at [ecoseek.org](https://ecoseek.org).
- **Full-stack threat model** — 24 scenarios, 12 assets, 6 actor profiles. See [security.md](./security.md).

## What is mocked or partial

- **End-to-end DIY demo.** Individual components work and are tested, but no single `docker-compose up` wires them all together yet.
- **EcoCoder authoring loop.** The runtime surfaces exist but the authoring scaffolding (write agent → run → inspect audit → iterate) is not yet pinned.
- **Knowledgebase wiring.** Not connected at runtime. Documentation references it as a read-only source.
- **Reproducibility hooks.** Designed, not implemented. Seeds, dataset pins, and environment captures do not yet land in any artifact.
- **Lab-managed mode.** Multi-user AgenticPlug sharing is a future target. Treat every install as single-user.

## What is unsafe or not production

- **No real secrets in this repo.** Do not configure EcoSeek with a real API key, OAuth token, or production credential against untested code paths.
- **No public exposure.** Do not expose AgenticPlug or EcoAgent on a public network without additional hardening. The auth model is tested but not independently audited.
- **No data handling guarantees.** Any data you give EcoSeek may end up in logs, working directories, or — if you misconfigure a substrate — in cloud calls you did not intend.
- **Client sandbox not independently audited.** The security review ([agenticSeek#28](https://github.com/alrobles/agenticSeek/pull/28)) identified 4 Critical + 4 High findings. P0 fixes landed in PR #33 (save_block jail, safety.py fix), but Python `exec()` in the code interpreter still runs with full builtins.
- **License is undecided.** See [`NOTICE.md`](../NOTICE.md). Until that is resolved, do not redistribute.

## Minimum alpha demo

The bar for calling something an "alpha" is a single end-to-end path that a reviewer can run and inspect:

1. A reviewer clones the relevant repos and runs EcoSeek in **DIY mode** with no real secrets.
2. EcoAgent loads a tiny EcoCoder-authored scientific agent.
3. The agent makes at least one call through AgenticPlug to a local model substrate.
4. AgenticPlug emits an audit log entry that names the actor, the requested action, the policy decision, and the timestamp — without leaking any inputs that look like secrets.
5. The reviewer can re-run the agent and get a deterministic-enough result to compare against the previous run.

If any of the five fails, it is not alpha yet.

## Before public alpha

Even after the minimum demo works internally, the following must be true before anything is published as a public alpha:

- [ ] Final license decision committed to the repository and reflected in `NOTICE.md`.
- [ ] All AgenticSeek-derived code in any EcoSeek component carries its GPLv3 headers and is identifiable.
- [x] ~~A written threat model in `security.md`.~~ Done — full-stack threat model with 24 scenarios across 5 layers. See [security.md](./security.md).
- [x] ~~A documented BYOK flow exercised with at least one provider.~~ Done — DeepSeek BYOK with Fernet keystore (agenticSeek PRs #23, #33). See [deepseek-byok.md](https://github.com/alrobles/agenticSeek/blob/main/docs/deepseek-byok.md).
- [ ] An audit log format that a second person, not the author, can read and reason about.
- [ ] A "how to report a security issue" contact published in `security.md`.
- [x] ~~A clear public statement that EcoSeek is not affiliated with or endorsed by AgenticSeek or DeepSeek.~~ Done — in README.md, NOTICE.md, UPSTREAM_CREDITS.md, and the landing page.
- [ ] At least one independent reviewer has run the minimum alpha demo and confirmed each step.

Until every box is checked, the project stays pre-alpha, regardless of how good the demo looks.
