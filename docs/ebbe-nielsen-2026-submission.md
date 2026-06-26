# 2026 GBIF Ebbe Nielsen Challenge — Submission

**Project:** EcoSeek — Scientific Agentic Assistant for Biodiversity Informatics  
**Team:** alrobles / ReumanLab  
**Repository:** https://github.com/alrobles/ecoseek  
**Live sites:** https://ecoseek.org | https://kids.ecoseek.org  

---

## Abstract (max 300 words)

EcoSeek is an open-source, local-first agentic assistant that transforms how researchers, conservationists, and educators interact with GBIF-mediated biodiversity data. Built on a three-layer architecture — Substrate, Gateway (AgenticPlug), and Intelligence (EcoCoder + EcoAgent) — EcoSeek enables natural-language queries against biodiversity records, species distributions, and ecological literature.

The submission presents three integrated innovations:

1. **Smart Literature Search (LACS pipeline):** A PU-learning classifier scores 36 million PubMed abstracts for ecological relevance, indexing them into Meilisearch. Combined with LLM-powered query expansion via a multi-provider chain (MiMo, Ollama, OpenRouter), researchers can discover biodiversity literature through natural language — for example, asking "What parasites affect amphibians in the Sierra Madre Oriental?" and receiving ranked citations enriched with GBIF occurrence data.

2. **DiDAL Distributed Agent System:** A swarm of lightweight AI agents running across HPC and edge nodes performs parallel biodiversity computations — species distribution modeling, GBIF data cleansing, and niche overlap analysis — coordinated through the AgenticPlug gateway with role-based access control and full audit trails.

3. **kids.ecoseek.org:** A kid-friendly science portal (ages 6–15) that makes GBIF-mediated biodiversity data accessible to young learners. Emily Astronauta, an animated mascot, guides children through ecology, zoology, botany, and Earth science using safe, age-appropriate responses filtered through Hermes Gateway content guardrails.

All components are fully open-source, self-hosted, and require only Git + Docker. EcoSeek operates in three modes: DIY (fully offline), BYOK (user-provided cloud keys, Fernet-encrypted), and Lab-managed (shared gateway with 600+ security tests).

---

## Rationale

### Openness & Repeatability

All components are freely available on GitHub under open-source licenses. The entire stack runs locally with zero external dependencies beyond GBIF data access. Every query, tool call, and policy decision is logged in a persistent audit trail. Reproducibility is guaranteed: the LACS pipeline uses deterministic scoring, the AgenticPlug gateway records every approval, and EcoAgent captures tool versions and input seeds. Any researcher can clone, run, and verify results.

### Applicability to the GBIF Network

EcoSeek addresses three critical gaps in the GBIF ecosystem:

- **Literature-to-data bridging:** GBIF excels at occurrence data but lacks deep integration with ecological literature. The LACS pipeline connects 36M PubMed abstracts to GBIF taxa, enabling researchers to ask "what does the literature say about this species?" and receive both citations and occurrence maps.
- **Democratizing access:** kids.ecoseek.org reaches audiences that GBIF portals currently do not serve — children aged 6–15 who will become the next generation of biodiversity scientists. The site already operates live, receiving real queries from young users.
- **Computational scaling:** DiDAL distributes GBIF data processing across available compute from laptops to HPC clusters, making large-scale analyses (SDM for thousands of species, niche overlap matrices) feasible for researchers without institutional HPC access.

### Innovation & Novelty

Unlike traditional GBIF tools that focus on single-purpose visualizations or downloads, EcoSeek introduces an **agentic** paradigm: the user describes a scientific question in natural language, and a swarm of AI agents autonomously queries GBIF, searches literature, runs models, and synthesizes results. This agentic approach has not been demonstrated in previous Ebbe Nielsen Challenge winners.

The LACS PU-learning pipeline is also novel for GBIF: it uses only 62K positive examples (GBIF-derived ecological publications) to classify 36M PubMed abstracts without requiring labeled negatives, a technique with immediate applicability to other biodiversity data domains.

### Quality of Implementation

EcoSeek is production-ready at pre-alpha stage with **600+ automated security tests** across 26 test suites covering authentication, authorization, approval workflows, path traversal protection, and BYOK encryption (Fernet: AES-128-CBC + HMAC-SHA256). The gateway enforces a fail-closed security posture: if any policy check is ambiguous, the request is denied. Two live deployments (ecoseek.org and kids.ecoseek.org) serve real users with monitored uptime.

### Benefit for GBIF Network

EcoSeek adds value across all GBIF stakeholder groups:

- **Data users:** Natural-language access to GBIF + literature, agentic analysis pipelines
- **Data holders:** Increased visibility through literature-mediated species discovery
- **Data managers:** Open-source, auditable, self-hosted — no vendor lock-in
- **Community & outreach:** kids.ecoseek.org builds the next generation of biodiversity scientists
- **Policy:** Evidence synthesis combining GBIF data with peer-reviewed literature at scale

---

## Operating Instructions

1. **Quick start** (requires Git + Docker):
   ```bash
   git clone https://github.com/alrobles/ecoseek.git
   cd ecoseek
   bash setup.sh
   docker compose up --build
   ```
2. Access the gateway at `http://localhost:3000`
3. Try a query: `POST /v1/smart-search {"text": "amphibian parasites in Mexico"}`
4. Visit https://kids.ecoseek.org for the kid-friendly version

## Video Demo

[Link to be provided]

## Submission Materials

- GitHub: https://github.com/alrobles/ecoseek
- AgenticPlug (gateway): https://github.com/alrobles/agenticplug
- EcoCoder (inference): https://github.com/alrobles/ecocoder
- EcoAgent (tools): https://github.com/alrobles/ecoagent
- EcoSeek Kids: https://github.com/alrobles/ecoseek-kids
- Live: https://ecoseek.org | https://kids.ecoseek.org