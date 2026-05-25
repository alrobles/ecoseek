# EcoSeek Plugin — DiDAL Protocol v2

Emily (Alpha, local) ↔ Hermes (Beta, remote on reumanlab) via `hermes.ecoseek.org`.

## Tools

| Tool | Description |
|------|-------------|
| `didal_protocol` | **Primary tool** — full dialectical research loop with automatic complexity routing |
| `classify_prompt` | Classify prompt complexity (direct/didal/didal_literature) |
| `hermes_status` | Check if Hermes Beta is available |
| `escalate_remote` | One-shot delegation to Beta (execution tasks) |
| `dialectical_exchange` | Legacy DiDAL exchange (iterative execution tasks) |

## DiDAL Protocol v2

### Automatic Mode Selection

The protocol classifies prompts and routes them automatically:

| Mode | Score | Description |
|------|-------|-------------|
| `direct` | < 0.25 | Simple/factual — fast single-call answer |
| `didal` | 0.25-0.59 | Conceptual — structured debate + mini-report |
| `didal_literature` | >= 0.60 | Scientific synthesis — adds evidence retrieval |

### Protocol Stages (didal/didal_literature mode)

```
1. Classify     → determine mode from prompt complexity
2. Frame Task   → decompose question into structured task object
3. Retrieve     → gather evidence sources (didal_literature only)
4. Expert Draft → first scientific synthesis from Beta
5. Critique     → identify gaps from naive interlocutor perspective
6. Revise       → address critique (max 2 rounds)
7. Report       → assemble structured mini-report
```

### Role Architecture

- **Alpha (Emily)**: Naive Scientific Interlocutor — clarifies, decomposes, critiques gaps
- **Beta (Hermes)**: Expert Scientific Researcher — retrieves, synthesizes, produces drafts

### Mini-Report Output Template

```
Title
Question and Scope
Short Answer
Conceptual Definition
Historical Development
Key Distinctions
Evidence and References
Competing Views and Limitations
Synthesis
Open Questions
```

## Setup

```bash
# Pass your Hermes API key when starting Emily:
HERMES_ECOSEEK_API_KEY=agenticplu... DEEPSEEK_API_KEY=sk-... bash emily-start.sh
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_REMOTE_URL` | `https://hermes.ecoseek.org` | Remote Hermes endpoint |
| `HERMES_ECOSEEK_API_KEY` | *(required for escalation)* | API key for hermes.ecoseek.org |
| `HERMES_REMOTE_MODEL` | `hermes` | Model name on the remote |
| `HERMES_REMOTE_TIMEOUT` | `300` | Request timeout in seconds |
| `DIDAL_ENABLED` | `true` | Feature flag for DiDAL protocol |
| `DIDAL_MAX_CRITIQUE_ROUNDS` | `2` | Max critique-revise rounds |
| `DIDAL_MAX_TURNS` | `12` | Max turns for legacy exchange |
| `DIDAL_STUCK_THRESHOLD` | `3` | Repeated errors before stopping |
| `ENTREZ_API_KEY` | *(optional BYOK)* | NCBI Entrez key for PubMed retrieval |
| `ENTREZ_EMAIL` | `ecoseek@ecoseek.org` | Email for Entrez API compliance |
| `S2_API_KEY` | *(optional)* | Semantic Scholar key for higher rate limits |
| `OPENALEX_MAILTO` | `ecoseek@ecoseek.org` | Email for OpenAlex polite pool |
| `GBIF_LITERATURE_ENABLED` | `true` | Enable GBIF Literature API search |
| `PHOENIX_COLLECTOR_ENDPOINT` | *(optional)* | Phoenix/OTLP endpoint (e.g. `http://localhost:6006/v1/traces`) |
| `PHOENIX_PROJECT_NAME` | `ecoseek-didal` | Project name in Phoenix UI |

## Architecture

```
User → localhost:4000 (frontend)
         → localhost:8642 (Emily/Alpha)
              ┌─ classify_prompt → determine mode
              ├─ didal_protocol → structured loop:
              │    frame → retrieve → draft → critique → revise → report
              │    (all calls to hermes.ecoseek.org)
              ├─ escalate_remote → one-shot to Beta
              └─ dialectical_exchange → legacy iterative loop
                   → hermes.ecoseek.org (Hermes/Beta on reumanlab)
                        → eco_analyze (GBIF, SDM, diversity, taxonomy)
                        → ku_hpc (Slurm → A100/MI210 GPUs)
                        → shell, GitHub CLI, DeepSeek v4 Pro
```

## Literature Retrieval Sources

| Source | Auth Required | Coverage | Used For |
|--------|--------------|----------|----------|
| **OpenAlex** | No (mailto recommended) | 250M+ works | Primary search, Tier A & B |
| **Semantic Scholar** | No (key for higher limits) | 200M+ papers | Abstracts + citations, Tier B |
| **GBIF Literature** | No | Biodiversity papers | Ecology-specific, Tier B |
| **NCBI Entrez/PubMed** | BYOK (`ENTREZ_API_KEY`) | Biomedical + ecology | High-quality, Tier B |

Retrieval tiers:
- **Tier A** (fast): OpenAlex only, 2-3 results per query
- **Tier B** (scientific): All sources, 5-10 results with deduplication

Inspired by `alrobles/gbifliterature` (GBIF API wrapper) and `alrobles/paper-qa` fork (Apache 2.0).

## Benchmark Prompts

### Direct mode (should route to direct)
- "What port is the backend running on?"
- "Where is the config file generated?"

### DiDAL mode (should route to didal)
- "Explain the difference between the fundamental niche and realized niche."
- "Why do ecological explanations often fail when they ignore scale?"

### DiDAL Literature mode (should route to didal_literature)
- "What is the fundamental niche, and how has the concept evolved since Hutchinson?"
- "Contrast niche theory and neutral theory using references and explain where each is most useful."
- "Summarize the ecological meaning of density dependence and support the answer with papers."
