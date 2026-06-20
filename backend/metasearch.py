"""
Metasearch — multi-agent literature search with DiDAL protocol.

Uses Alpha↔Beta dialectic to refine search queries and rank papers.
Alpha proposes → Beta critiques → Alpha revises → consensus ranking.
"""
import json, urllib.request, time, logging

logger = logging.getLogger("ecoseek.metasearch")

MEILI_URL = "http://alpha:7700"
OLLAMA_URL = "http://127.0.0.1:19998/api/generate"
MODEL = "qwen2.5:14b-instruct-q4_K_M"
MAX_ROUNDS = 3

# ─── LLM call ─────────────────────────────────────────────────────────
def ask(prompt, system="", max_tokens=300, temperature=0.3):
    full = f"{system}\n\n{prompt}" if system else prompt
    body = json.dumps({
        "model": MODEL, "prompt": full,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens}
    }).encode()
    r = urllib.request.Request(OLLAMA_URL, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read()).get("response", "")
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return ""

# ─── Meilisearch ──────────────────────────────────────────────────────
def search(query, limit=30):
    body = json.dumps({"q": query, "limit": limit,
        "attributesToRetrieve": ["id","title","abstract","year","keywords","doi","has_abstract"]}).encode()
    r = urllib.request.Request(f"{MEILI_URL}/indexes/gbif_literature/search",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
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

# ─── Alpha: propose query + ranking ───────────────────────────────────
ALPHA_SYS = """You are EcoSeek Alpha, an expert in biodiversity informatics.
Your job: design optimal search strategies and rank scientific papers by relevance.
You are rigorous, creative, and precise."""

BETA_SYS = """You are EcoSeek Beta, a skeptical peer reviewer.
Your job: critique Alpha's work, find blind spots, suggest improvements.
You are thorough, critical, and constructive."""

def alpha_propose(user_query, papers=None):
    """Alpha proposes query expansion + initial ranking."""
    if papers:
        papers_text = format_papers(papers, 20)
        prompt = f"""User is researching: {user_query}

You retrieved these papers. Rank the top-10 by relevance to the user's research question.
Consider: ecological relevance, methodological rigor, geographic specificity, recency.

Papers:
{papers_text}

Return a JSON object: {{"ranking": [3, 7, 1, ...], "explanation": "why this ranking"}}
The ranking array contains the 1-based indices of the top 10 papers in order.
"""
    else:
        prompt = f"""User wants to research: {user_query}

Generate a JSON object with:
1. "expanded_query": A precise search query with scientific terminology, species names, ecological methods, and geographic terms. Must be in English. Max 15 words.
2. "keywords": Array of 3-5 key scientific terms for keyword search.
3. "filters": Object with "min_year" (suggest a minimum year for relevance) and "require_abstract" (boolean).

Return: {{"expanded_query": "...", "keywords": [...], "filters": {{"min_year": 2020, "require_abstract": true}}}}"""
    
    response = ask(prompt, ALPHA_SYS, max_tokens=250 if papers else 150)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"ranking": list(range(1, min(11, len(papers)+1))) if papers else {},
            "expanded_query": user_query, "keywords": []}

def beta_critique(user_query, papers, alpha_ranking):
    """Beta critiques Alpha's ranking and suggests improvements."""
    papers_text = format_papers(papers, 20)
    prompt = f"""User is researching: {user_query}

Alpha ranked these papers. CRITIQUE this ranking. Consider:
- Are the top papers truly the most relevant?
- Did Alpha miss important ecological aspects?
- Are there geographic or taxonomic biases?
- Are highly-cited or foundational papers missing?

Alpha's ranking (indices): {alpha_ranking.get("ranking", [])}

Papers:
{papers_text}

Return a JSON object with:
- "critique": brief critique of Alpha's ranking
- "suggested_rerank": [new indices in preferred order, top-10]
- "reason": why your ranking is better
"""
    response = ask(prompt, BETA_SYS, max_tokens=300)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"critique": "Could not parse", "suggested_rerank": alpha_ranking.get("ranking", [])}

def alpha_revise(user_query, papers, alpha_ranking, beta_critique):
    """Alpha revises ranking based on Beta's critique."""
    papers_text = format_papers(papers, 20)
    prompt = f"""User is researching: {user_query}

Your original ranking: {alpha_ranking.get("ranking", [])}
Beta's critique: {beta_critique.get("critique", "")}
Beta's suggested ranking: {beta_critique.get("suggested_rerank", [])}

Synthesize the best of both rankings into a final consensus. Consider Beta's points fairly.
Return a JSON object: {{"final_ranking": [...], "synthesis": "brief explanation of final ranking"}}
"""
    response = ask(prompt, ALPHA_SYS, max_tokens=250)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"final_ranking": alpha_ranking.get("ranking", []), "synthesis": "Fallback"}

# ─── Main metasearch ──────────────────────────────────────────────────
def metasearch(user_query, rounds=MAX_ROUNDS):
    """
    Multi-agent literature search with Alpha↔Beta dialectic.
    
    Returns: {
        "results": [paper, ...],
        "stages": [{"stage": "expand"|"critique"|"revise", "alpha": ..., "beta": ...}],
        "time_ms": ...
    }
    """
    t0 = time.time()
    stages = []
    
    # ROUND 1 — Query expansion
    logger.info("Metasearch R1: Alpha expands query '%s'", user_query[:60])
    alpha_r1 = alpha_propose(user_query)
    expanded = alpha_r1.get("expanded_query", user_query)
    stages.append({"stage": "expand", "alpha": alpha_r1, "expanded_query": expanded})
    
    # Search with expanded query
    papers = search(expanded, limit=30)
    logger.info("Metasearch: Meilisearch returned %d papers", len(papers))
    
    if len(papers) < 5:
        return {"results": papers[:10], "stages": stages, 
                "time_ms": int((time.time()-t0)*1000)}
    
    # ROUND 2 — Alpha ranks, Beta critiques
    alpha_r2 = alpha_propose(user_query, papers)
    stages.append({"stage": "rank", "alpha": alpha_r2})
    
    beta = beta_critique(user_query, papers, alpha_r2)
    stages.append({"stage": "critique", "beta": beta})
    
    # ROUND 3 — Alpha revises
    final = alpha_revise(user_query, papers, alpha_r2, beta)
    stages.append({"stage": "revise", "final": final})
    
    # Build final result set
    ranking = final.get("final_ranking", alpha_r2.get("ranking", []))
    reranked = []
    seen = set()
    for idx in ranking[:15]:
        i = idx - 1  # 1-indexed to 0-indexed
        if 0 <= i < len(papers) and i not in seen:
            reranked.append({
                "id": papers[i].get("id", ""),
                "title": papers[i].get("title", ""),
                "abstract": papers[i].get("abstract", ""),
                "year": str(papers[i].get("year", "")),
                "keywords": papers[i].get("keywords", ""),
                "doi": papers[i].get("doi", ""),
            })
            seen.add(i)
    
    elapsed = int((time.time() - t0) * 1000)
    logger.info("Metasearch done: %d results in %dms", len(reranked), elapsed)
    
    return {"results": reranked, "stages": stages, "time_ms": elapsed}
