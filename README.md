# EcoSeek

**EcoSeek** is an independent, downstream scientific adaptation built on top of a fork of [AgenticSeek](https://github.com/Fosowl/agenticSeek). It is the final product direction for a community- and lab-oriented agentic assistant focused on scientific workflows, reproducibility, and safe local-first operation.

EcoSeek is built on a fork of AgenticSeek. We gratefully acknowledge the AgenticSeek project and contributors as the foundation for this work. EcoSeek is an independent downstream adaptation focused on scientific and ecological computing. See [`UPSTREAM_CREDITS.md`](./UPSTREAM_CREDITS.md) for detailed acknowledgements and license obligations.

EcoSeek is **not** an official AgenticSeek release. It is **not affiliated with**, **not endorsed by**, and **not maintained by** the AgenticSeek project or its contributors unless and until such a relationship is publicly established.

---

## Current state

EcoSeek is **pre-alpha** — components work individually and are tested, but the end-to-end demo is not yet wired. See [alpha-checklist.md](./docs/alpha-checklist.md) for what works, what is mocked, and the gate for the first public alpha.

### What is working

| Component | Status | Tests |
|-----------|--------|-------|
| [AgenticPlug gateway](https://github.com/alrobles/agenticplug) | Functional — auth, sessions, scopes, approvals, discovery, audit | 600+ |
| [EcoSeek client](https://github.com/alrobles/ecoseek-client) | Functional — providers, keystore, safety, entry point | 72 P0 + others |
| [EcoAgent tools](https://github.com/alrobles/ecoagent) | Functional — 30+ ecological tools via HTTP server | Unit + integration |
| [EcoCoder inference](https://github.com/alrobles/ecocoder) | Functional — OpenAI-compatible endpoint | Unit tests |
| EcoSeek API gateway (`backend/`) | Alpha — health + `/v1/query` with Hermes/AgenticPlug/local routing + OpenTelemetry tracing (Phoenix opt-in) | — |
| [Landing page](https://ecoseek.org) | Live | — |
| [Threat model](./docs/security.md) | Complete — 24 scenarios, 12 assets, 6 actor profiles | — |

### Security highlights

- **Dual-layer auth:** GitHub identity → opaque session. Raw GitHub tokens rejected as bearer.
- **BYOK keystore:** Fernet-encrypted (AES-128-CBC + HMAC-SHA256). Fails closed without `cryptography`.
- **Approval workflow:** 6 risky capabilities gated. SHA-256 request binding. TOCTOU-safe.
- **Path traversal jail:** `save_block` uses realpath + commonpath. Blocks `../`, absolute escapes, symlinks.
- **HPC log containment:** 3-layer defense (input validation → remote symlink resolution → shell safety).
- **600+ security-focused tests** across all components.

---

## Product modes

EcoSeek supports three deployment modes:

1. **DIY** — self-hosted, fully local, no external accounts. The default for privacy-sensitive users and offline labs.
2. **BYOK** — self-hosted with user-provided API keys for cloud models (e.g. DeepSeek). Keys stored in Fernet-encrypted local keystore; never leave the user's machine.
3. **Lab-managed** — a research group operates a shared AgenticPlug for its members. Members do not handle keys directly.

---

## Quick start

Only **Git** and **Docker** are required. No Node.js, Python, or npm needed on the host.

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
bash setup.sh          # Linux / macOS / WSL
# .\setup.ps1          # Windows PowerShell (native Docker Desktop)
```

Or manually: `docker compose up --build`

First build takes 2-5 minutes (clones repos inside containers). See [docs/install.md](./docs/install.md) for the full guide, manual setup, and BYOK configuration.

---

## Documentation

- [Architecture](./docs/architecture.md) — three-layer design, product modes, cross-cutting principles
- [Security posture](./docs/security.md) — threat model summary, auth model, BYOK rules, containment
- [Alpha checklist](./docs/alpha-checklist.md) — what works, what is mocked, pre-alpha gates
- [Roadmap](./docs/roadmap.md) — Done / Now / Next / Later
- [Install guide](./docs/install.md) — prerequisites, quick start, running tests
- [Local DIY smoke test](./docs/smoke-test.md) — canonical Phase 2 smoke command (issue #15)
- [LACS Pipeline](./docs/lacs-pipeline.md) — PubMed ecology classifier (PU-learning, 36M abstracts)
- [Remote smoke (Phase 3 scaffold)](./docs/remote-smoke.md) — reumanlab / KU-HPC remote path verifier (issue #22)
- [Full threat model](https://github.com/alrobles/knowledgebase/blob/main/plans/ecoSeek/threat-model.md) — 24 scenarios, risk matrix, incident response

---

## Related repositories

| Repository | Role |
|-----------|------|
| [`alrobles/agenticSeek`](https://github.com/alrobles/agenticSeek) | Legacy fork — agent runtime (being replaced by ecoseek-client) |
| [`alrobles/ecoseek-client`](https://github.com/alrobles/ecoseek-client) | EcoSeek Python client — providers, keystore, safety, CLI |
| [`alrobles/agenticplug`](https://github.com/alrobles/agenticplug) | Secure gateway — auth, sessions, policy, approvals, audit |
| [`alrobles/ecocoder`](https://github.com/alrobles/ecocoder) | Domain-specialized ecological/code LLM path |
| [`alrobles/ecoagent`](https://github.com/alrobles/ecoagent) | Scientific workflow and tool layer (30+ ecological tools) |
| [`alrobles/knowledgebase`](https://github.com/alrobles/knowledgebase) | Architecture, security docs, planning source of truth |
| [`alrobles/alrobles.github.io`](https://github.com/alrobles/alrobles.github.io) | Author portfolio (redirects to ecoseek.org) |

---

## Hermes

[Hermes](https://hermes.ecoseek.org) is the optional remote orchestration service for EcoSeek. When enabled, the EcoSeek API gateway routes queries through AgenticPlug's `/v1/orchestrate` endpoint, which forwards them to Hermes for advanced scientific reasoning.

**How to enable Hermes:**

1. Set the following env vars in `.env` (generated by `setup.sh`):
   ```
   HERMES_ENABLED=true
   HERMES_URL=https://hermes.ecoseek.org
   HERMES_API_KEY=<your-key>
   ```
2. Restart: `docker compose up -d`
3. Verify: `curl -s http://127.0.0.1:3000/v1/query -X POST -H 'Content-Type: application/json' -d '{"text":"hello","mode":"hermes"}'`

When `HERMES_ENABLED=false` (the default), the gateway falls back to AgenticPlug chat completions and then the local LLM. Hermes is fail-closed — the stack works without it.

**Env vars summary:**

| Variable | Default | Description |
|---|---|---|
| `HERMES_ENABLED` | `false` | Enable Hermes routing |
| `HERMES_URL` | _(empty)_ | Hermes service URL |
| `HERMES_API_KEY` | _(empty)_ | Bearer token for Hermes |
| `AGENTICPLUG_URL` | `http://agenticplug:8080` | AgenticPlug internal URL |
| `UPSTREAM_TIMEOUT_S` | `30` | Upstream request timeout (seconds) |
| `LOCAL_LLM_URL` | _(empty)_ | OpenAI-compatible local LLM URL (e.g. Ollama) |
| `LOCAL_LLM_API_KEY` | _(empty)_ | Bearer token for local LLM |
| `PHOENIX_ENABLED` | `false` | Enable OpenTelemetry tracing to Phoenix |
| `PHOENIX_ENDPOINT` | `http://phoenix:6006/v1/traces` | OTLP collector endpoint |
| `PHOENIX_PROJECT_NAME` | `ecoseek` | Project name in Phoenix UI |

---

## License

The final license for EcoSeek is **not yet decided**. See [`NOTICE.md`](./NOTICE.md) for the current placeholder and the constraints that any final choice must respect (in particular, GPLv3 attribution obligations flowing from AgenticSeek-derived components).

Until a license is committed to this repository, treat the contents as **"all rights reserved, source-available for review and discussion only"** — but note that any AgenticSeek-derived code that lands here in the future will need to comply with the upstream GPLv3 terms.

---

## Disclaimer

EcoSeek is an independent project. It is not an official AgenticSeek product, not affiliated with the AgenticSeek maintainers, and not endorsed by them. Bugs, security issues, and design decisions in EcoSeek are the responsibility of the EcoSeek maintainers, not the upstream project.
