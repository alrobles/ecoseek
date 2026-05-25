"""Literature retrieval for DiDAL Protocol v2.

Provides multi-source scientific literature search with normalized output.
Sources (in priority order):
  1. OpenAlex  — 250M+ works, open, no auth required (default Tier A & B)
  2. Semantic Scholar — 200M+ papers, abstracts + citation context
  3. GBIF Literature — biodiversity-specific papers via api.gbif.org
  4. NCBI Entrez / PubMed — BYOK via ENTREZ_API_KEY (optional)

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
_GBIF_LIT_ENABLED = os.environ.get("GBIF_LITERATURE_ENABLED", "true").lower() in ("true", "1", "yes")
_REQUEST_TIMEOUT = int(os.environ.get("RETRIEVAL_TIMEOUT", "15"))

# ---------------------------------------------------------------------------
# Normalized evidence schema
# ---------------------------------------------------------------------------

class Evidence(NamedTuple):
    source_type: str       # "paper" | "review" | "web_reference" | "preprint"
    title: str
    authors: str           # first author et al.
    year: int | None
    url: str
    doi: str
    abstract: str
    claim_used_for: str    # filled later by the protocol
    confidence: float      # 0.0 - 1.0
    provider: str          # "openalex" | "semantic_scholar" | "gbif" | "entrez"


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

def _http_get_json(url: str, headers: dict | None = None, timeout: int = 0) -> dict | list | None:
    """Simple GET → JSON with error handling."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout or _REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
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
    params = urllib.parse.urlencode({
        "search": query,
        "per_page": min(max_results, 25),
        "select": "id,doi,title,authorships,publication_year,type,cited_by_count,open_access,abstract_inverted_index",
        "mailto": _OPENALEX_MAILTO,
    })
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

        results.append(Evidence(
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
        ))

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
    params = urllib.parse.urlencode({
        "query": query,
        "limit": min(max_results, 10),
        "fields": "title,authors,year,abstract,url,externalIds,citationCount,openAccessPdf,publicationTypes,venue",
    })
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

        results.append(Evidence(
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
        ))

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

    params = urllib.parse.urlencode({
        "q": query,
        "limit": min(max_results, 20),
        "peerReview": "true",
    })
    url = f"https://api.gbif.org/v1/literature/search?{params}"
    data = _http_get_json(url)
    if not data or "results" not in data:
        return []

    results = []
    for item in data["results"][:max_results]:
        doi = (item.get("identifiers", {}).get("doi") or "")
        if isinstance(doi, list):
            doi = doi[0] if doi else ""

        # Authors
        authors_raw = item.get("authors") or []
        if authors_raw:
            if isinstance(authors_raw[0], dict):
                first = authors_raw[0].get("lastName", authors_raw[0].get("firstName", "Unknown"))
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

        results.append(Evidence(
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
        ))

    return results


# ---------------------------------------------------------------------------
# NCBI Entrez / PubMed search (BYOK)
# ---------------------------------------------------------------------------

def search_entrez(query: str, max_results: int = 5) -> list[Evidence]:
    """Search PubMed via NCBI Entrez E-utilities.

    Requires ENTREZ_API_KEY env var (free from NCBI).
    Without key: 3 req/s. With key: 10 req/s.

    Docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/
    """
    if not _ENTREZ_API_KEY:
        return []

    # Step 1: ESearch to get PMIDs
    search_params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": min(max_results, 20),
        "retmode": "json",
        "api_key": _ENTREZ_API_KEY,
        "tool": "ecoseek",
        "email": _ENTREZ_EMAIL,
    })
    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    search_data = _http_get_json(search_url)
    if not search_data:
        return []

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    # Step 2: ESummary to get paper metadata
    ids = ",".join(id_list[:max_results])
    summary_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ids,
        "retmode": "json",
        "api_key": _ENTREZ_API_KEY,
        "tool": "ecoseek",
        "email": _ENTREZ_EMAIL,
    })
    summary_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}"
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

        results.append(Evidence(
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
        ))

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

    # Build search queries
    queries = [query]
    if subquestions and tier == "B":
        # Add most specific subquestions for broader coverage
        queries.extend(subquestions[:2])

    # Import tracing (no-op when Phoenix is not configured)
    from .tracing import trace_retrieval_source

    # Build a minimal trace context for retrieval spans
    _tctx: dict = {"protocol_id": "retrieval"}

    # --- Source 1: OpenAlex (always, primary) ---
    for q in queries[:2]:
        with trace_retrieval_source("openalex", _tctx, q) as src_ctx:
            try:
                results = search_openalex(q, max_results=max_per_source)
                all_evidence.extend(results)
                provider_stats["openalex"] = provider_stats.get("openalex", 0) + len(results)
                src_ctx["results_count"] = len(results)
            except Exception as exc:
                errors.append(f"openalex: {exc}")
                src_ctx["error"] = str(exc)[:200]
                logger.warning("OpenAlex search failed: %s", exc)

    # --- Source 2: Semantic Scholar (Tier B only) ---
    if tier == "B":
        with trace_retrieval_source("semantic_scholar", _tctx, query) as src_ctx:
            try:
                results = search_semantic_scholar(query, max_results=max_per_source)
                all_evidence.extend(results)
                provider_stats["semantic_scholar"] = len(results)
                src_ctx["results_count"] = len(results)
            except Exception as exc:
                errors.append(f"semantic_scholar: {exc}")
                src_ctx["error"] = str(exc)[:200]
                logger.warning("Semantic Scholar search failed: %s", exc)

    # --- Source 3: GBIF Literature (Tier B, ecology-specific) ---
    if tier == "B" and _GBIF_LIT_ENABLED:
        with trace_retrieval_source("gbif", _tctx, query) as src_ctx:
            try:
                results = search_gbif_literature(query, max_results=max_per_source)
                all_evidence.extend(results)
                provider_stats["gbif"] = len(results)
                src_ctx["results_count"] = len(results)
            except Exception as exc:
                errors.append(f"gbif: {exc}")
                src_ctx["error"] = str(exc)[:200]
                logger.warning("GBIF Literature search failed: %s", exc)

    # --- Source 4: Entrez/PubMed (Tier B, BYOK) ---
    if tier == "B" and _ENTREZ_API_KEY:
        with trace_retrieval_source("entrez", _tctx, query) as src_ctx:
            try:
                results = search_entrez(query, max_results=max_per_source)
                all_evidence.extend(results)
                provider_stats["entrez"] = len(results)
                src_ctx["results_count"] = len(results)
            except Exception as exc:
                errors.append(f"entrez: {exc}")
                src_ctx["error"] = str(exc)[:200]
                logger.warning("Entrez search failed: %s", exc)

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

    # Ensure we have at least some diversity of source types
    # Protocol spec: at least 1 contrast/critique source when available
    has_review = any(e.source_type == "review" for e in unique_evidence)

    return {
        "sources": [evidence_to_dict(e) for e in unique_evidence],
        "total_found": len(unique_evidence),
        "provider_stats": provider_stats,
        "has_review_source": has_review,
        "tier": tier,
        "queries_used": queries[:3],
        "errors": errors if errors else None,
        "retrieval_notes": (
            f"Retrieved {len(unique_evidence)} unique sources from "
            f"{', '.join(provider_stats.keys())}. "
            f"{'Includes review/meta-analysis.' if has_review else 'No review papers found — consider broadening search.'}"
        ),
    }
