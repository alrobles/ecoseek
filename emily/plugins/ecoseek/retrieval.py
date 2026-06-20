"""Literature retrieval for DiDAL Protocol v2.

Provides multi-source scientific literature search with normalized output.
Sources (in priority order):
  1. OpenAlex  — 250M+ works, open, no auth required (default Tier A & B)
  2. Semantic Scholar — 200M+ papers, abstracts + citation context
  3. GBIF Literature — biodiversity-specific papers via api.gbif.org
  4. NCBI Entrez / PubMed — works without API key (3 req/s); faster with ENTREZ_API_KEY (10 req/s)
  5. EcoAgent RAG — GBIF literature + cofid via Hermes → reumanlab tool_server

Each source returns normalized Evidence objects that the protocol can
inject into the expert draft stage.

Design inspired by alrobles/gbifliterature (GBIF Literature API wrapper)
and alrobles/paper-qa (Apache 2.0, search → chunk → cite pipeline).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "ecoseek@ecoseek.org")
_S2_API_KEY = os.environ.get("S2_API_KEY", "")
_ENTREZ_API_KEY = os.environ.get("ENTREZ_API_KEY", "")
_ENTREZ_EMAIL = os.environ.get("ENTREZ_EMAIL", "ecoseek@ecoseek.org")
_GBIF_LIT_ENABLED = os.environ.get("GBIF_LITERATURE_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
_REQUEST_TIMEOUT = int(os.environ.get("RETRIEVAL_TIMEOUT", "15"))

# EcoAgent RAG backend on reumanlab (accessed via Hermes → eco_analyze)
_ECOAGENT_ENABLED = os.environ.get("ECOAGENT_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
_HERMES_REMOTE_URL = os.environ.get(
    "HERMES_REMOTE_URL", "https://hermes.ecoseek.org"
).rstrip("/")
_HERMES_API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")
_ECOAGENT_TIMEOUT = int(os.environ.get("ECOAGENT_RETRIEVAL_TIMEOUT", "30"))

# CORE API — world's largest open access aggregator (57M+ full texts)
_CORE_API_KEY = os.environ.get("CORE_API_KEY", "")
_CORE_ENABLED = os.environ.get("CORE_ENABLED", "true").lower() in ("true", "1", "yes")
_CORE_TIMEOUT = int(os.environ.get("CORE_RETRIEVAL_TIMEOUT", "15"))

# Crawl4AI — web crawling for supplementary literature (replaces Firecrawl)
_CRAWL4AI_VENV = os.environ.get(
    "CRAWL4AI_VENV", os.path.expanduser("~/crawl4ai-venv")
)
_CRAWL4AI_ENABLED = os.environ.get("CRAWL4AI_ENABLED", "true").lower() in (
    "true", "1", "yes",
)
_CRAWL4AI_TIMEOUT = int(os.environ.get("CRAWL4AI_TIMEOUT", "20"))

# ---------------------------------------------------------------------------
# Normalized evidence schema
# ---------------------------------------------------------------------------


class Evidence(NamedTuple):
    source_type: str  # "paper" | "review" | "web_reference" | "preprint"
    title: str
    authors: str  # first author et al.
    year: int | None
    url: str
    doi: str
    abstract: str
    claim_used_for: str  # filled later by the protocol
    confidence: float  # 0.0 - 1.0
    provider: str  # "openalex" | "semantic_scholar" | "gbif" | "entrez"


def evidence_to_dict(ev: Evidence) -> dict:
    return {
        "source_type": ev.source_type,
        "title": ev.title,
        "authors": ev.authors,
        "year": ev.year,
        "url": ev.url,
        "doi": ev.doi,
        "abstract": ev.abstract[:500] if ev.abstract else "",
        "claim_used_for": ev.claim_used_for,
        "confidence": ev.confidence,
        "provider": ev.provider,
    }


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _http_get_json(
    url: str, headers: dict | None = None, timeout: int = 0
) -> dict | list | None:
    """Simple GET → JSON with error handling."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout or _REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        TimeoutError,
    ) as exc:
        logger.warning("retrieval GET failed for %s: %s", url[:120], exc)
        return None


# ---------------------------------------------------------------------------
# OpenAlex search
# ---------------------------------------------------------------------------


