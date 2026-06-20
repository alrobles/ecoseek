import os
"""
Metasearch — fast literature search with geographic relevance.

Single LLM call for ranking (expand is heuristic, no LLM needed).
Geographic post-filtering for better relevance.
"""
import json, urllib.request, time, logging, threading, re

logger = logging.getLogger("ecoseek.metasearch")

MEILI_URL = os.environ.get("MEILI_URL", "http://100.123.27.68:7700")

# ─── Provider fallback chain ────────────────────────────────────────────
PROVIDERS = []

# 1. Mimo mimo-v2.5 (xiaomi) — fastest
MIMO_KEY = os.environ.get("XIAOMI_API_KEY", "")
if MIMO_KEY:
    PROVIDERS.append(("mimo", {
        "url": "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
        "model": "mimo-v2.5",
        "key": MIMO_KEY,
        "type": "openai",
    }))

# 2. Ollama deepseek-r1:14b (cluster) — fallback
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
if OLLAMA_URL:
    PROVIDERS.append(("ollama", {
        "url": OLLAMA_URL if "/api/generate" in OLLAMA_URL else f"{OLLAMA_URL}/api/generate",
        "model": os.environ.get("OLLAMA_MODEL", "deepseek-r1:14b"),
        "type": "ollama",
    }))

# 3. OpenRouter — last resort
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if OR_KEY:
    PROVIDERS.append(("openrouter", {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "deepseek/deepseek-chat-v3-0324",
        "key": OR_KEY,
        "type": "openai",
    }))

logger.info("Metasearch providers: %s", [p[0] for p in PROVIDERS])

