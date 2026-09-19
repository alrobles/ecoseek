#!/usr/bin/env python3
"""meili_seed.py — Seed the EcoSeek Meilisearch `gbif_literature` index.

Idempotent bootstrap for the optional `search` compose profile:

    docker compose --profile search up -d
    python3 scripts/meili_seed.py                 # host run (localhost:7700)
    MEILI_URL=http://meilisearch:7700 python3 scripts/meili_seed.py

What it does:
  1. Waits for Meilisearch /health.
  2. Creates the index (primaryKey=id) if missing.
  3. Applies the production index settings (searchable/filterable/sortable).
  4. If the index has fewer than --min-docs documents, downloads ALL papers
     from the public GBIF Literature API (no auth) and bulk-indexes them.
     Skipped entirely when the index is already populated.

Fields populated per document:
    id, title, abstract, year, doi, keywords, has_abstract,
    countries_of_coverage, country_names_coverage,
    countries_of_researcher, country_names_researcher,
    language, topics, gbif_taxon_key, gbif_higher_taxon_key,
    source, publisher, literature_type, open_access, peer_review

Note: the production index also carries `taxonomic_groups` and
`relevance_score` from a later enrichment pass (ecoseek-litdump). A fresh
seed leaves them empty; the attributes are still declared filterable so
queries that use them simply match nothing until enrichment runs.

Fast path (exact copy instead of re-downloading):
    docker cp gbif_literature.dump meilisearch:/tmp/
    docker exec meilisearch meilisearch --import-dump /tmp/gbif_literature.dump
    # or relaunch the container with --import-dump
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

GBIF_API = "https://api.gbif.org/v1/literature/search"
PAGE_LIMIT = 1000
BATCH_SIZE = 1000

INDEX_SETTINGS = {
    "searchableAttributes": ["title", "abstract", "keywords"],
    "filterableAttributes": [
        "year",
        "has_abstract",
        "relevance_score",
        "country_names_coverage",
        "taxonomic_groups",
        "language",
        "topics",
        "literature_type",
        "open_access",
        "peer_review",
    ],
    "sortableAttributes": ["relevance_score", "year"],
    "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
}

# ISO 3166-1 alpha-2 → country name (same mapping as
# ecoseek-litdump/scripts/enrich_meilisearch.py — metasearch geo-filters on it)
COUNTRY_NAMES = {
    "ES": "Spain", "MX": "Mexico", "CO": "Colombia", "BR": "Brazil",
    "AR": "Argentina", "PE": "Peru", "CL": "Chile", "EC": "Ecuador",
    "VE": "Venezuela", "BO": "Bolivia", "CR": "Costa Rica", "PA": "Panama",
    "GT": "Guatemala", "HN": "Honduras", "NI": "Nicaragua", "CU": "Cuba",
    "PY": "Paraguay", "UY": "Uruguay", "DO": "Dominican Republic",
    "US": "United States", "CA": "Canada", "GB": "United Kingdom",
    "DE": "Germany", "FR": "France", "IT": "Italy", "PT": "Portugal",
    "NL": "Netherlands", "SE": "Sweden", "NO": "Norway", "FI": "Finland",
    "DK": "Denmark", "CH": "Switzerland", "AT": "Austria", "BE": "Belgium",
    "PL": "Poland", "CZ": "Czech Republic", "RO": "Romania", "HU": "Hungary",
    "GR": "Greece", "TR": "Turkey", "RU": "Russia", "CN": "China",
    "JP": "Japan", "KR": "South Korea", "IN": "India", "AU": "Australia",
    "NZ": "New Zealand", "ZA": "South Africa", "KE": "Kenya", "TZ": "Tanzania",
    "NG": "Nigeria", "EG": "Egypt", "MA": "Morocco", "DZ": "Algeria",
    "GH": "Ghana", "CM": "Cameroon", "ET": "Ethiopia", "UG": "Uganda",
    "SN": "Senegal", "ML": "Mali", "BF": "Burkina Faso", "NE": "Niger",
    "TD": "Chad", "SD": "Sudan", "MG": "Madagascar", "MZ": "Mozambique",
    "ZW": "Zimbabwe", "BW": "Botswana", "NA": "Namibia", "ZM": "Zambia",
    "AO": "Angola", "CD": "DR Congo", "CG": "Congo", "GA": "Gabon",
    "GQ": "Equatorial Guinea", "RW": "Rwanda", "BI": "Burundi",
    "SS": "South Sudan", "ER": "Eritrea", "DJ": "Djibouti", "SO": "Somalia",
    "LY": "Libya", "TN": "Tunisia", "JO": "Jordan", "LB": "Lebanon",
    "SY": "Syria", "IQ": "Iraq", "IR": "Iran", "SA": "Saudi Arabia",
    "AE": "UAE", "OM": "Oman", "YE": "Yemen", "AF": "Afghanistan",
    "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka", "NP": "Nepal",
    "MM": "Myanmar", "TH": "Thailand", "VN": "Vietnam", "KH": "Cambodia",
    "LA": "Laos", "MY": "Malaysia", "ID": "Indonesia", "PH": "Philippines",
    "TW": "Taiwan", "MN": "Mongolia", "KZ": "Kazakhstan", "UZ": "Uzbekistan",
    "GY": "Guyana", "SR": "Suriname", "GF": "French Guiana",
    "BZ": "Belize", "SV": "El Salvador", "JM": "Jamaica", "HT": "Haiti",
    "TT": "Trinidad and Tobago", "PR": "Puerto Rico",
    "IS": "Iceland", "IE": "Ireland", "LU": "Luxembourg",
    "SK": "Slovakia", "HR": "Croatia", "RS": "Serbia", "BG": "Bulgaria",
    "UA": "Ukraine", "BY": "Belarus", "LT": "Lithuania", "LV": "Latvia",
    "EE": "Estonia", "SI": "Slovenia", "BA": "Bosnia", "MK": "North Macedonia",
    "AL": "Albania", "ME": "Montenegro", "XK": "Kosovo", "MD": "Moldova",
    "GE": "Georgia", "AM": "Armenia", "AZ": "Azerbaijan",
}


def http(method: str, url: str, payload=None, timeout: int = 60):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def wait_healthy(meili_url: str, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            http("GET", f"{meili_url}/health", timeout=5)
            print("[seed] Meilisearch healthy")
            return
        except Exception:
            time.sleep(2)
    sys.exit("[seed] Meilisearch not healthy after %ds" % timeout_s)


def ensure_index(meili_url: str, index: str) -> None:
    try:
        http("GET", f"{meili_url}/indexes/{index}", timeout=10)
        print(f"[seed] Index '{index}' exists")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        http("POST", f"{meili_url}/indexes", {"uid": index, "primaryKey": "id"})
        print(f"[seed] Created index '{index}' (primaryKey=id)")


def apply_settings(meili_url: str, index: str) -> None:
    res = http(
        "PATCH", f"{meili_url}/indexes/{index}/settings", INDEX_SETTINGS, timeout=30
    )
    print(f"[seed] Settings applied (task {res.get('taskUid', '?')})")


def doc_count(meili_url: str, index: str) -> int:
    stats = http("GET", f"{meili_url}/indexes/{index}/stats", timeout=10)
    return int(stats.get("numberOfDocuments", 0))


def fetch_gbif_page(offset: int) -> dict:
    url = f"{GBIF_API}?limit={PAGE_LIMIT}&offset={offset}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "EcoSeek-Seed/1.0 (ecoseek.org)", "Accept": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def to_doc(rec: dict) -> dict:
    coverage = rec.get("countriesOfCoverage", []) or []
    researcher = rec.get("countriesOfResearcher", []) or []
    identifiers = rec.get("identifiers", {})
    authors = rec.get("authors", [])
    if isinstance(authors, list):
        names = []
        for a in authors:
            if isinstance(a, dict):
                names.append(" ".join(p for p in (a.get("lastName"), a.get("firstName")) if p))
            else:
                names.append(str(a))
        authors = "; ".join(names)
    keywords = rec.get("keywords", [])
    return {
        "id": str(rec.get("id", "")),
        "title": rec.get("title", ""),
        "abstract": rec.get("abstract", ""),
        "authors": authors,
        "year": rec.get("year", ""),
        "doi": identifiers.get("doi", "") if isinstance(identifiers, dict) else "",
        "keywords": "; ".join(keywords) if isinstance(keywords, list) else str(keywords or ""),
        "has_abstract": bool(rec.get("abstract")),
        "countries_of_coverage": coverage,
        "country_names_coverage": [COUNTRY_NAMES.get(c, c) for c in coverage if c],
        "countries_of_researcher": researcher,
        "country_names_researcher": [COUNTRY_NAMES.get(c, c) for c in researcher if c],
        "language": rec.get("language", ""),
        "topics": rec.get("topics", []),
        "gbif_taxon_key": rec.get("gbifTaxonKey", ""),
        "gbif_higher_taxon_key": rec.get("gbifHigherTaxonKey", ""),
        "source": rec.get("source", ""),
        "publisher": rec.get("publisher", ""),
        "literature_type": rec.get("literatureType", ""),
        "open_access": rec.get("openAccess", False),
        "peer_review": rec.get("peerReview", False),
    }


def seed_documents(meili_url: str, index: str) -> int:
    offset = 0
    total = None
    indexed = 0
    while True:
        data = fetch_gbif_page(offset)
        results = data.get("results", [])
        if total is None:
            total = data.get("count", 0)
            print(f"[seed] GBIF API reports {total} papers")
        if not results:
            break
        docs = [to_doc(r) for r in results]
        res = http(
            "PUT",
            f"{meili_url}/indexes/{index}/documents?primaryKey=id",
            docs,
            timeout=300,
        )
        indexed += len(docs)
        offset += len(results)
        print(f"[seed] Indexed {indexed}/{total} (task {res.get('taskUid', '?')})")
        if data.get("endOfRecords", True) or offset >= (total or 0):
            break
        time.sleep(0.5)  # be nice to the public API
    return indexed


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed Meilisearch gbif_literature index")
    ap.add_argument("--meili-url", default=os.environ.get("MEILI_URL", "http://localhost:7700"))
    ap.add_argument("--index", default=os.environ.get("MEILI_INDEX", "gbif_literature"))
    ap.add_argument("--min-docs", type=int, default=1000,
                    help="Skip data load when index already has >= this many docs")
    ap.add_argument("--settings-only", action="store_true",
                    help="Create index + apply settings, skip data load")
    ap.add_argument("--force", action="store_true",
                    help="Re-index even when --min-docs is already met")
    args = ap.parse_args()

    meili = args.meili_url.rstrip("/")
    wait_healthy(meili)
    ensure_index(meili, args.index)
    apply_settings(meili, args.index)

    existing = doc_count(meili, args.index)
    print(f"[seed] Index currently has {existing} documents")
    if args.settings_only:
        return
    if existing >= args.min_docs and not args.force:
        print(f"[seed] >= --min-docs ({args.min_docs}); skipping data load")
        return

    n = seed_documents(meili, args.index)
    print(f"[seed] Done — {n} documents submitted for indexing")


if __name__ == "__main__":
    main()