def search_openalex(query: str, max_results: int = 5) -> list[Evidence]:
    """Search OpenAlex for papers matching the query.

    OpenAlex is free, no API key required. Adding mailto gets polite pool
    (faster rate limits).

    Docs: https://docs.openalex.org/api-entities/works/search-works
    """
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per_page": min(max_results, 25),
            "select": "id,doi,title,authorships,publication_year,type,cited_by_count,open_access,abstract_inverted_index",
            "mailto": _OPENALEX_MAILTO,
        }
    )
    url = f"https://api.openalex.org/works?{params}"
    data = _http_get_json(url)
    if not data or "results" not in data:
        return []

    results = []
    for work in data["results"][:max_results]:
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        title = work.get("title") or ""

        # Reconstruct abstract from inverted index
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        # Format authors
        authorships = work.get("authorships") or []
        if authorships:
            first = authorships[0].get("author", {}).get("display_name", "Unknown")
            authors = f"{first} et al." if len(authorships) > 1 else first
        else:
            authors = "Unknown"

        # Determine source type
        work_type = work.get("type", "")
        if work_type == "review":
            source_type = "review"
        elif "preprint" in work_type.lower():
            source_type = "preprint"
        else:
            source_type = "paper"

        # Confidence based on citation count
        cited = work.get("cited_by_count") or 0
        confidence = min(0.5 + (cited / 200), 1.0)

        # URL
        oa = work.get("open_access") or {}
        paper_url = oa.get("oa_url") or work.get("id") or ""
        if doi and not paper_url:
            paper_url = f"https://doi.org/{doi}"

        results.append(
            Evidence(
                source_type=source_type,
                title=title,
                authors=authors,
                year=work.get("publication_year"),
                url=paper_url,
                doi=doi,
                abstract=abstract,
                claim_used_for="",
                confidence=round(confidence, 2),
                provider="openalex",
            )
        )

    return results


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex's inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_positions)


# ---------------------------------------------------------------------------
# Semantic Scholar search
# ---------------------------------------------------------------------------


def search_semantic_scholar(query: str, max_results: int = 5) -> list[Evidence]:
    """Search Semantic Scholar for papers.

    Free tier: 100 requests per 5 minutes.
    With S2_API_KEY: higher limits.

    Docs: https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data/operation/get_graph_paper_relevance_search
    """
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": min(max_results, 10),
            "fields": "title,authors,year,abstract,url,externalIds,citationCount,openAccessPdf,publicationTypes,venue",
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    headers = {}
    if _S2_API_KEY:
        headers["x-api-key"] = _S2_API_KEY

    data = _http_get_json(url, headers=headers)
    if not data or "data" not in data:
        return []

    results = []
    for paper in data["data"][:max_results]:
        ext_ids = paper.get("externalIds") or {}
        doi = ext_ids.get("DOI") or ""

        # Authors
        authors_list = paper.get("authors") or []
        if authors_list:
            first = authors_list[0].get("name", "Unknown")
            authors = f"{first} et al." if len(authors_list) > 1 else first
        else:
            authors = "Unknown"

        # Source type
        pub_types = paper.get("publicationTypes") or []
        if "Review" in pub_types:
            source_type = "review"
        elif "Conference" in pub_types:
            source_type = "paper"
        else:
            source_type = "paper"

        # Confidence
        cited = paper.get("citationCount") or 0
        confidence = min(0.5 + (cited / 200), 1.0)

        # URL
        oa_pdf = paper.get("openAccessPdf") or {}
        paper_url = oa_pdf.get("url") or paper.get("url") or ""
        if doi and not paper_url:
            paper_url = f"https://doi.org/{doi}"

        results.append(
            Evidence(
                source_type=source_type,
                title=paper.get("title") or "",
                authors=authors,
                year=paper.get("year"),
                url=paper_url,
                doi=doi,
                abstract=(paper.get("abstract") or "")[:500],
                claim_used_for="",
                confidence=round(confidence, 2),
                provider="semantic_scholar",
            )
        )

    return results


# ---------------------------------------------------------------------------
# GBIF Literature search
# ---------------------------------------------------------------------------


