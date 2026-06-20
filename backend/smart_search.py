"""Smart Search — LLM-powered literature retrieval for ecoSeek.
Uses Ollama Qwen2.5 14B for query expansion + semantic re-ranking.
"""
import json, urllib.request, sys, os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://r22r35n01:56593/api/generate")
MEILI_URL = os.environ.get("MEILI_URL", "http://alpha:7700")
MODEL = os.environ.get("SMART_MODEL", "qwen2.5:14b-instruct-q4_K_M")

def query_ollama(prompt, max_tokens=300):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": max_tokens}
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["response"]

def search_meili(query, limit=50):
    body = json.dumps({"q": query, "limit": limit, "attributesToRetrieve": ["id","title","abstract","year","keywords","doi","has_abstract"]}).encode()
    req = urllib.request.Request(f"{MEILI_URL}/indexes/gbif_literature/search", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def expand_query(user_query):
    """Use LLM to rewrite the user query with scientific terminology."""
    prompt = f"""You are an expert in biodiversity informatics. Rewrite the following search query to find relevant ecological literature in English.

User query: {user_query}

Generate:
1. SCIENTIFIC_QUERY: A precise English query with scientific species names, ecological terms, and methodology keywords for searching GBIF-cited ecological papers.
2. The query should mention specific taxa (scientific names), geographic regions, ecological processes, and analytical methods if relevant.
3. Keep it concise (max 15 words).

SCIENTIFIC_QUERY: """
    expanded = query_ollama(prompt, 100)
    # Extract just the query line
    for line in expanded.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "SCIENTIFIC_QUERY" not in line and len(line) > 5:
            return line.strip('"').strip()
    return user_query  # fallback

def rerank_papers(user_query, papers):
    """Use LLM to score and re-rank papers based on relevance to user intent."""
    papers_text = ""
    for i, p in enumerate(papers[:20]):
        papers_text += f"{i+1}. [{p.get('year','?')}] {p['title'][:120]}\n"
    
    prompt = f"""As an ecological literature expert, rank these papers by relevance to the query. Return ONLY a JSON array with indices of the top 10 most relevant papers.

QUERY: {user_query}

PAPERS:
{papers_text}

Return: {{"ranking": [3, 7, 1, ...]}} — indices of top 10 papers in order of relevance.
"""
    response = query_ollama(prompt, 200)
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
    except:
        pass
    return papers  # fallback
