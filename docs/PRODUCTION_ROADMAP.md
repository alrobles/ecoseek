# EcoSeek Production Roadmap — DIY Self-Hosting

> **Status:** active · **Owner:** Angel Robles · **Last updated:** 2026-09-04
>
> Companion architecture docs: `docs/architecture.md`, `docs/install.md`,
> `docs/smoke-test.md`. Private planning copies live in the knowledgebase
> (`plans/ecoSeek/PRODUCTION_ROADMAP.md`).

## Why this roadmap exists

EcoSeek is sold as a **self-hosted, Docker-based product**: a scientist clones
`alrobles/ecoseek`, runs `bash setup.sh && docker compose up -d`, and gets a
local ecological AI assistant (Emily) with scientific tools (EcoAgent), a
private search engine (SearxNG), a local model backend (Ollama), and an API
gateway.

Today that promise is **not yet true**. The only production deployment (reumanlab)
never ran the repo's compose file, the tooling (`setup.sh`, `smoke.sh`,
`frontend-start.sh`, `docs/install.md`) still describes a broker service that was
removed on 2026-09-04, the Emily gateway denies all chat traffic out of the box,
and **no one has ever done the customer test: clone → setup → up → chat works**.

This roadmap closes that gap in three phases. Each phase has a concrete
**product** (what the user gets) and **Definition of Done checks** (how we prove
it without lying).

---

## Phase F0 — Tooling Sync (debt from the broker removal)

**Why:** On 2026-09-04 the legacy dockerized AgenticPlug broker was removed from
`docker-compose.yml` (superseded by the systemd broker on :9092). The installer,
smoke script, frontend starter, and install docs still assume it exists (clone
`.repos/agenticplug`, write `AGENTICPLUG_PORT`/`BROKER_SESSION_STORE`, tell users
to `curl http://127.0.0.1:8080/healthz` — a port that no longer exists). A new
customer following the docs would hit dead instructions on day one.

**Product:** The onboarding surface (installer + smoke + docs) describes exactly
the stack that `docker compose up -d` actually starts, and nothing else.

**Changes:**
| File | Change |
|---|---|
| `scripts/setup.sh` | Stop cloning `.repos/agenticplug`; drop `AGENTICPLUG_PORT`, `BROKER_SESSION_STORE`, `AGENTICPLUG_ALLOWED_LOGINS`, `AGENTICPLUG_SESSION`, `HERMES_*` broker-oriented vars from the generated `.env`; fix "Next steps" and the service table (no `:8080/healthz`). |
| `scripts/smoke.sh` | Rewrite the canonical smoke to prove the real product path: Emily `/health` → EcoSeek API `/` → EcoAgent `/v1/tools` → a chat completion through the API gateway (Ollama local or DeepSeek BYOK). No broker steps. |
| `frontend-start.sh` | Remove broker/8080 assumptions; default `REACT_APP_BROKER_URL` is no longer the broker — chat goes Emit through nginx to Emily directly. |
| `docs/install.md` | Update the "What starts" table (no AgenticPlug row), LLM routing section, and next steps to match the no-broker stack. |

**Definition of Done (checks):**
1. `grep -rn "agenticplug" scripts/ docs/ frontend-start.sh setup.sh` → only
   historical/removal notes, zero functional references.
2. `bash setup.sh CI=1` on a machine without `.repos/` exits 0, writes `.env`
   with **no** `AGENTICPLUG_*` keys, and does not clone `agenticplug`.
3. `bash scripts/smoke.sh` against a running stack passes its steps without
   touching `:8080` or `agenticplug`.
4. `docs/install.md` service table matches `docker compose config --services`.
5. CI (GitHub Actions) still green: lint + build + compose-smoke.

---

## Phase F1 — Minimum Viable Product on a Fresh System

**Why:** With the tooling honest again, the stack itself must actually work for
a first-time customer. Today it does not:
1. **Chat is 403 by default** — the Hermes gateway denies all users unless
   `GATEWAY_ALLOW_ALL_USERS=true` (or an allowlist) is set. The repo has zero
   occurrences of it. The documented fix (skill `ecoseek-deployment`) never made
   it into the product.
2. **Frontend build aborts** — `frontend/Dockerfile` requires the
   `EMILY_HERMES_KEY` build-arg (hard abort if empty), but the compose service
   passes it only as a runtime env → `docker compose --profile frontend up --build`
   dies at build. And the default stack has **no web UI at all** (frontend is
   profile-gated).
3. **Literature tab born broken** — `MEILI_ENABLED=true` by default but Meilisearch
   is not in the compose → `/v1/smart-search` fails on a fresh install.
4. **Host-specific mount hardcoded** — `r-workspace` mounts
   `/media/reumanlab/TOSHIBA_EXT` (an internal USB drive) in the public compose.
