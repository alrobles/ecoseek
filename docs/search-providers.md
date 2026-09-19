# EcoSeek Literature Search — Provider Configuration

## Overview

EcoSeek's literature search endpoints use an LLM-powered pipeline for query
expansion and semantic re-ranking. The provider chain is configured for
**balance between speed and availability**.

## Provider Chain (priority order)

**Policy: no Chinese AI providers or models.** Mimo/Xiaomi, DeepSeek, GLM
(Zhipu), Kimi (Moonshot) and Qwen (Alibaba) are excluded everywhere — both
as hosted providers and as model choices on routers. This is a hard
requirement, not a preference; do not re-add them to the chain.

| Priority | Provider | Model | Latency | Use Case |
|----------|----------|-------|---------|----------|
| 1 | **Arcee router** | inkling-small (Thinking Machines Lab, US) | ~3-6s | Primary — OpenAI-compatible (`api.arcee.ai/api/v1`) |
| 2 | **Ollama** | llama3.1:8b (Meta, US) | ~6s | Fallback — free, self-hosted (set `OLLAMA_URL`) |
| 3 | **OpenRouter** | openai/gpt-4o-mini (OpenAI, US) | ~3s | Last resort — paid, non-reasoning |

## Configuration by Environment

### Demo / Development (current)
- **Primary:** Arcee `inkling-small` via `ARCEE_API_KEY`
- **Why:** Hosted, no cluster dependency, honors the no-Chinese-AI policy
- **Override model:** `ARCEE_MODEL` (default `thinkingmachines/inkling-small`)

### Production (EcoSeek cluster)
- **Fallback:** Ollama on KU-HPC via SSH tunnel — use a US model
  (`llama3.1:8b`, `gemma3`, …). Do NOT use the legacy deepseek-r1 jobs.
- **Tunnel:** `ssh -f -N -L 19998:<node>:<port> kuhpc`

### Switching providers

To switch primary provider, reorder the `PROVIDERS` list in:
- `backend/metasearch.py`
- `backend/smart_search.py`

```python
# For demo (Arcee primary):
PROVIDERS = [
    ("arcee", {...}),      # ← primary
    ("ollama", {...}),     # ← fallback
    ("openrouter", {...}),
]

# For production (Ollama primary):
PROVIDERS = [
    ("ollama", {...}),     # ← primary
    ("arcee", {...}),      # ← fallback
    ("openrouter", {...}),
]
```

## Endpoints

| Endpoint | Backend | Purpose |
|----------|---------|---------|
| `/v1/search` | ecoseek-api:3000 | Instant Meilisearch (no LLM) |
| `/v1/smart-search` | ecoseek-api:3000 | LLM query expansion + re-ranking |
| `/v1/metasearch` | ecoseek-api:3000 | Dual-language + LLM ranking |
| `/v1/chat/completions` | hermes:8642 | Emily chat (Hermes gateway) |

## Nginx Routing (ecoseek-frontend)

```
/v1/search        → host.docker.internal:3000  (ecoseek-api)
/v1/smart-search  → host.docker.internal:3000  (ecoseek-api)
/v1/metasearch    → host.docker.internal:3000  (ecoseek-api)
/v1/*             → host.docker.internal:8642  (hermes/Emily)
/health           → host.docker.internal:8642  (hermes)
```

## Cluster Ollama Jobs (legacy — deprecated)

The KU-HPC cluster previously ran Ollama instances with **deepseek-r1:14b**
— retired per the no-Chinese-AI policy. Any future cluster deployment must
use a US/open model (`llama3.1`, `gemma3`, …). Tunnel command for whatever
job is running:

`ssh -f -N -L 19998:<node>:<port> kuhpc`

## Performance Benchmarks

| Search Type | Cold | Warm (cache) | LLM Calls |
|-------------|------|--------------|-----------|
| `/v1/search` | <100ms | <100ms | 0 |
| `/v1/metasearch` | ~5s | ~3s | 2 (expand + rank) |
| `/v1/smart-search` | ~3-9s | ~3s | 1-2 |

## Key Optimizations Applied

1. **Query cache** — `_expand_cache` dict (512 entries, LRU eviction)
2. **Parallel Meilisearch** — EN + native queries run in threads
3. **Reduced LLM calls** — 2 max (expand + rank), critique/revise removed
4. **Reasoning effort** — `reasoning_effort=low` sent to reasoning-capable
   providers (e.g. Inkling) to cap thinking tokens; `max_tokens=512` leaves
   headroom so `content` isn't starved by reasoning.
