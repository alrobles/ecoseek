# 2026 GBIF Ebbe Nielsen Challenge — Submission

**Project:** EcoSeek — A Scientific AI Agent for Biodiversity  
**Team:** alrobles / ReumanLab  
**Repo:** https://github.com/alrobles/ecoseek  
**Live:** https://ecoseek.org · https://kids.ecoseek.org  

---

## Abstract

Most biodiversity tools expect you to learn their interface, download the data, and run your analysis somewhere else. EcoSeek doesn't. You ask a question — "What drives Quercus distribution in the Mexican Altiplano?" — and the system does the rest. It hits GBIF for occurrence records, pulls WorldClim layers, runs a species distribution model, searches the literature, and comes back with maps, citations, and numbers.

A swarm of DiDAL agents splits the work across whatever compute is available: your laptop, the lab cluster, an HPC node. A gateway called AgenticPlug sits between the agents and the outside world, approving or denying every GBIF query, filesystem write, and API call. The agent layer never touches a raw credential. If you're deploying this in a university or research institute, someone will ask "who accessed what and when." The audit log has the answer.

We also built kids.ecoseek.org — same system, but for children ages 6 to 15. Emily, an animated astronaut, guides them through ecology, animals, plants, and Earth science. Responses go through content safety filters. It's live and serving actual young users right now.

EcoSeek is open source. Git + Docker, three commands to run. Three modes: offline with local models, bring-your-own-keys for cloud models, or lab-managed with role-based access and audit logs.

---

## Rationale

### What we actually built

We didn't take a generic LLM and add biodiversity prompts. EcoSeek is an agent built specifically for ecological research. The agents don't just chat — they run tools. SDM, niche overlap, GBIF data validation, host-parasite network construction, taxonomic resolution. Over 30 of them, exposed as HTTP endpoints that the gateway discovers and brokers.

DiDAL is the part that distributes work. Send a complex question, and multiple agents go off in parallel — one hits GBIF, another pulls climate data, a third searches PubMed. They report back through the same gateway that enforces policy and logs everything. If a reviewer wants to know exactly what happened during a query, the audit trail has it.

The security model is why this can actually run in an institution. The gateway is approval-gated. Six capabilities require explicit sign-off. Every decision goes into a SQLite log. We've got 600+ tests covering auth, authorization, path traversal, and key encryption. It fails closed — ambiguous request, denied.

### Why GBIF should care

GBIF has 2.7 billion records. Getting insight out of them still takes real technical skill. EcoSeek lowers that bar without dumbing down the science. Every query is logged. Every model run captures its inputs and seeds. Results trace back to source data.

kids.ecoseek.org reaches an audience GBIF currently doesn't: children. These are the people who'll be submitting their own datasets in 15 years. Right now they're asking Emily about volcanoes and whale sharks. The responses are safe, the data is real GBIF data, and the site is live.

### What makes this different from previous Challenge winners

Past winners have built visualization tools, data cleaners, analysis pipelines. All valuable. EcoSeek is a different thing: an agent that does the pipeline for you. You describe the scientific question. The system figures out which GBIF endpoints to hit, which models to run, which papers to cite. That's not been submitted before.

The LACS literature pipeline and GBIF tools existed before this submission. What's new is putting them behind an agent interface, distributed across compute, with institutional-grade security and an audit trail. And a kids version that's actually deployed and serving users.

### Openness

Everything is on GitHub, open source. The only external dependency is GBIF itself. Clone, run three commands, you're in. Every query result, agent decision, and model output is reproducible. The audit trail has the receipts.

### Quality

600+ tests across 26 suites. Two live deployments. Pre-alpha code, production security posture. The gateway won't start with invalid path configuration. The keystore refuses to run without the cryptography library. Fail-closed isn't a design principle we wrote in a doc — it's enforced at runtime.

---

## How to run it

Git + Docker. That's it.

```bash
git clone https://github.com/alrobles/ecoseek.git
cd ecoseek
bash setup.sh
docker compose up --build
```

Then hit `http://localhost:3000` and try:

```
POST /v1/smart-search {"text": "ecological niche of Quercus in Mexican altiplano"}
```

Kids version at https://kids.ecoseek.org — no setup needed.

## Video

[Link to be provided]

## Repositories

**Main:** https://github.com/alrobles/ecoseek  
**Gateway:** https://github.com/alrobles/agenticplug  
**Inference:** https://github.com/alrobles/ecocoder  
**Tools:** https://github.com/alrobles/ecoagent  
**Kids:** https://github.com/alrobles/ecoseek-kids  
**Live:** https://ecoseek.org · https://kids.ecoseek.org