def search_gbif_literature(query: str, max_results: int = 5) -> list[Evidence]:
    """Search GBIF Literature API for biodiversity papers.

    Inspired by alrobles/gbifliterature R package.
    API docs: https://www.gbif.org/developer/literature

    This is specifically valuable for ecology because GBIF curates
    papers that actually USE biodiversity data.
    """
    if not _GBIF_LIT_ENABLED:
        return []

    params = urllib.parse.urlencode(
        {
            "q": query,
            "limit": min(max_results, 20),
            "peerReview": "true",
        }
    )
    url = f"https://api.gbif.org/v1/literature/search?{params}"
    data = _http_get_json(url)
    if not data or "results" not in data:
        return []

    results = []
    for item in data["results"][:max_results]:
        doi = item.get("identifiers", {}).get("doi") or ""
        if isinstance(doi, list):
            doi = doi[0] if doi else ""

        # Authors
        authors_raw = item.get("authors") or []
        if authors_raw:
            if isinstance(authors_raw[0], dict):
                first = authors_raw[0].get(
                    "lastName", authors_raw[0].get("firstName", "Unknown")
                )
            else:
                first = str(authors_raw[0])
            authors = f"{first} et al." if len(authors_raw) > 1 else first
        else:
            authors = "Unknown"

        paper_url = ""
        websites = item.get("websites") or []
        if websites:
            paper_url = websites[0] if isinstance(websites[0], str) else ""
        if doi and not paper_url:
            paper_url = f"https://doi.org/{doi}"

        results.append(
            Evidence(
                source_type="paper",
                title=item.get("title") or "",
                authors=authors,
                year=item.get("year"),
                url=paper_url,
                doi=doi,
                abstract=(item.get("abstract") or "")[:500],
                claim_used_for="",
                confidence=0.75,  # GBIF-curated = good baseline
                provider="gbif",
            )
        )

    return results


# ---------------------------------------------------------------------------
# NCBI Entrez / PubMed search (works without API key)
# ---------------------------------------------------------------------------


def search_entrez(query: str, max_results: int = 5) -> list[Evidence]:
    """Search PubMed via NCBI Entrez E-utilities.

    Works without API key (3 req/s). With ENTREZ_API_KEY: 10 req/s.

    Docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/
    """

    # Step 1: ESearch to get PMIDs
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(max_results, 20),
        "retmode": "json",
        "tool": "ecoseek",
        "email": _ENTREZ_EMAIL,
    }
    if _ENTREZ_API_KEY:
        params["api_key"] = _ENTREZ_API_KEY
    search_params = urllib.parse.urlencode(params)
    search_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    )
    search_data = _http_get_json(search_url)
    if not search_data:
        return []

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    # Step 2: ESummary to get paper metadata
    ids = ",".join(id_list[:max_results])
    sum_params = {
        "db": "pubmed",
        "id": ids,
        "retmode": "json",
        "tool": "ecoseek",
        "email": _ENTREZ_EMAIL,
    }
    if _ENTREZ_API_KEY:
        sum_params["api_key"] = _ENTREZ_API_KEY
    summary_params = urllib.parse.urlencode(sum_params)
    summary_url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}"
    )
    summary_data = _http_get_json(summary_url)
    if not summary_data:
        return []

    results = []
    doc_results = summary_data.get("result", {})
    for pmid in id_list[:max_results]:
        item = doc_results.get(pmid, {})
        if not item or not isinstance(item, dict):
            continue

        # Extract DOI from articleids
        doi = ""
        for aid in item.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break

        # Authors
        authors_list = item.get("authors", [])
        if authors_list:
            first = authors_list[0].get("name", "Unknown")
            authors = f"{first} et al." if len(authors_list) > 1 else first
        else:
            authors = "Unknown"

        # Publication type
        pub_types = item.get("pubtype", [])
        if "Review" in pub_types:
            source_type = "review"
        else:
            source_type = "paper"

        # Year
        pub_date = item.get("pubdate", "")
        year_match = re.match(r"(\d{4})", pub_date)
        year = int(year_match.group(1)) if year_match else None

        paper_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if doi:
            paper_url = f"https://doi.org/{doi}"

        results.append(
            Evidence(
                source_type=source_type,
                title=item.get("title") or "",
                authors=authors,
                year=year,
                url=paper_url,
                doi=doi,
                abstract="",  # ESummary doesn't return abstracts; would need EFetch
                claim_used_for="",
                confidence=0.80,  # PubMed = high quality baseline
                provider="entrez",
            )
        )

    return results

# ═══════════════════════════════════════════════════════════════════════════
# CORE API — full-text open access papers (57M+ full texts)
# ═══════════════════════════════════════════════════════════════════════════

def _search_core(query: str, limit: int = 10) -> list[Evidence]:
    """Search CORE for open access papers with full text."""
    if not _CORE_ENABLED:
        return []

    params = urllib.parse.urlencode({
        "q": f"{query} AND _exists_:fullText",
        "limit": limit,
    })
    url = f"https://api.core.ac.uk/v3/search/works?{params}"

    headers = {"Accept": "application/json"}
    if _CORE_API_KEY:
        headers["Authorization"] = f"Bearer {_CORE_API_KEY}"

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=_CORE_TIMEOUT)
        data = json.loads(resp.read())
    except Exception as exc:
        logger.warning(f"CORE search failed: {exc}")
        return []

    results = []
    for hit in data.get("results", []):
        title = (hit.get("title") or "").strip()
        if len(title) < 5:
            continue
        authors_list = hit.get("authors") or []
        first = authors_list[0].get("name", "") if authors_list else ""
        authors_str = f"{first} et al." if len(authors_list) > 1 else first
        doi = hit.get("doi") or ""
        download_url = hit.get("downloadUrl") or ""
        url_source = hit.get("sourceUrl") or ""
        year = hit.get("yearPublished")
        abstract = (hit.get("abstract") or "")[:500]

        results.append(Evidence(
            source_type="paper",
            title=title,
            authors=authors_str,
            year=year,
            url=download_url or url_source,
            doi=doi,
            abstract=abstract,
            claim_used_for="",
            confidence=0.85 if download_url else 0.75,
            provider="core",
        ))

    logger.info(f"CORE: {len(results)} results for '{query[:60]}'")
    return results



