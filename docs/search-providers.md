# EcoSeek Literature Search — Provider Configuration

## Overview

EcoSeek's literature search endpoints use an LLM-powered pipeline for query
expansion and semantic re-ranking. The provider chain is configured for
**balance between speed and availability**.

## Provider Chain (priority order)

| Priority | Provider | Model | Latency | Use Case |
|----------|----------|-------|---------|----------|
| 1 | **Mimo (Xiaomi)** | mimo-v2.5 | ~2s | Primary — fast reasoning with `reasoning_effort=low` |
| 2 | **Ollama (KU-HPC)** | deepseek-r1:14b | ~6s | Fallback — free, local, 14B reasoning model |
| 3 | **OpenRouter** | deepseek-chat-v3 | ~3s | Last resort — paid, non-reasoning |

## Configuration by Environment

### Demo / Development (current)
- **Primary:** Mimo mimo-v2.5 via `XIAOMI_API_KEY`
- **Why:** Fastest option (~2s per LLM call), consistent availability
- **Tradeoff:** Uses API credits, depends on Xiaomi service

### Production (EcoSeek cluster)
- **Primary:** Ollama deepseek-r1:14b via SSH tunnel to KU-HPC
- **Why:** Free, local, no external dependencies
- **Tradeoff:** Slower (~6s per call), requires cluster jobs running
- **Tunnel:** `ssh -f -N -L 19998:r22r20n01:39501 kuhpc`

### Switching providers

To switch primary provider, reorder the `PROVIDERS` list in:
- `backend/metasearch.py`
- `backend/smart_search.py`

```python
# For demo (Mimo primary):
PROVIDERS = [
    ("mimo", {...}),     # ← primary
    ("ollama", {...}),   # ← fallback
    ("openrouter", {...}),
]

# For production (Ollama primary):
PROVIDERS = [
    ("ollama", {...}),   # ← primary
    ("mimo", {...}),     # ← fallback
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

## Cluster Ollama Jobs

The KU-HPC cluster runs 4 Ollama instances with deepseek-r1:14b (Q4_K_M):

| Node | Port | Context | Notes |
|------|------|---------|-------|
| r15r10n01 | 35367 | 8192 | New job |
| r22r25n01 | 43459 | 8192 | --no-mmap |
| r22r20n01 | 39501 | 65536 | **Recommended** (tunnel target) |
| r22r15n01 | 34529 | 65536 | Standard |

Tunnel command: `ssh -f -N -L 19998:r22r20n01:39501 kuhpc`

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
4. **Reasoning effort** — `reasoning_effort=low` for Mimo (22 vs 278 tokens)
5. **Faster model** — mimo-v2.5 instead of mimo-v2.5-pro (~35% faster)
