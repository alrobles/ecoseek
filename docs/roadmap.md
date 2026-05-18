# Roadmap

EcoSeek is pre-alpha. This roadmap is intentionally short and split into **Now / Next / Later**. Items move up the list as they stabilize; nothing here is a commitment to a date.

## Now

The current focus is making EcoSeek *legible*: a clean shell that explains what the product is, how it relates to AgenticSeek, and how the pieces fit together.

- Documentation shell (this repository) — README, NOTICE, UPSTREAM_CREDITS, architecture, security posture, install stub, alpha checklist.
- AgenticPlug gateway: minimal local-only mode that can broker calls between EcoAgent and a local model substrate, with no real secrets in play.
- EcoCoder: pin the scaffolding interface (how a scientific agent is declared, where reproducibility metadata lives) before any agents are written against it.
- Track upstream AgenticSeek changes in [`alrobles/agenticSeek`](https://github.com/alrobles/agenticSeek); keep the fork merge-able.

## Next

Once the shell is in place, the next phase is making a single end-to-end path actually work, end to end, on one machine.

- DIY-mode demo: EcoAgent runs a tiny scientific agent (literature triage or a unit-conversion / data-cleanup task) against a local model, brokered by AgenticPlug, with full audit log.
- BYOK plumbing: add DeepSeek as the first cloud provider, with keys held only by AgenticPlug. Mocked first; real keys gated behind a deliberate opt-in.
- EcoCoder authoring loop: write an agent, run it locally, see the audit trail, iterate.
- Knowledgebase wiring: pull from [`alrobles/knowledgebase`](https://github.com/alrobles/knowledgebase) as a read-only reference source.
- Define and publish the alpha checklist gate (see [`alpha-checklist.md`](./alpha-checklist.md)) and ship the first internal alpha behind it.

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
