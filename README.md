# EcoSeek

**EcoSeek** is an independent, downstream scientific adaptation built on top of a fork of [AgenticSeek](https://github.com/Fosowl/agenticSeek). It is the final product direction for a community- and lab-oriented agentic assistant focused on scientific workflows, reproducibility, and safe local-first operation.

EcoSeek is **not** an official AgenticSeek release. It is **not affiliated with**, **not endorsed by**, and **not maintained by** the AgenticSeek project or its contributors unless and until such a relationship is publicly established. All references to AgenticSeek are made with gratitude, attribution, and respect for the upstream license.

---

## Gratitude and attribution

EcoSeek would not exist without the work of the AgenticSeek authors and contributors. The upstream project provided the core agent loop, browser/research patterns, and many of the architectural ideas that EcoSeek builds on. We thank everyone who has contributed to AgenticSeek.

See [`UPSTREAM_CREDITS.md`](./UPSTREAM_CREDITS.md) for a more detailed acknowledgement of upstream work and the license obligations that flow from it.

---

## What EcoSeek is

EcoSeek is a **product shell**, not yet a runnable product. This repository currently contains documentation, architecture notes, and the roadmap. Working code, integrations, and binaries live in companion repositories (see below) and will be referenced as they stabilize.

EcoSeek is composed of three cooperating concepts:

- **AgenticPlug** — the secure gateway. AgenticPlug is the trust boundary between EcoSeek and the outside world. It brokers credentials (BYOK), authenticates clients, gates risky actions, and is the only component permitted to hold long-lived secrets in the deployed product.
- **EcoCoder / EcoAgent** — the community/scientific intelligence path. EcoCoder is the developer-facing surface for building, testing, and sharing scientific agents and tools. EcoAgent is the runtime that executes those agents against EcoSeek's local-first stack.
- **DeepSeek BYOK (optional)** — for users who want stronger low-cost reasoning, EcoSeek supports bringing your own DeepSeek API key. This is optional. EcoSeek is designed to run with local models by default; DeepSeek is one of several supported BYOK providers.

For a deeper picture, see [`docs/architecture.md`](./docs/architecture.md).

---

## Product modes

EcoSeek will be usable in three modes:

1. **DIY** — self-hosted, fully local, no external accounts. The default for privacy-sensitive users and offline labs.
2. **BYOK** — self-hosted with user-provided API keys for frontier or low-cost cloud models (e.g. DeepSeek). Keys never leave the user's AgenticPlug instance.
3. **Lab-managed** — a research group or institution operates a shared AgenticPlug for its members. Members do not handle keys directly; the lab's gateway does.

---

## Status

This repository is **pre-alpha**. There is no installable product yet. See:

- [`docs/alpha-checklist.md`](./docs/alpha-checklist.md) — what works, what is mocked, what is unsafe, and the gate for the first public alpha.
- [`docs/roadmap.md`](./docs/roadmap.md) — Now / Next / Later.
- [`docs/install.md`](./docs/install.md) — local/mock setup. **Do not use real secrets yet.**
- [`docs/security.md`](./docs/security.md) — security posture, BYOK rules, gating principles.

---

## Related repositories

EcoSeek is one piece of a small constellation of repositories. None of these are official upstream projects.

- [`alrobles/agenticSeek`](https://github.com/alrobles/agenticSeek) — the fork EcoSeek descends from.
- [`alrobles/agenticplug`](https://github.com/alrobles/agenticplug) — the AgenticPlug secure gateway.
- [`alrobles/ecocoder`](https://github.com/alrobles/ecocoder) — developer surface for scientific agents and tools.
- [`alrobles/ecoagent`](https://github.com/alrobles/ecoagent) — runtime executing EcoCoder-authored agents.
- [`alrobles/knowledgebase`](https://github.com/alrobles/knowledgebase) — shared knowledge and curated references for the scientific stack.

---

## License

The final license for EcoSeek is **not yet decided**. See [`NOTICE.md`](./NOTICE.md) for the current placeholder and the constraints that any final choice must respect (in particular, GPLv3 attribution obligations flowing from AgenticSeek-derived components).

Until a license is committed to this repository, treat the contents as **"all rights reserved, source-available for review and discussion only"** — but note that any AgenticSeek-derived code that lands here in the future will need to comply with the upstream GPLv3 terms.

---

## Disclaimer

EcoSeek is an independent project. It is not an official AgenticSeek product, not affiliated with the AgenticSeek maintainers, and not endorsed by them. Bugs, security issues, and design decisions in EcoSeek are the responsibility of the EcoSeek maintainers, not the upstream project.
