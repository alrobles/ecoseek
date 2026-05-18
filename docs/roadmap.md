# Roadmap

EcoSeek is pre-alpha. This roadmap is intentionally short and split into **Done / Now / Next / Later**. Items move up the list as they stabilize; nothing here is a commitment to a date.

**Last updated:** 2026-05-18, after P0 stabilization.

## Done

The following milestones have been completed:

- **Phase 0:** Verify merged PRs and baseline tests.
- **Phase 1:** Product identity — EcoSeek positioning, upstream credits, licensing audit, canonical architecture and ADR set (5 ADRs).
- **Phase 2:** AgenticPlug production hardening — connector discovery API, scoped sessions, persistent SQLite session store, approval workflow (6 gated capabilities), remote symlink containment, HPC log path docs, full-stack threat model.
- **Phase 3:** EcoSeek providers — DeepSeek BYOK with Fernet keystore, EcoCoder local provider (Ollama), EcoCoder cluster provider (AgenticPlug), connector discovery + tool registration, install docs, sandbox security review.
- **Phase 4:** EcoCoder/EcoAgent backends — OpenAI-compatible inference endpoint, model card + release checklist, EcoAgent tool plugin HTTP server, Docker packaging.
- **Phase 5:** Public landing page at [alrobles.github.io/ecoseek.html](https://alrobles.github.io/ecoseek.html).
- **P0 Stabilization:** agenticSeek PR #33 (safety.py comma fix, Fernet keystore fail-closed, save_block realpath jail, ecoseek entry point) and agenticplug PR #74 (scope enforcement on all routes, TOCTOU fix on approval execution, 502 vs 403 distinction for HPC logs). 380 tests pass on main, 0 regressions.

## Now

The current focus is **migration and integration**: making the `alrobles/ecoseek` repo the coherent entry point that ties together the companion repos.

- Update ecoseek docs to reflect actual state (this roadmap, alpha checklist, security posture, install guide).
- Wire a DIY-mode `docker-compose.yml` that starts AgenticPlug + EcoAgent + a local model substrate.
- Resolve the remaining pre-alpha gates (see [alpha-checklist.md](./alpha-checklist.md)).

## Next

Once the integration layer is in place, the next phase is the **minimum alpha demo** — one end-to-end path a reviewer can run and inspect:

- EcoAgent runs a tiny scientific agent against a local model, brokered by AgenticPlug, with full audit log.
- EcoCoder authoring loop: write an agent, run it locally, see the audit trail, iterate.
- License decision and GPLv3 header audit.
- Security contact published.
- Independent reviewer runs the alpha demo.

## Later

The later bucket is everything that depends on the first end-to-end path existing. Order is not fixed.

- Lab-managed mode: multi-user AgenticPlug, shared keys, per-user audit.
- A second BYOK provider beyond DeepSeek, chosen by what users actually ask for.
- Reproducibility packaging: a one-command "run this agent again with the same inputs and pins" flow.
- Public alpha, with a documented threat model and a clear "what is and is not safe to do with this" page.
- Optional outreach to the upstream AgenticSeek project; until then, no claim of affiliation.

## Non-goals (for now)

- A hosted EcoSeek SaaS. EcoSeek is self-hosted first.
- Replacing AgenticSeek. EcoSeek is a downstream scientific adaptation, not a competing fork.
- Frontier model training. EcoSeek consumes models; it does not train them.
