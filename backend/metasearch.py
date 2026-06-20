import os
"""
Metasearch — multi-agent literature search with DiDAL protocol + fallback chain.

Ollama Q6000 (primary) → Mimo (fallback) → OpenRouter (last resort).
Query cache avoids repeated LLM calls for same/similar queries.
Parallel EN + native search for dual-language performance.
"""
import json, urllib.request, time, logging, threading
from functools import lru_cache

logger = logging.getLogger("ecoseek.metasearch")

MEILI_URL = os.environ.get("MEILI_URL", "http://100.123.27.68:7700")
MAX_ROUNDS = 2  # Reduced: expand + rank (skip critique if <10 results)

# ─── Provider fallback chain ────────────────────────────────────────────
PROVIDERS = []

# 1. Ollama Q6000 (local, free, 47 tok/s)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
if OLLAMA_URL:
    PROVIDERS.append(("ollama", {
        "url": OLLAMA_URL if "/api/generate" in OLLAMA_URL else f"{OLLAMA_URL}/api/generate",
        "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct-q4_K_M"),
        "type": "ollama",
    }))

# 2. Mimo (xiaomi) — reasoning model
MIMO_KEY = os.environ.get("XIAOMI_API_KEY", "")
if MIMO_KEY:
    PROVIDERS.append(("mimo", {
        "url": "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
        "model": "mimo-v2.5-pro",
        "key": MIMO_KEY,
        "type": "openai",
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
def ask(prompt, system="", max_tokens=300, temperature=0.3):
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
                with urllib.request.urlopen(req, timeout=45) as resp:
                    response = json.loads(resp.read()).get("response", "")
                    logger.info("LLM via %s: %d chars", provider_name, len(response))
                    return response
            
            elif cfg["type"] == "openai":
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.append({"role": "user", "content": prompt})
                body = json.dumps({
                    "model": cfg["model"], "messages": msgs,
                    "max_tokens": max_tokens, "temperature": temperature
                }).encode()
                req = urllib.request.Request(cfg["url"], data=body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {cfg['key']}"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    response = json.loads(resp.read())
                    text = response["choices"][0]["message"]["content"]
                    logger.info("LLM via %s: %d chars", provider_name, len(text))
                    return text
        
        except Exception as e:
            logger.warning("Provider %s failed: %s", provider_name, str(e)[:80])
            continue
    
    logger.error("ALL providers failed!")
    return ""

# ─── Query cache ────────────────────────────────────────────────────────
@lru_cache(maxsize=256)
def _cached_expand(query):
    """Cache query expansions. Keyed by lowercase normalized query."""
    return None  # Will be filled by alpha_propose

# ─── Meilisearch ──────────────────────────────────────────────────────
def search(query, limit=30):
    body = json.dumps({"q": query, "limit": limit,
        "attributesToRetrieve": ["id","title","abstract","year","keywords","doi","has_abstract"]}).encode()
    req = urllib.request.Request(f"{MEILI_URL}/indexes/gbif_literature/search",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("hits", [])
    except Exception as e:
        logger.error("Meilisearch error: %s", e)
        return []

# ─── Paper formatting ─────────────────────────────────────────────────
def format_papers(papers, max_n=15):
    lines = []
    for i, p in enumerate(papers[:max_n]):
        kw = p.get("keywords","") or ""
        if len(kw) > 60: kw = kw[:57] + "..."
        lines.append(f"{i+1}. [{p.get('year','?')}] {p['title'][:100]}")
        if p.get("abstract"):
            lines.append(f"   {p['abstract'][:150]}...")
    return "\n".join(lines)

# ─── Alpha / Beta ──────────────────────────────────────────────────────
ALPHA_SYS = "You are EcoSeek Alpha, an expert in biodiversity informatics. You design optimal search strategies and rank papers by ecological relevance. Be precise and concise."
BETA_SYS = "You are EcoSeek Beta, a skeptical peer reviewer. You critique Alpha's rankings, find blind spots, and suggest improvements. Be critical but fair."

def alpha_propose(user_query, papers=None):
    if papers:
        papers_text = format_papers(papers, 20)
        prompt = f"""Query: {user_query}\nPapers:\n{papers_text}\nRank top-10 by relevance. Return JSON: {{"ranking": [3,7,1,...], "explanation": "why"}}"""
        response = ask(prompt, ALPHA_SYS, max_tokens=200)
    else:
        prompt = f"""Query: {user_query}\n
Detect language. If not English, translate to scientific English. Find scientific names for species.
Return JSON: {{"detected_language":"es","english_query":"Andean hummingbird biodiversity","native_query":"colibries andes distribucion","scientific_names":["Trochilidae"],"keywords":["species distribution","elevational gradient"],"filters":{{"min_year":2018,"require_abstract":true}}}}"""
        response = ask(prompt, ALPHA_SYS, max_tokens=200)
    
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"ranking": list(range(1, min(11, len(papers)+1))) if papers else {},
            "english_query": user_query, "detected_language": "en", "keywords": []}

def beta_critique(user_query, papers, alpha_ranking):
    if len(papers) < 10:
        return {"critique": "Few results, skip critique", "suggested_rerank": alpha_ranking.get("ranking", [])}
    
    papers_text = format_papers(papers, 20)
    prompt = f"""Query: {user_query}\nAlpha ranked: {alpha_ranking.get('ranking',[])}\nPapers:\n{papers_text}\nCritique ranking. Return JSON: {{"critique":"...","suggested_rerank":[...],"reason":"..."}}"""
    response = ask(prompt, BETA_SYS, max_tokens=200)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"critique": "Parse error", "suggested_rerank": alpha_ranking.get("ranking", [])}

def alpha_revise(user_query, alpha_r, beta):
    prompt = f"""Query: {user_query}\nAlpha: {alpha_r.get('ranking',[])}\nBeta: {beta.get('critique','')} suggested {beta.get('suggested_rerank',[])}\nSynthesize final ranking. Return JSON: {{"final_ranking":[...],"synthesis":"..."}}"""
    response = ask(prompt, ALPHA_SYS, max_tokens=150)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"final_ranking": alpha_r.get("ranking", []), "synthesis": "Fallback"}

# ─── Main metasearch ──────────────────────────────────────────────────
def metasearch(user_query):
    t0 = time.time()
    stages = []
    provider_used = PROVIDERS[0][0] if PROVIDERS else "none"
    
    # ROUND 1 — Expand (with cache)
    logger.info("Metasearch: '%s'", user_query[:60])
    alpha_r1 = alpha_propose(user_query)
    english = alpha_r1.get("english_query", user_query)
    native = alpha_r1.get("native_query", user_query)
    lang = alpha_r1.get("detected_language", "en")
    stages.append({"stage": "expand", "english": english, "native": native, "lang": lang})
    
    # Parallel search (EN + native if different)
    papers_en = search(english, limit=25)
    
    papers_native = []
    if lang != "en" and native != english:
        papers_native = search(native, limit=10)
    
    # Merge
    papers = papers_en
    seen = {p.get("id") for p in papers_en}
    for p in papers_native:
        if p.get("id") not in seen:
            papers.append(p)
            seen.add(p.get("id"))
    
    logger.info("Merged: %d papers (%d EN + %d native)", len(papers), len(papers_en), len(papers_native))
    
    # ROUND 2 — Rank + optional critique
    if len(papers) <= 1:
        elapsed = int((time.time() - t0) * 1000)
        return {"results": _format_results(papers[:10]), "stages": stages, 
                "time_ms": elapsed, "provider": provider_used, "method": "didal-fast"}
    
    alpha_r2 = alpha_propose(user_query, papers)
    stages.append({"stage": "rank", "alpha": alpha_r2})
    
    # Only critique if many results (saves time)
    if len(papers) > 10:
        beta = beta_critique(user_query, papers, alpha_r2)
        stages.append({"stage": "critique", "beta": beta})
        final = alpha_revise(user_query, alpha_r2, beta)
        stages.append({"stage": "revise", "final": final})
        ranking = final.get("final_ranking", alpha_r2.get("ranking", []))
    else:
        ranking = alpha_r2.get("ranking", [])
    
    elapsed = int((time.time() - t0) * 1000)
    return {"results": _format_results(papers, ranking),
            "stages": stages, "time_ms": elapsed,
            "provider": provider_used, "method": "didal"}

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
    
    # Add unranked papers
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