# ---------------------------------------------------------------------------
# Crawl4AI — web crawling for supplementary literature (replaces Firecrawl)
# ---------------------------------------------------------------------------


def _crawl4ai_available() -> bool:
    """Return True if crawl4ai venv is installed and enabled."""
    if not _CRAWL4AI_ENABLED:
        return False
    python_bin = os.path.join(_CRAWL4AI_VENV, "bin", "python")
    return os.path.isfile(python_bin)


def search_crawl4ai(query: str, max_results: int = 3) -> list[Evidence]:
    """Use crawl4ai to crawl web pages for supplementary literature.

    Unlike API-based sources, crawl4ai can access arbitrary web pages,
    preprint servers, and journal sites that don't have public APIs.
    This replaces Firecrawl which ran out of credits.

    Strategy: crawl Google Scholar / CrossRef / DOAJ for the query,
    extract paper metadata from the crawled markdown.
    """
    import subprocess
    import re

    if not _crawl4ai_available():
        return []

    python_bin = os.path.join(_CRAWL4AI_VENV, "bin", "python")

    # Use CrossRef API (free, no auth) as a web-accessible source
    # that crawl4ai can enrich with abstracts from landing pages
    queries_to_try = [
        f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}&select=DOI,title,author,published-print,abstract,URL",
    ]

    results: list[Evidence] = []

    for crawl_url in queries_to_try[:1]:  # one URL per call to stay fast
        try:
            proc = subprocess.run(
                [python_bin, "-m", "crawl4ai.cli", "crawl", crawl_url, "-o", "md"],
                capture_output=True,
                text=True,
                timeout=_CRAWL4AI_TIMEOUT,
            )
            if proc.returncode != 0:
                logger.warning("crawl4ai failed for %s: %s", crawl_url[:80], proc.stderr[:200])
                continue

            md_output = proc.stdout.strip()
            if not md_output or len(md_output) < 50:
                continue

            # Try to parse as JSON (CrossRef returns JSON)
            try:
                # Strip markdown code fences if present
                clean = md_output
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
                data = json.loads(clean)
                items = data.get("message", {}).get("items", [])
            except (json.JSONDecodeError, ValueError):
                # If not JSON, try to extract DOIs from markdown text
                dois = re.findall(r'10\.\d{4,}/[^\s"\'>]+', md_output)
                items = [{"DOI": d} for d in dois[:max_results]]

            for item in items[:max_results]:
                doi = item.get("DOI", "")
                title_list = item.get("title", [])
                title = title_list[0] if isinstance(title_list, list) and title_list else str(title_list)

                # Authors
                authors_list = item.get("author", [])
                if authors_list:
                    first = authors_list[0].get("family", authors_list[0].get("given", "Unknown"))
                    authors = f"{first} et al." if len(authors_list) > 1 else first
                else:
                    authors = "Unknown"

                # Year
                pub = item.get("published-print", item.get("published-online", {}))
                year = None
                if pub and pub.get("date-parts"):
                    try:
                        year = pub["date-parts"][0][0]
                    except (IndexError, TypeError):
                        pass

                # Abstract (may be absent from CrossRef)
                abstract = item.get("abstract", "")
                # Strip HTML tags from CrossRef abstracts
                if abstract:
                    abstract = re.sub(r'<[^>]+>', '', abstract)[:500]

                url = item.get("URL", "")
                if doi and not url:
                    url = f"https://doi.org/{doi}"

                if title:
                    results.append(Evidence(
                        source_type="paper",
                        title=title,
                        authors=authors,
                        year=year,
                        url=url,
                        doi=doi,
                        abstract=abstract,
                        claim_used_for="",
                        confidence=0.70,  # CrossRef = good but not curated
                        provider="crawl4ai",
                    ))

        except subprocess.TimeoutExpired:
            logger.warning("crawl4ai timeout for query '%s'", query[:60])
        except Exception as exc:
            logger.warning("crawl4ai error: %s", exc)

    if results:
        logger.info("crawl4ai: %d results for '%s'", len(results), query[:60])
    return results