# ─── LLM call with fallback ─────────────────────────────────────────────
def ask(prompt, system="", max_tokens=200, temperature=0.3):
    """Try each provider in order until one responds."""
    for provider_name, cfg in PROVIDERS:
        try:
            if cfg["type"] == "ollama":
                full = f"{system}\n\n{prompt}" if system else prompt
                body = json.dumps({
                    "model": cfg["model"], "prompt": full,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens}
                }).encode()
                req = urllib.request.Request(cfg["url"], data=body,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read())
                    response = data.get("response", "")
                    if not response:
                        response = data.get("thinking", "")
                    logger.info("LLM via %s: %d chars", provider_name, len(response))
                    return response
            
            elif cfg["type"] == "openai":
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": prompt})
                body = json.dumps({
                    "model": cfg["model"], "messages": msgs,
                    "max_tokens": max_tokens, "temperature": temperature,
                    "reasoning_effort": "low"
                }).encode()
                req = urllib.request.Request(cfg["url"], data=body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {cfg['key']}"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    response = json.loads(resp.read())
                    text = response["choices"][0]["message"]["content"]
                    if not text:
                        text = response["choices"][0]["message"].get("reasoning_content", "")
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

# ─── Heuristic translate (no LLM needed) ───────────────────────────────
# Common ecological terms in Spanish/Portuguese/French → English
ECO_DICT = {
    "mamiferos": "mammals", "mamíferos": "mammals",
    "aves": "birds", "peces": "fish", "reptiles": "reptiles",
    "anfibios": "amphibians", "insectos": "insects",
    "plantas": "plants", "árboles": "trees",
    "biodiversidad": "biodiversity", "distribución": "distribution",
    "conservación": "conservation", "ecología": "ecology",
    "hábitat": "habitat", "especie": "species", "especies": "species",
    "género": "genus", "familia": "family",
    "bosque": "forest", "selva": "jungle", "montaña": "mountain",
    "río": "river", "lago": "lake", "mar": "sea", "océano": "ocean",
    "clima": "climate", "cambio": "change", "amenaza": "threat",
    "endémico": "endemic", "amenazado": "threatened",
    "invasor": "invasive", "nativo": "native",
    "de": "of", "del": "of the", "en": "in", "el": "the", "la": "the",
    "los": "the", "las": "the", "un": "a", "una": "a",
    "y": "and", "o": "or", "del": "of the",
    "mammifères": "mammals", "oiseaux": "birds", "biodiversité": "biodiversity",
    "espèces": "species", "habitat": "habitat", "conservation": "conservation",
}

# Known geographic terms
GEO_TERMS = {
    "españa": "Spain", "spain": "Spain", "iberian": "Iberian",
    "colombia": "Colombia", "mexico": "Mexico", "brasil": "Brazil",
    "argentina": "Argentina", "peru": "Peru", "chile": "Chile",
    "ecuador": "Ecuador", "venezuela": "Venezuela", "bolivia": "Bolivia",
    "costa rica": "Costa Rica", "panama": "Panama", "guatemala": "Guatemala",
    "honduras": "Honduras", "nicaragua": "Nicaragua", "cuba": "Cuba",
    "europa": "Europe", "europe": "Europe", "africa": "Africa",
    "asia": "Asia", "amazonas": "Amazon", "amazon": "Amazon",
    "andes": "Andes", "caribe": "Caribbean", "mediterraneo": "Mediterranean",
    "tropical": "tropical", "neotropical": "Neotropical",
}

def _extract_geographic(query_lower):
    """Extract geographic context from query."""
    for term, english in GEO_TERMS.items():
        if term in query_lower:
            return english
    return ""

def _heuristic_translate(query):
    """Fast translate without LLM. Returns (english_query, geo_context)."""
    query_lower = query.lower().strip()
    geo = _extract_geographic(query_lower)
    
    words = re.findall(r'\w+', query_lower)
    translated = []
    for w in words:
        if w in ECO_DICT:
            translated.append(ECO_DICT[w])
        elif len(w) > 2:  # keep short words as-is
            translated.append(w)
    
    english = " ".join(translated)
    if geo and geo.lower() not in english.lower():
        english += f" {geo}"
    
    return english, geo

# ─── Meilisearch ──────────────────────────────────────────────────────
def search(query, limit=30, geo_filter=None):
    """Search Meilisearch. If geo_filter is set (ISO code), filter by country."""
    payload = {
        "q": query,
        "limit": limit,
        "attributesToRetrieve": ["id","title","abstract","year","keywords","doi","has_abstract","countries_of_coverage","country_names_coverage","topics","language"],
    }
    # Add geographic filter if available
    if geo_filter:
        payload["filter"] = f'country_names_coverage = "{geo_filter}"'
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{MEILI_URL}/indexes/gbif_literature/search",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("hits", [])
    except Exception as e:
        logger.error("Meilisearch error: %s", e)
        return []

def _parallel_search(queries, limit=25, geo_filter=None):
    """Run multiple Meilisearch queries in parallel, return merged hits."""
    results = [None] * len(queries)
    threads = []
    def _do_search(idx, q):
        results[idx] = search(q, limit=limit, geo_filter=geo_filter)
    for i, q in enumerate(queries):
        t = threading.Thread(target=_do_search, args=(i, q))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    merged = []
    seen = set()
    for hits in results:
        if not hits:
            continue
        for p in hits:
            pid = p.get("id")
            if pid not in seen:
                merged.append(p)
                seen.add(pid)
    return merged

# ─── Geographic post-filter ────────────────────────────────────────────
def _geo_boost(papers, geo_context):
    """Boost papers that mention the geographic context in title/abstract."""
    if not geo_context:
        return papers
    
    geo_lower = geo_context.lower()
    boosted = []
    rest = []
    
    for p in papers:
        text = ((p.get("title","") or "") + " " + (p.get("abstract","") or "")).lower()
        if geo_lower in text:
            boosted.append(p)
        else:
            rest.append(p)
    
    logger.info("Geo filter: %d/%d papers mention '%s'", len(boosted), len(papers), geo_context)
    return boosted + rest

# ─── Paper formatting ─────────────────────────────────────────────────
def format_papers(papers, max_n=20):
    lines = []
    for i, p in enumerate(papers[:max_n]):
        abstract = p.get("abstract", "") or ""
        title = p.get("title", "") or ""
        lines.append(f"{i+1}. [{p.get('year','?')}] {title[:120]}")
        if abstract:
            lines.append(f"   {abstract[:200]}...")
    return "\n".join(lines)

# ─── Single LLM call for ranking ──────────────────────────────────────
RANK_SYS = "You rank ecological papers. Output ONLY a JSON array of indices. Geographic relevance to the query is #1 priority. No explanations."

def rank_papers(user_query, papers):
    """Single LLM call to rank papers by relevance."""
    papers_text = format_papers(papers, 20)
    prompt = f"""Query: {user_query}
{papers_text}

Rank top-10 by relevance. Geographic match to query is #1 priority.
Output ONLY JSON: {{"ranking": [3,7,1,...]}}"""
    
    response = ask(prompt, RANK_SYS, max_tokens=100)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end]).get("ranking", [])
    except:
        pass
    return []

