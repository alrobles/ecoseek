# 2026 GBIF Ebbe Nielsen Challenge — Submission

**Project:** EcoSeek — A Dedicated Scientific AI Agent for Biodiversity  
**Team:** alrobles / ReumanLab  
**Repository:** https://github.com/alrobles/ecoseek  
**Live sites:** https://ecoseek.org | https://kids.ecoseek.org  

---

## Abstract (max 300 words)

EcoSeek is the first dedicated scientific AI agent purpose-built for the GBIF network — not a generic chatbot with biodiversity prompts, but an agentic system designed from the ground up for ecological research, biodiversity informatics, and science outreach.

Where traditional GBIF tools require users to learn query interfaces, download datasets, and run analyses in separate environments, EcoSeek collapses the entire research pipeline into a single natural-language interaction. A researcher asks "What ecological factors drive the distribution of Quercus species in the Mexican Altiplano?" — and EcoSeek's swarm of DiDAL agents autonomously queries GBIF occurrences, retrieves WorldClim environmental layers, builds species distribution models, searches 36M PubMed abstracts for relevant literature, and synthesizes a response with citations, maps, and model outputs.

The system operates through a three-layer security architecture where no raw credentials ever reach the intelligence layer. An approval-gated gateway (AgenticPlug, 600+ tests) brokers every GBIF query, filesystem write, and external API call. This makes EcoSeek the first GBIF tool that can be safely deployed in institutional environments where data access must be audited and controlled.

The submission also introduces **kids.ecoseek.org**, a live deployment that extends GBIF's reach to learners aged 6–15. Emily Astronauta, an animated mascot, guides children through ecology, zoology, and Earth science with age-appropriate responses filtered through content safety guardrails — cultivating the next generation of biodiversity scientists through direct engagement with GBIF-mediated data.

EcoSeek is fully open-source, requires only Git + Docker, and operates in three modes: DIY (offline, local models), BYOK (user-provided cloud keys, Fernet-encrypted), and Lab-managed (institutional gateway with RBAC and audit trails).

---

## Rationale

### Core Innovation: A Dedicated Biodiversity AI Agent

The Ebbe Nielsen Challenge has recognized tools for visualization, data cleaning, and analysis pipelines. EcoSeek represents a fundamentally different category: **the first dedicated AI agent for GBIF**. It is not a generic LLM with biodiversity knowledge — it is an agentic system engineered specifically for ecological research workflows, with:

- **Domain-specialized agent architecture:** EcoCoder runs fine-tuned models optimized for ecological reasoning. EcoAgent exposes 30+ biodiversity-specific tools via HTTP — SDM, niche overlap, GBIF data validation, host-parasite networks, taxonomic resolution.
- **Multi-agent orchestration (DiDAL):** A swarm of lightweight agents distributed across available compute (laptop to HPC) performs tasks in parallel. The gateway coordinates agents, enforces policy, and records every decision in an immutable audit log.
- **Fail-closed security by design:** The agent cannot make an unmediated GBIF query, filesystem write, or API call. Every action passes through an approval-gated gateway. This is not a feature — it is the architectural invariant that makes EcoSeek suitable for institutional deployment where audit compliance matters.

### Why This Matters for GBIF

The GBIF network holds over 2.7 billion occurrence records, but extracting scientific insight still requires significant technical expertise. EcoSeek removes this barrier by letting researchers interact with GBIF data in natural language while maintaining scientific rigor — every query is logged, every model run is reproducible, and every result is traceable to its source data.

### Applicability

- **Researchers:** Ask complex ecological questions in natural language. Receive answers backed by GBIF data + literature + models. No query language, no separate analysis environments.
- **Institutions:** Deploy a lab-managed gateway with role-based access control. Audit every GBIF interaction. Share keys safely via Fernet-encrypted keystore.
- **Educators & children:** kids.ecoseek.org makes GBIF data accessible to ages 6–15 with content safety guardrails. Live, serving real users.
- **Data managers:** Open-source, self-hosted, zero vendor lock-in. Every component can be inspected, modified, and redeployed.

### Openness & Repeatability

All code is freely available under open-source licenses on GitHub. The entire stack runs locally — the only external dependency is GBIF data access. Every query result, agent decision, and model output is reproducible: LACS uses deterministic scoring, EcoAgent captures tool versions and input seeds, and the audit trail records every approval.

### Quality of Implementation

EcoSeek ships with **600+ automated security tests** covering authentication, authorization, approval workflows, path traversal protection, and BYOK encryption. Two live deployments (ecoseek.org and kids.ecoseek.org) serve real users. Pre-alpha maturity, production-ready security posture.

---

## Operating Instructions

1. **Quick start** (requires Git + Docker):
   ```bash
   git clone https://github.com/alrobles/ecoseek.git
   cd ecoseek
   bash setup.sh
   docker compose up --build
   ```
2. Access: `http://localhost:3000`
3. Try: `POST /v1/smart-search {"text": "ecological niche of Quercus in Mexican altiplano"}`
4. Kids version live at: https://kids.ecoseek.org

## Video Demo

[Link to be provided]

## Submission Materials

| Component | Repository |
|-----------|-----------|
| EcoSeek (monorepo) | https://github.com/alrobles/ecoseek |
| AgenticPlug (gateway) | https://github.com/alrobles/agenticplug |
| EcoCoder (inference) | https://github.com/alrobles/ecocoder |
| EcoAgent (tools) | https://github.com/alrobles/ecoagent |
| EcoSeek Kids | https://github.com/alrobles/ecoseek-kids |
| Live sites | https://ecoseek.org · https://kids.ecoseek.org |