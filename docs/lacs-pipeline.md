# LACS Pipeline: Literature Classification for EcoSeek

## Overview

The LACS (Literature Automated Classification System) pipeline is the
core data engine behind ecoSeek's literature intelligence. It uses
PU-learning to classify 36M PubMed abstracts by ecological relevance,
feeding the Meilisearch index that powers Emily's literature retrieval.

## How It Fits in EcoSeek

```
┌─────────────────────────────────────────────────────────┐
│                    ecoSeek Platform                      │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Emily UI │───▶│ EcoAgent │───▶│ Meilisearch      │  │
│  │ (query)  │    │ (reason) │    │ pubmed_ecology   │  │
│  └──────────┘    └──────────┘    │ (~500K-2M papers)│  │
│                                  └────────▲─────────┘  │
│                                           │             │
└───────────────────────────────────────────┼─────────────┘
                                            │
┌───────────────────────────────────────────┼─────────────┐
│              LACS Scoring Pipeline         │             │
│                                           │             │
│  ┌──────────┐    ┌──────────┐    ┌────────┴─────────┐  │
│  │ GBIF 62K │───▶│ LACS     │───▶│ Score PubMed     │  │
│  │ (pos.)   │    │ Model    │    │ 36M abstracts    │  │
│  └──────────┘    │ train    │    │ score >= 0.8     │  │
│  ┌──────────┐    └──────────┘    └──────────────────┘  │
│  │ PubMed   │                                          │
│  │ 30K unl. │                                          │
│  └──────────┘                                          │
└─────────────────────────────────────────────────────────┘
```

## Integration Points

### Emily Plugin (lacs_classifier.py)

The `emily/plugins/ecoseek/lacs_classifier.py` module provides:

- `classify_literature` tool: Scores abstracts by domain relevance
- `train_lacs_model` tool: Trains new domain models on HPC
- Remote mode: Sends abstracts to HPC via Hermes → R in Apptainer
- Local mode: Keyword-frequency heuristic fallback (3 domains)

### DiDAL Protocol (retrieval.py)

The retrieval layer uses LACS for re-ranking:
1. BM25/FTS5 initial retrieval from PubMed + GBIF
2. LACS domain scoring (ecology-biodiversity)
3. Combined score = BM25 * 0.4 + LACS * 0.6
4. Results above threshold feed into Emily's reasoning

### Meilisearch Index

- **Index**: `pubmed_ecology`
- **Documents**: ~500K-2M (papers with LACS score >= 0.8)
- **Searchable**: title, abstract, authors, journal
- **Filterable**: year, score, decade, domain
- **Port**: 7700 (Meilisearch on cluster private IP)

## Domains

| Domain | Training Data | Status |
|--------|---------------|--------|
| host-parasite | GMPD + ZOVER | Production (existing) |
| niche-modeling | SDM literature | Production (existing) |
| biodiversity | GBIF general | Production (existing) |
| **ecology-biodiversity** | **GBIF 62K + PubMed 30K** | **NEW — this pipeline** |

## Deployment

The scoring pipeline runs entirely on KU HPC (Slurm cluster).
No additional infrastructure needed — uses shared scratch filesystem
with Parquet shards and DuckDB for aggregation.

See `alrobles/ecoseek-litdump/docs/lacs-scoring-pipeline.md` for
full technical documentation.

## Performance Targets

| Metric | Target |
|--------|--------|
| Training time | ~5 min |
| Scoring throughput | ~100K abstracts/min/job |
| Total scoring time | ~2-4 hours (360 parallel jobs) |
| Precision at 0.8 | ~90% |
| Meilisearch import | ~1-2 hours (streaming) |
| End-to-end | ~3-6 hours |
