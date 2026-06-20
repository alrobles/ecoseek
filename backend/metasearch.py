import os
"""
Metasearch — multi-agent literature search with DiDAL protocol.

Uses Alpha↔Beta dialectic to refine search queries and rank papers.
Alpha proposes → Beta critiques → Alpha revises → consensus ranking.
"""
import json, urllib.request, time, logging

logger = logging.getLogger("ecoseek.metasearch")

MEILI_URL = os.environ.get("MEILI_URL", "http://100.123.27.68:7700")
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
        prompt = f"""User query: {user_query}

Step 1: Detect the language. If NOT English, translate to precise scientific English.
Step 2: Expand with GBIF taxonomy — find scientific names for any common species names.

Generate a JSON object:
1. "detected_language": ISO 639-1 code (es, en, pt, fr, de, etc.)
2. "english_query": Always. The primary search query in English with scientific terminology. Max 15 words.
3. "native_query": If original is not English, a search query in the native language. Max 15 words.
4. "scientific_names": Array of scientific taxa found (genus, species, family).
5. "keywords": Array of 3-5 key ecological/methodological terms.
6. "filters": Object with "min_year" and "require_abstract" (boolean).

Return: {{"detected_language": "es", "english_query": "...", "native_query": "...", "scientific_names": [...], "keywords": [...], "filters": {{"min_year": 2018, "require_abstract": true}}}}"""
    
    response = ask(prompt, ALPHA_SYS, max_tokens=300 if papers else 200)
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except:
        pass
    return {"ranking": list(range(1, min(11, len(papers)+1))) if papers else {},
            "english_query": user_query, "native_query": user_query, "detected_language": "en",
            "scientific_names": [], "keywords": [], "filters": {"min_year": 2018, "require_abstract": True}}

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
    
    # ROUND 1 — Query expansion + language detection
    logger.info("Metasearch R1: Alpha expands query '%s'", user_query[:60])
    alpha_r1 = alpha_propose(user_query)
    english_query = alpha_r1.get("english_query", user_query)
    native_query = alpha_r1.get("native_query", user_query)
    detected_lang = alpha_r1.get("detected_language", "en")
    stages.append({"stage": "expand", "alpha": alpha_r1, 
                   "english_query": english_query, "native_query": native_query,
                   "detected_language": detected_lang})
    
    # PRIMARY: search in English (always)
    papers_en = search(english_query, limit=30)
    logger.info("Metasearch: English search '%s' -> %d papers", english_query[:60], len(papers_en))
    
    # SECONDARY: search in native language if different
    papers_native = []
    if detected_lang != "en" and native_query != english_query:
        papers_native = search(native_query, limit=15)
        logger.info("Metasearch: Native (%s) search -> %d papers", detected_lang, len(papers_native))
    
    # Merge + deduplicate
    papers = papers_en
    seen_ids = {p.get("id") for p in papers_en}
    for p in papers_native:
        if p.get("id") not in seen_ids:
            papers.append(p)
            seen_ids.add(p.get("id"))
    
    logger.info("Metasearch: merged %d papers (%d EN + %d native)", len(papers), len(papers_en), len(papers_native))
    
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
            paper = papers[i]
            doi = paper.get("doi", "")
            doi_link = f"https://doi.org/{doi}" if doi else ""
            reranked.append({
                "id": paper.get("id", ""),
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""),
                "year": str(paper.get("year", "")),
                "keywords": paper.get("keywords", ""),
                "doi": doi,
                "doi_link": doi_link,
            })
            seen.add(i)
    
    elapsed = int((time.time() - t0) * 1000)
    logger.info("Metasearch done: %d results in %dms", len(reranked), elapsed)
    
    return {"results": reranked, "stages": stages, "time_ms": elapsed}