# ---------------------------------------------------------------------------
# EcoAgent RAG backend (via Hermes → eco_analyze on reumanlab)
# ---------------------------------------------------------------------------


def _ecoagent_available() -> bool:
    """Return True if we can reach EcoAgent via Hermes."""
    return bool(_ECOAGENT_ENABLED and _HERMES_REMOTE_URL and _HERMES_API_KEY)


def _hermes_eco_analyze(action: str, params: dict, timeout: int = 0) -> dict | None:
    """Call eco_analyze tool on reumanlab via Hermes chat completion.

    Hermes Beta has the eco_analyze tool which wraps EcoAgent's tool_server
    at localhost:8200 on reumanlab. We ask Hermes to call it for us.

    Uses the Cloudflare-safe HTTP client (curl fallback) to avoid
    Cloudflare Bot Fight Mode blocking from inside Docker containers.
    """
    from .http_client import http_post_json

    prompt = (
        f"Use the eco_analyze tool to run action={action!r} with these params: "
        f"{json.dumps(params, ensure_ascii=False)}. "
        f"Return the raw JSON result only, no commentary."
    )
    payload = {
        "model": "hermes-agent",
        "messages": [
            {
                "role": "system",
                "content": "You have the eco_analyze tool. Use it to execute ecological analysis actions on EcoAgent. Return the tool result as-is.",
            },
            {"role": "user", "content": prompt},
        ],
    }

    headers = {"Authorization": f"Bearer {_HERMES_API_KEY}"}

    try:
        data = http_post_json(
            f"{_HERMES_REMOTE_URL}/v1/chat/completions",
            payload,
            headers,
            timeout=timeout or _ECOAGENT_TIMEOUT,
        )
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return {"raw_text": content}
    except Exception as exc:
        logger.warning("ecoagent via hermes failed (%s): %s", action, exc)
        return None


def search_ecoagent_literature(query: str, max_results: int = 5) -> list[Evidence]:
    """Search EcoAgent's GBIF literature + vector store via Hermes.

    Calls two ecoagent tools:
      1. query_gbif_literature — structured GBIF literature API search
      2. search_literature — semantic vector search over indexed papers

    Results are merged and returned as Evidence objects.
    """
    if not _ecoagent_available():
        return []

    results: list[Evidence] = []

    # 1. GBIF Literature via EcoAgent (structured, curated)
    gbif_data = _hermes_eco_analyze(
        "query_gbif_literature",
        {"args": {"query": query, "limit": max_results}},
    )
    if gbif_data and isinstance(gbif_data, dict):
        result_text = ""
        if "result" in gbif_data:
            r = gbif_data["result"]
            result_text = r.get("result", "") if isinstance(r, dict) else str(r)
        elif "raw_text" in gbif_data:
            result_text = gbif_data["raw_text"]

        # Parse structured results from the text
        if result_text:
            for block in result_text.split("\n\n"):
                block = block.strip()
                if not block or "Title:" not in block:
                    continue
                title = ""
                year = None
                doi = ""
                topics = ""
                for line in block.split("\n"):
                    line = line.strip()
                    if line.startswith("Title:"):
                        title = line[6:].strip()
                    elif line.startswith("Year:"):
                        try:
                            year = int(line[5:].strip())
                        except ValueError:
                            pass
                    elif line.startswith("DOI:"):
                        doi = line[4:].strip()
                    elif line.startswith("Topics:"):
                        topics = line[7:].strip()
                if title:
                    url = f"https://doi.org/{doi}" if doi else ""
                    results.append(
                        Evidence(
                            source_type="paper",
                            title=title,
                            authors="",
                            year=year,
                            url=url,
                            doi=doi,
                            abstract=topics,
                            claim_used_for="",
                            confidence=0.80,
                            provider="ecoagent:gbif",
                        )
                    )

    # 2. Cofid host-parasite interactions (if query is relevant)
    query_lower = query.lower()
    cofid_keywords = (
        "host",
        "parasite",
        "parasit",
        "infection",
        "pathogen",
        "cofid",
        "helminth",
    )
    if any(kw in query_lower for kw in cofid_keywords):
        cofid_data = _hermes_eco_analyze(
            "query_cofid",
            {"args": {"query": query, "limit": max_results}},
        )
        if cofid_data and isinstance(cofid_data, dict):
            result_text = ""
            if "result" in cofid_data:
                r = cofid_data["result"]
                result_text = r.get("result", "") if isinstance(r, dict) else str(r)
            elif "raw_text" in cofid_data:
                result_text = cofid_data["raw_text"]
            if result_text and len(result_text) > 20:
                results.append(
                    Evidence(
                        source_type="web_reference",
                        title=f"CoFID host-parasite interactions: {query[:60]}",
                        authors="CoFID Database",
                        year=2024,
                        url="https://github.com/alrobles/cofid",
                        doi="",
                        abstract=result_text[:500],
                        claim_used_for="",
                        confidence=0.85,
                        provider="ecoagent:cofid",
                    )
                )

    logger.info("ecoagent search: %d results for '%s'", len(results), query[:60])
    return results


