# 2026 GBIF Ebbe Nielsen Challenge — Submission

**Project:** EcoSeek — A Scientific AI Agent for Biodiversity  
**Team:** alrobles / ReumanLab  
**Repo:** https://github.com/alrobles/ecoseek  
**Live:** https://ecoseek.org · https://kids.ecoseek.org  

---

## Abstract

Most biodiversity tools expect users to learn a query interface, download data, and run analyses in separate environments. EcoSeek does not. A researcher asks a question — "What drives Quercus distribution in the Mexican Altiplano?" — and the system queries GBIF occurrences, retrieves WorldClim layers, runs a species distribution model, searches the literature, and returns maps, citations, and model outputs.

The system has three components. A swarm of DiDAL agents distributes computation across available hardware — from a laptop to an HPC node; the gateway (AgenticPlug) brokers every GBIF query, filesystem write, and external API call, while the agent layer never holds raw credentials. kids.ecoseek.org extends GBIF-mediated data to learners aged 6 to 15; an animated mascot guides children through ecology, zoology, and Earth science with age-appropriate responses filtered through content safety guardrails. The system runs in three modes — offline with local models, bring-your-own-keys with Fernet-encrypted credentials, or lab-managed with role-based access control and audit trails.

All components are open source, require only Git and Docker, and include 600+ automated security tests across 26 suites covering authentication, authorization, path traversal protection, and encryption key management.

---

## Rationale

### A dedicated biodiversity AI agent

Previous Ebbe Nielsen Challenge winners have advanced visualization, data cleaning, and analysis pipelines. EcoSeek represents a different approach: an agentic system I built specifically for ecological research workflows. The agents do not merely generate text — they execute tools. EcoAgent exposes over 30 biodiversity-specific HTTP endpoints (species distribution modeling, niche overlap, GBIF data validation, host-parasite network construction, taxonomic resolution) that AgenticPlug discovers and brokers at runtime.

DiDAL orchestrates parallel execution. A complex query triggers multiple agents simultaneously — one fetches GBIF occurrences, another retrieves environmental layers, a third searches PubMed — all coordinated through the same gateway that enforces policy and records decisions in an immutable audit log.

The gateway is approval-gated; six capabilities require explicit authorization. Every decision is recorded. If a reviewer needs to trace what happened during a query, the audit log provides the chain of events. The system fails closed — ambiguous requests are denied.

### Relevance to GBIF

GBIF holds over 2.7 billion occurrence records. Extracting insight at scale requires technical expertise that many potential users lack. EcoSeek accepts natural-language questions and returns results backed by GBIF data, literature, and model outputs — without requiring users to learn query languages or manage separate analysis environments. Every query is logged; every model run captures its inputs and seeds; results trace to source data.

kids.ecoseek.org reaches an audience GBIF currently does not serve — children aged 6 to 15. These users will become the next generation of biodiversity data contributors; engaging them early matters. The site is live and serving real users today.

### Openness and repeatability

All code is freely available under open-source licenses. The stack runs locally with no external dependencies beyond GBIF data access. Every component can be inspected, modified, and redeployed. Agent decisions, model outputs, and query results are reproducible: LACS uses deterministic scoring, EcoAgent captures tool versions and input seeds, and the audit trail records every approval.

### Quality of implementation

The codebase ships with 600+ automated tests across 26 suites. Two deployments (ecoseek.org and kids.ecoseek.org) serve live traffic. The gateway refuses to start with invalid path configuration; the keystore refuses to operate without the cryptography library. I designed the system to fail closed at runtime — it is not a documented aspiration, it is enforced behavior.

---

## How to run

Git and Docker. Three commands:

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
bash setup.sh
docker compose up --build
```

Access at `http://localhost:3000`. Try:

```
POST /v1/smart-search {"text": "ecological niche of Quercus in Mexican altiplano"}
```

Kids version at https://kids.ecoseek.org — no setup required.

## Video

[Link to be provided]

## Repositories

**Main:** https://github.com/alrobles/ecoseek  
**Gateway:** https://github.com/alrobles/agenticplug  
**Inference:** https://github.com/alrobles/ecocoder  
**Tools:** https://github.com/alrobles/ecoagent  
**Kids:** https://github.com/alrobles/ecoseek-kids  
**Live:** https://ecoseek.org · https://kids.ecoseek.org