# ─── Main metasearch ──────────────────────────────────────────────────
def metasearch(user_query):
    t0 = time.time()
    provider_used = PROVIDERS[0][0] if PROVIDERS else "none"
    
    # STEP 1 — Heuristic translate (instant, no LLM)
    cached = _cache_get(user_query)
    if cached:
        english, geo = cached["english_query"], cached.get("geographic_context", "")
        logger.info("Cache hit: '%s' → '%s'", user_query[:40], english[:40])
    else:
        english, geo = _heuristic_translate(user_query)
        _cache_set(user_query, {"english_query": english, "geographic_context": geo})
        logger.info("Translated: '%s' → '%s' (geo=%s)", user_query[:40], english[:40], geo)
    
    # STEP 2 — Parallel Meilisearch (EN + original if different)
    # Try with geographic filter first, then without if too few results
    queries = [english]
    if english.lower() != user_query.lower():
        queries.append(user_query)
    
    papers = _parallel_search(queries, limit=30, geo_filter=geo)
    if len(papers) < 5 and geo:
        logger.info("Too few geo-filtered results (%d), retrying without filter", len(papers))
        papers = _parallel_search(queries, limit=30)
    
    logger.info("Meilisearch: %d papers from %d queries", len(papers), len(queries))
    
    if not papers:
        elapsed = int((time.time() - t0) * 1000)
        return {"results": [], "time_ms": elapsed, "provider": provider_used, "method": "fast"}
    
    # STEP 3 — Geographic boost (instant, no LLM)
    papers = _geo_boost(papers, geo)
    
    # STEP 4 — Single LLM call for ranking (if enough papers)
    if len(papers) > 3:
        ranking = rank_papers(user_query, papers)
        results = _format_results(papers, ranking)
    else:
        results = _format_results(papers)
    
    elapsed = int((time.time() - t0) * 1000)
    return {"results": results[:15], "time_ms": elapsed,
            "provider": provider_used, "method": "fast"}

def _format_results(papers, ranking=None):
    reranked = []
    seen = set()
    indices = ranking if ranking else list(range(1, len(papers)+1))
    
    for idx in indices[:15]:
        i = idx - 1
        if 0 <= i < len(papers) and i not in seen:
            p = papers[i]
            doi = p.get("doi", "")
            reranked.append({
                "id": p.get("id", ""), "title": p.get("title", ""),
                "abstract": p.get("abstract", ""), "year": str(p.get("year", "")),
                "keywords": p.get("keywords", ""),
                "doi": doi, "doi_link": f"https://doi.org/{doi}" if doi else "",
            })
            seen.add(i)
    
    for p in papers:
        if len(reranked) >= 15: break
        if p.get("id") not in {r["id"] for r in reranked}:
            doi = p.get("doi", "")
            reranked.append({
                "id": p.get("id", ""), "title": p.get("title", ""),
                "abstract": p.get("abstract", ""), "year": str(p.get("year", "")),
                "keywords": p.get("keywords", ""),
                "doi": doi, "doi_link": f"https://doi.org/{doi}" if doi else "",
            })
    
    return reranked