# ---------------------------------------------------------------------------
# Local-first search sources (user papers + cluster FTS5 via Hermes)
# ---------------------------------------------------------------------------


def search_user_papers(query: str, max_results: int = 5) -> list[Evidence]:
    """Search user-uploaded documents in local litdb."""
    try:
        from .litdb import search_user_papers as _search_user

        hits = _search_user(query, limit=max_results)
        results = []
        for h in hits:
            results.append(
                Evidence(
                    source_type="user_upload",
                    title=h.get("title", h.get("filename", "")),
                    authors=h.get("authors", ""),
                    year=h.get("year"),
                    url="",
                    doi="",
                    abstract=h.get("snippet", "")[:500],
                    claim_used_for="",
                    confidence=0.95,
                    provider="user_upload",
                )
            )
        return results
    except Exception as exc:
        logger.debug("user_papers search failed: %s", exc)
        return []


def search_cluster_pubmed(query: str, max_results: int = 5) -> list[Evidence]:
    """Search the PubMed FTS5 index on the cluster via Hermes.

    The cluster has a local SQLite FTS5 index at
    /home/a474r867/work/pubmed/index/ with ~36M articles.
    We ask Hermes to run the search_pubmed.py script.
    """
    if not _HERMES_API_KEY:
        return []

    try:
        from .http_client import http_post_json

        resp = http_post_json(
            f"{_HERMES_REMOTE_URL}/v1/chat/completions",
            body={
                "model": "hermes-agent",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Run this command and return ONLY the JSON output, no explanation:\n"
                            f"python3 /home/a474r867/work/Github/ecoseek-litdump/scripts/search_pubmed.py "
                            f'"{query}" --limit {max_results} --json'
                        ),
                    }
                ],
            },
            headers={"Authorization": f"Bearer {_HERMES_API_KEY}"},
            timeout=20,
        )
        if not resp:
            return []

        content = ""
        choices = resp.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        # Try to parse JSON from the response
        results = _parse_cluster_results(content, "pubmed_local")
        return results[:max_results]
    except Exception as exc:
        logger.debug("cluster pubmed search failed: %s", exc)
        return []


def search_cluster_gbif_lit(query: str, max_results: int = 5) -> list[Evidence]:
    """Search the GBIF Literature FTS5 index on the cluster via Hermes."""
    if not _HERMES_API_KEY:
        return []

    try:
        from .http_client import http_post_json

        resp = http_post_json(
            f"{_HERMES_REMOTE_URL}/v1/chat/completions",
            body={
                "model": "hermes-agent",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Run this command and return ONLY the JSON output, no explanation:\n"
                            f"python3 /home/a474r867/work/Github/ecoseek-litdump/scripts/search_gbif_literature.py "
                            f'"{query}" --limit {max_results} --json'
                        ),
                    }
                ],
            },
            headers={"Authorization": f"Bearer {_HERMES_API_KEY}"},
            timeout=20,
        )
        if not resp:
            return []

        content = ""
        choices = resp.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        results = _parse_cluster_results(content, "gbif_lit_local")
        return results[:max_results]
    except Exception as exc:
        logger.debug("cluster gbif_lit search failed: %s", exc)
        return []


