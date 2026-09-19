"""Smart Search — LLM-powered literature retrieval for ecoSeek.

Provider fallback chain: Arcee → Ollama → OpenRouter.

NOTE: Chinese AI providers are intentionally excluded (policy: no Chinese
AI services/models — no Mimo/Xiaomi, DeepSeek, GLM, Kimi, Qwen). Arcee's
Inkling-Small (Thinking Machines Lab, US) is the primary provider.
Query expansion + semantic re-ranking for better results.
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger("ecoseek.smart_search")

MEILI_URL = os.environ.get("MEILI_URL", "http://meilisearch:7700")

# ─── Provider fallback chain (same as metasearch) ──────────────────────
# Policy: no Chinese AI providers/models (no Mimo, DeepSeek, GLM, Kimi, Qwen).
PROVIDERS = []

# 1. Arcee router (Inkling-Small, Thinking Machines Lab US) — primary
ARCEE_KEY = os.environ.get("ARCEE_API_KEY", "")
if ARCEE_KEY:
    PROVIDERS.append(
        (
            "arcee",
            {
                "url": "https://api.arcee.ai/api/v1/chat/completions",
                "model": os.environ.get("ARCEE_MODEL", "thinkingmachines/inkling-small"),
                "key": ARCEE_KEY,
                "type": "openai",
            },
        )
    )

# 2. Ollama (cluster/self-hosted) — fallback
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
if OLLAMA_URL:
    PROVIDERS.append(
        (
            "ollama",
            {
                "url": OLLAMA_URL
                if "/api/generate" in OLLAMA_URL
                else f"{OLLAMA_URL}/api/generate",
                "model": os.environ.get("SMART_MODEL", "llama3.1:8b"),
                "type": "ollama",
            },
        )
    )

# 3. OpenRouter — last resort
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if OR_KEY:
    PROVIDERS.append(
        (
            "openrouter",
            {
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "model": "openai/gpt-4o-mini",
                "key": OR_KEY,
                "type": "openai",
            },
        )
    )

logger.info("Smart search providers: %s", [p[0] for p in PROVIDERS])


# ─── LLM call with fallback ─────────────────────────────────────────────
def ask(prompt, system="", max_tokens=300, temperature=0.3):
    """Try each provider in order until one responds."""
    for provider_name, cfg in PROVIDERS:
        try:
            if cfg["type"] == "ollama":
                full = f"{system}\n\n{prompt}" if system else prompt
                body = json.dumps(
                    {
                        "model": cfg["model"],
                        "prompt": full,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        },
                    }
                ).encode()
                req = urllib.request.Request(
                    cfg["url"], data=body, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                    response = data.get("response", "")
                    # Reasoning models put output in 'thinking' field
                    if not response:
                        response = data.get("thinking", "")
                    logger.info("LLM via %s: %d chars", provider_name, len(response))
                    return response

            elif cfg["type"] == "openai":
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": prompt})
                body = json.dumps(
                    {
                        "model": cfg["model"],
                        "messages": msgs,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "reasoning_effort": "low",
                    }
                ).encode()
                req = urllib.request.Request(
                    cfg["url"],
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {cfg['key']}",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    response = json.loads(resp.read())
                    text = response["choices"][0]["message"]["content"]
                    # Reasoning models may put output in reasoning_content
                    if not text:
                        text = response["choices"][0]["message"].get(
                            "reasoning_content", ""
                        )
                    logger.info("LLM via %s: %d chars", provider_name, len(text))
                    return text

        except Exception as e:
            logger.warning("Provider %s failed: %s", provider_name, str(e)[:80])
            continue

    logger.error("ALL providers failed!")
    return ""


# ─── Query cache ────────────────────────────────────────────────────────
_expand_cache = {}


def _cache_get(query):
    key = query.strip().lower()
    return _expand_cache.get(key)


def _cache_set(query, result):
    key = query.strip().lower()
    if len(_expand_cache) >= 512:
        oldest = next(iter(_expand_cache))
        del _expand_cache[oldest]
    _expand_cache[key] = result


# ─── Meilisearch ──────────────────────────────────────────────────────
def search_meili(query, limit=50):
    body = json.dumps(
        {
            "q": query,
            "limit": limit,
            "attributesToRetrieve": [
                "id",
                "title",
                "abstract",
                "year",
                "keywords",
                "doi",
                "has_abstract",
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"{MEILI_URL}/indexes/gbif_literature/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error("Meilisearch error: %s", e)
        return {"hits": []}


def expand_query(user_query):
    """Use LLM to rewrite the user query with scientific terminology."""
    # Check cache first
    cached = _cache_get(user_query)
    if cached:
        logger.info("Cache hit for: %s", user_query[:40])
        return cached

    prompt = f"""Translate to English scientific search terms. Include geographic region. Output ONLY the query, nothing else.

User query: {user_query}

Query: """
    expanded = ask(prompt, max_tokens=512)
    # Extract just the query line
    for line in expanded.split("\n"):
        line = line.strip()
        if (
            line
            and not line.startswith("#")
            and "SCIENTIFIC_QUERY" not in line
            and len(line) > 5
        ):
            result = line.strip('"').strip()
            _cache_set(user_query, result)
            return result
    _cache_set(user_query, user_query)
    return user_query  # fallback


def rerank_papers(user_query, papers):
    """Use LLM to score and re-rank papers based on relevance to user intent."""
    papers_text = ""
    for i, p in enumerate(papers[:20]):
        abstract = p.get("abstract", "") or ""
        papers_text += f"{i + 1}. [{p.get('year', '?')}] {p['title'][:120]}\n"
        if abstract:
            papers_text += f"   {abstract[:150]}...\n"

    prompt = f"""As an ecological literature expert, rank these papers by relevance to the query. CRITICAL: geographic match is the #1 priority. A paper about mammals in Colombia is NOT relevant if the query asks about mammals in Spain. Papers must match BOTH the topic AND the geographic region.
Return ONLY a JSON array with indices of the top 10 most relevant papers.

QUERY: {user_query}

PAPERS:
{papers_text}

Return: {{"ranking": [3, 7, 1, ...]}} — indices of top 10 papers in order of relevance.
"""
    response = ask(prompt, max_tokens=512)
    try:
        # Extract JSON
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            ranking = json.loads(response[start:end])
            indices = ranking.get("ranking", [])
            # Reorder papers
            reranked = []
            seen = set()
            for idx in indices:
                i = idx - 1  # 1-indexed to 0-indexed
                if 0 <= i < len(papers) and i not in seen:
                    reranked.append(papers[i])
                    seen.add(i)
            # Add remaining
            for i, p in enumerate(papers):
                if i not in seen:
                    reranked.append(p)
            return reranked
    except Exception:
        pass
    return papers  # fallback
