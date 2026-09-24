# EcoSeek Plugin — DiDAL Protocol v2

Emily (Alpha, local) ↔ Hermes (Beta, remote on reumanlab) via `hermes.ecoseek.org`.

## Tools

| Tool | Description |
|------|-------------|
| `didal_protocol` | **Primary tool** — full dialectical research loop with automatic complexity routing |
| `classify_prompt` | Classify prompt complexity (direct/didal/didal_literature) |
| `ecoagent_query` | Execute ecological analysis on EcoAgent (reumanlab) — 25 tools: GBIF, SDM, taxonomy, cofid, etc. |
| `literature_search` | Search the local literature database (cached papers from all retrieval sources) |
| `world_query` | **EcoSeek World** — stigmergic lookup in the persistent artifact registry |
| `world_propose` | Register a new durable artifact (content-addressed, novelty-gated) |
| `world_event` | Record test/install/observe/repair/dismantle/attest on an artifact |
| `world_validate` | Promote to `validated` — requires agent-free replay evidence + metrics |
| `world_fork` | Executable inheritance — fork an artifact into a descendant |
| `world_get` | Full artifact record + provenance event history |
| `world_lineage` | Ancestors/descendants inheritance graph |
| `world_stats` | Portfolio metrics (validated inventions, lineage depth, reuse fraction) |
| `world_replay` | Frozen agent-free replay of `artifact.executable` on held-out inputs — emits `world_validate` evidence |
| `world_methods` | Render a Methods section from provenance (lineage + evidence + replay runs) — registers a `methods_section` artifact |
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
HERMES_ECOSEEK_API_KEY=agenticplu... ARCEE_API_KEY=sk-... bash emily-start.sh
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
                        → shell, GitHub CLI, Trinity Large Thinking (Arcee)
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

## Phase 5: Memory + Judge + Policy Evolution

### Memory (SQLite — persistent across sessions)

| Class | Stores | Example |
|-------|--------|---------|
| **Episodic** | Previous sessions, user intent, mode used | "User asked about niche ecology → didal_literature, 2 rounds" |
| **Semantic** | Stable concepts, theses, key points | "Fundamental niche = n-dimensional hypervolume (Hutchinson 1957)" |
| **Procedural** | Strategies, round counts, source counts | "didal_literature averages 2 rounds, 4 sources" |

**Writeback policy:** Only writes when judge score > threshold (default 0.6), user confirms, or new concept detected.

Memory is stored at `~/.ecoseek/didal_memory/` on the host, mounted into Docker.

### Judge

Scores final answers on 6 criteria:
- Scientific accuracy, Definition clarity, Evidence grounding
- Perspective contrast, Depth, Report structure

Uses LLM judge via Hermes Beta when available; falls back to heuristic scoring.
Produces overall score (0-1), verdict (excellent/good/adequate/needs_improvement/poor), and per-criterion breakdown.

### Policy Evolution

Records fitness signals per protocol run:
```
fitness = 0.25(answer_quality) + 0.20(evidence_quality) + 0.15(report_structure)
        + 0.15(clarification) + 0.10(memory_usefulness)
        - 0.10(excessive_rounds) - 0.05(unused_retrieval)
```

Stats from `policy_signals` table can tune classifier thresholds, round limits, and retrieval policies.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DIDAL_MEMORY_ENABLED` | `true` | Enable/disable memory |
| `DIDAL_MEMORY_DIR` | `~/.hermes/didal_memory` | SQLite DB location |
| `DIDAL_WRITEBACK_SCORE_THRESHOLD` | `0.6` | Min judge score to write memory |
| `DIDAL_JUDGE_ENABLED` | `true` | Enable/disable LLM judge |
| `DIDAL_JUDGE_TIMEOUT` | `120` | Judge LLM call timeout (seconds) |

## Reasoning Mode Toggle (Fast / Auto / Deep)

The frontend provides a 3-way toggle that controls how Emily processes questions:

| Mode | Frontend Label | Behavior | Cost |
|------|---------------|----------|---------------|
| ⚡ **Fast** (Rápido) | `fast` | Skips DiDAL → direct single-call answer | Cheapest |
| 🔄 **Auto** | `auto` | Classifier decides (default) | Varies by complexity |
| 🧠 **Deep** (Profundo) | `deep` | Forces full DiDAL protocol + literature retrieval | Standard cost, deeper reasoning |

### How It Works

1. User selects mode via toggle button next to the chat input
2. Frontend injects `[reasoning_mode:fast|deep]` prefix into the message
3. Emily's `didal_protocol` tool parses the prefix and maps:
   - `fast` → `direct` mode (skip dialectical loop)
   - `deep` → `didal_literature` mode (full protocol + evidence retrieval)
   - `auto` → classifier decides based on prompt complexity score
4. `reasoning_effort` is NOT forwarded raw — trinity-large-thinking always thinks (Hermes handles this internally)

### Provider note

Emily's remote escalation runs on Trinity Large Thinking via Arcee AI.
DeepSeek/Qwen/MiMo and other Chinese AI providers are banned (see
`docs/search-providers.md`) — DeepSeek pricing references were removed.

## Literature Database (litdb)

Persistent SQLite cache for retrieved papers. Stores papers from OpenAlex, GBIF Literature, Semantic Scholar, and Entrez so repeated queries hit the local cache instead of the API.

### Features

- **FTS5 full-text search** over titles, abstracts, and authors (Porter stemming + Unicode)
- **Automatic caching**: `retrieve_literature()` stores API results → subsequent queries are instant
- **Deduplication** by DOI (with use-count tracking)
- **`literature_search` tool**: Emily can search the cache directly for quick reference lookups
- **Persistent**: stored at `~/.ecoseek/didal_memory/literature.db` (Docker volume mount)

### Usage

```python
from emily.plugins.ecoseek.litdb import search, store_paper, get_stats

# Search cached papers
results = search("niche modeling MaxEnt", limit=10)

# Store a paper manually
store_paper(doi="10.1234/test", title="...", provider="openalex")

# Check statistics
stats = get_stats()  # {'total_papers': 42, 'by_provider': {...}, ...}
```

## EcoCoder-7B Integration — ⚠️ non-compliant model

[EcoCoder-7B](https://huggingface.co/alrobles/EcoCoder-7B) is a domain-specialized ecological LLM — **but it is a Qwen2.5-Coder fine-tune, which is banned under the no-Chinese-AI policy** (`docs/search-providers.md`). Do not deploy it on lab infrastructure; it is retained for history until a compliant-base retrain lands (see ecocoder repo).

> ⚠️ **~4.5 GB download.** Non-compliant — do not run in the EcoSeek stack.

### Benchmarking EcoCoder vs DeepSeek — DEPRECATED

`benchmarks/ecocoder_vs_deepseek.py` compares two models that are both
non-compliant under the policy. See `benchmarks/README.md` for details and
the compliant-comparator path.

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