def _parse_cluster_results(content: str, provider: str) -> list[Evidence]:
    """Parse JSON results from cluster search scripts into Evidence list."""
    if not content:
        return []

    # Try to extract JSON from the response (may be wrapped in markdown)
    json_str = content
    if "```" in content:
        import re as _re

        match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, _re.DOTALL)
        if match:
            json_str = match.group(1)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Try to find array in content
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return []
        else:
            return []

    if isinstance(data, dict):
        data = data.get("results", data.get("papers", []))
    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        results.append(
            Evidence(
                source_type="paper",
                title=str(item.get("title", ""))[:200],
                authors=str(item.get("authors", ""))[:200],
                year=item.get("year"),
                url=str(item.get("url", item.get("doi_url", "")))[:300],
                doi=str(item.get("doi", ""))[:100],
                abstract=str(item.get("abstract", ""))[:500],
                claim_used_for="",
                confidence=0.8,
                provider=provider,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Multi-source retrieval orchestrator
# ---------------------------------------------------------------------------


def retrieve_literature(
    query: str,
    subquestions: list[str] | None = None,
    tier: str = "B",
    max_per_source: int = 3,
) -> dict:
    """Retrieve scientific literature from multiple sources.

    Parameters
    ----------
    query : str
        Main search query (usually the user's question).
    subquestions : list[str], optional
        Subquestions from the task object for targeted retrieval.
    tier : str
        "A" = fast (OpenAlex only, 2-3 results)
        "B" = scientific (OpenAlex + Semantic Scholar + GBIF + Entrez, 5-10 results)
    max_per_source : int
        Maximum results per source.

    Returns
    -------
    dict
        Structured evidence with sources, retrieval_notes, and provider stats.
    """
    if tier == "A":
        max_per_source = min(max_per_source, 2)
    else:
        max_per_source = min(max_per_source, 5)

    all_evidence: list[Evidence] = []
    provider_stats: dict[str, int] = {}
    errors: list[str] = []

    # --- Priority 1: User-uploaded documents (highest priority, instant) ---
    try:
        user_hits = search_user_papers(query, max_results=max_per_source)
        if user_hits:
            all_evidence.extend(user_hits)
            provider_stats["user_upload"] = len(user_hits)
            logger.info("user_papers: %d results for '%s'", len(user_hits), query[:60])
    except Exception as exc:
        logger.debug("user_papers search error: %s", exc)

    # --- Priority 2: Local literature cache (litdb) ---
    try:
        from .litdb import search as litdb_search

        cached = litdb_search(query, limit=max_per_source * 2)
        for paper in cached:
            all_evidence.append(
                Evidence(
                    source_type=paper.get("source_type", "paper"),
                    title=paper.get("title", ""),
                    authors=paper.get("authors", ""),
                    year=paper.get("year"),
                    url=paper.get("url", ""),
                    doi=paper.get("doi", ""),
                    abstract=paper.get("abstract", ""),
                    claim_used_for="",
                    confidence=paper.get("confidence", 0.7),
                    provider=f"cache:{paper.get('provider', '')}",
                )
            )
        if cached:
            provider_stats["cache"] = len(cached)
            logger.info(
                "litdb cache hit: %d papers for query '%s'", len(cached), query[:60]
            )
    except Exception as exc:
        logger.debug("litdb cache miss or error: %s", exc)

    # Build search queries
    queries = [query]
    if subquestions and tier == "B":
        # Add most specific subquestions for broader coverage
        queries.extend(subquestions[:2])

    # Import tracing (no-op when Phoenix is not configured)

    # Build a minimal trace context for retrieval spans
    _tctx: dict = {"protocol_id": "retrieval"}

    # --- Parallel retrieval of all sources (ThreadPoolExecutor) ---
    # Previously sequential (~14s). Now concurrent (~3-4s, limited by slowest).
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _search_source(
        name: str, fn, q: str, max_r: int
    ) -> tuple[str, list[Evidence], str | None]:
        """Wrapper that returns (source_name, results, error_or_None)."""
        try:
            return (name, fn(q, max_results=max_r), None)
        except Exception as exc:
            return (name, [], str(exc)[:200])

    # Build list of search tasks
    search_tasks: list[tuple[str, object, str, int]] = []

    # Source 1: OpenAlex (always, primary) — submit for each query variant
    for q in queries[:2]:
        search_tasks.append(("openalex", search_openalex, q, max_per_source))

    # Source 2-4: Tier B sources
    if tier == "B":
        search_tasks.append(
            ("semantic_scholar", search_semantic_scholar, query, max_per_source)
        )
        if _GBIF_LIT_ENABLED:
            search_tasks.append(("gbif", search_gbif_literature, query, max_per_source))
        search_tasks.append(("entrez", search_entrez, query, max_per_source))

    # Source 5: CORE — full-text open access papers (57M+)
    if _CORE_ENABLED:
        search_tasks.append(("core", search_core, query, max_per_source))

    # Source 5b: Crawl4AI — web crawling (replaces Firecrawl)
    if _crawl4ai_available():
        search_tasks.append(("crawl4ai", search_crawl4ai, query, max_per_source))

    # Source 6: EcoAgent RAG (via Hermes)
    if _ecoagent_available():
        search_tasks.append(
            ("ecoagent", search_ecoagent_literature, query, max_per_source)
        )

    # Source 6-7: Cluster FTS5 indices (PubMed ~36M + GBIF Lit ~61K)
    if tier == "B" and _HERMES_API_KEY:
        search_tasks.append(
            ("pubmed_local", search_cluster_pubmed, query, max_per_source)
        )
        search_tasks.append(
            ("gbif_lit_local", search_cluster_gbif_lit, query, max_per_source)
        )

    # Execute all searches in parallel (max 10s total timeout)
    with ThreadPoolExecutor(max_workers=min(len(search_tasks), 6)) as pool:
        futures = {
            pool.submit(_search_source, name, fn, q, max_r): name
            for name, fn, q, max_r in search_tasks
        }
        for future in as_completed(futures, timeout=15):
            source_name = futures[future]
            try:
                name, results, err = future.result()
                if err:
                    errors.append(f"{name}: {err}")
                    logger.warning("%s search failed: %s", name, err)
                elif results:
                    all_evidence.extend(results)
                    provider_stats[name] = provider_stats.get(name, 0) + len(results)
                    logger.info("%s returned %d results", name, len(results))
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")
                logger.warning("%s future failed: %s", source_name, exc)

    # --- Deduplicate by DOI ---
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    unique_evidence: list[Evidence] = []

    for ev in all_evidence:
        key_doi = ev.doi.lower().strip() if ev.doi else ""
        key_title = ev.title.lower().strip()[:80] if ev.title else ""

        if key_doi and key_doi in seen_dois:
            continue
        if key_title and key_title in seen_titles:
            continue

        if key_doi:
            seen_dois.add(key_doi)
        if key_title:
            seen_titles.add(key_title)
        unique_evidence.append(ev)

    # Sort by confidence (highest first)
    unique_evidence.sort(key=lambda e: e.confidence, reverse=True)

    # --- Store new API results in local literature cache ---
    try:
        from .litdb import store_many

        api_papers = [
            evidence_to_dict(e)
            for e in unique_evidence
            if not e.provider.startswith("cache:")
        ]
        if api_papers:
            stored = store_many(api_papers)
            if stored:
                logger.info("litdb cached %d new papers", stored)
    except Exception as exc:
        logger.debug("litdb store failed: %s", exc)

    # Ensure we have at least some diversity of source types
    # Protocol spec: at least 1 contrast/critique source when available
    has_review = any(e.source_type == "review" for e in unique_evidence)

    # --- LACS re-ranking: score evidence by domain relevance ---
    sources_dicts = [evidence_to_dict(e) for e in unique_evidence]
    lacs_applied = False
    lacs_domain = ""
    try:
        from .lacs_classifier import rerank_evidence, _LACS_ENABLED

        if _LACS_ENABLED and sources_dicts:
            lacs_domain = _detect_domain(query)
            sources_dicts = rerank_evidence(sources_dicts, domain=lacs_domain)
            lacs_applied = True
            provider_stats["lacs_rerank"] = len(sources_dicts)
            logger.info(
                "LACS re-ranked %d sources (domain=%s)", len(sources_dicts), lacs_domain
            )
    except Exception as exc:
        logger.debug("LACS re-ranking skipped: %s", exc)

    return {
        "sources": sources_dicts,
        "total_found": len(unique_evidence),
        "provider_stats": provider_stats,
        "has_review_source": has_review,
        "tier": tier,
        "queries_used": queries[:3],
        "errors": errors if errors else None,
        "lacs_applied": lacs_applied,
        "lacs_domain": lacs_domain,
        "retrieval_notes": (
            f"Retrieved {len(unique_evidence)} unique sources from "
            f"{', '.join(provider_stats.keys())}. "
            f"{'LACS re-ranked by ' + lacs_domain + ' relevance. ' if lacs_applied else ''}"
            f"{'Includes review/meta-analysis.' if has_review else 'No review papers found — consider broadening search.'}"
        ),
    }


def _detect_domain(query: str) -> str:
    """Heuristic to detect the best LACS domain for a query."""
    q = query.lower()
    host_parasite_kw = {
        "host",
        "parasite",
        "pathogen",
        "virus",
        "zoonotic",
        "infection",
        "reservoir",
        "hantavirus",
        "spillover",
        "vector",
        "disease",
    }
    niche_kw = {
        "niche",
        "distribution",
        "sdm",
        "maxent",
        "bioclim",
        "chelsa",
        "occurrence",
        "suitability",
        "habitat",
        "climate",
    }

    hp_hits = sum(1 for kw in host_parasite_kw if kw in q)
    nm_hits = sum(1 for kw in niche_kw if kw in q)

    if hp_hits > nm_hits:
        return "host-parasite"
    if nm_hits > hp_hits:
        return "niche-modeling"
    return "biodiversity"