5. **`.env.example` promised but missing** — compose header and install docs say
   `cp .env.example .env`, the file does not exist.

**Product:** On a fresh machine (Linux/macOS/WSL), a customer can go from
`git clone` to a **working chat + tools + web UI** in one documented flow, with
the literature search optionally enabled and no host-specific paths required.

**Changes:**
| File | Change |
|---|---|
| `docker-compose.yml` | Pass `EMILY_HERMES_KEY` as a build-arg to `ecoseek-frontend`; remove the now-redundant runtime `command` envsubst. Add `GATEWAY_ALLOW_ALL_USERS` env (default `true`, overridable) to `emily`. Default `MEILI_ENABLED=false`. Make the `r-workspace` TOSHIBA mount conditional/commented. Optionally gate `meilisearch` service behind a `search` profile. |
| `emily/entrypoint.sh` | Write `GATEWAY_ALLOW_ALL_USERS` to `~/.hermes/.env` when provided so the setting survives container restarts. |
| `emily/config.yaml` | Document/allow the setting. |
| `frontend/Dockerfile` | Keep the hard abort but ensure the compose actually supplies the arg (or relax to a clear runtime check). |
| `.env.example` | **Create it** (mirror of what `setup.sh` generates) so the documented `cp .env.example .env` works. |
| `setup.sh` | Emit `GATEWAY_ALLOW_ALL_USERS=true`, `MEILI_ENABLED=false`, and document the `search` profile + `EMILY_HERMES_KEY` for the frontend. |

**Definition of Done (checks):**
1. Fresh clone → `cp .env.example .env` (or `bash setup.sh CI=1`) → `docker compose up -d`
   → `docker compose ps` all core services **healthy**.
2. `curl http://127.0.0.1:3000/` → 200 status ok; chat completion through the
   gateway returns 200 with non-empty content (no 403) against Ollama, DeepSeek
   BYOK, or remote Hermes.
3. `docker compose --profile frontend up --build` completes the build (no
   `EMILY_HERMES_KEY` abort) and the UI loads at `http://127.0.0.1:4000`.
4. Literature tab: with `MEILI_ENABLED=false` it degrades gracefully; with the
   `search` profile + Meilisearch it works.
5. `docker compose config` contains **no** reference to `/media/reumanlab/...`.
6. `setup.sh` output contains `GATEWAY_ALLOW_ALL_USERS`, `MEILI_ENABLED`.
7. CI green.

---

## Phase F2 — The Customer Test (fresh-machine deployment)

**Why:** F0+F1 make the repo *look* right; F2 makes it *proven*. The single most
valuable test is deploying ecoSeek on a clean machine of the mesh
(`reumanlab-terminal`, or a fresh VM/container) **following the published docs
literally** — the exact experience of a paying customer.

**Product:** A documented, reproducible deployment on a machine that never ran
ecoSeek, with the smoke script green, and a written runbook
(`docs/fresh-install-runbook.md`) capturing every deviation found.

**Definition of Done (checks):**
1. `reumanlab-terminal` (or equivalent clean target) has git + Docker only.
2. Customer path executed with **no undocumented steps**: clone → `.env` →
   `docker compose up -d --build` → services healthy.
3. `bash scripts/smoke.sh` passes in full (API + chat + tools).
4. Frontend profile builds and serves the UI; chat round-trips through nginx.
5. Every fix made during the test is committed back (the runbook documents them).
6. Time-to-value (clone → working chat) recorded in the runbook.

---

## Backlog (after F2)

- **I1 — Meilisearch as a first-class optional service** (`search` profile with
  volume + seed docs) so literature search is a documented toggle, not a footnote.
- **I2 — BYOK hardening**: per-service key files via `*_FILE` env (issue #99
  pattern), documented in `setup.sh`.
- **I3 — GPU profile validation** (`--profile gpu` on a fresh NVIDIA machine,
  Ollama passthrough verified).
- **I4 — Multi-machine mesh doc**: how two ecoSeek instances talk (DiDAL remote,
  task delegation) without exposing services.
- **I5 — Release packaging**: tagged images on GHCR so customers can
  `docker compose pull` instead of building from source.

---

## Guiding rules

1. **Production evidence > prose.** Every phase's DoD is a command someone can
   run. No phase is "done" on description alone.
2. **The repo IS the product.** Production state must live in `alrobles/ecoseek`
   (public), not in `/opt` or a machine's compose dir. Anything that only works on
   reumanlab is tech debt, not a feature.
3. **No dead references.** If a service is removed, the tooling that mentions it
   is removed in the same release.
4. **Secrets stay out of chat, logs, and the repo.** Keys flow via `_FILE` or
   `.env` (0600), never committed.