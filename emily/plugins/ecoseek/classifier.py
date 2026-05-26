"""DiDAL complexity classifier — rules-based prompt routing.

Decides whether a user prompt should:
  - stay in **direct** mode (simple/factual),
  - enter **didal** mode (conceptual/scientific),
  - or enter **didal_literature** mode (evidence-grounded synthesis).

Uses a deterministic rules-plus-score approach that is easy to audit
and can later be replaced by a learned classifier from Phoenix traces.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Scientific vocabulary sets
# ---------------------------------------------------------------------------

_SCIENTIFIC_TERMS = frozenset(
    {
        # Ecology core
        "niche",
        "nicho",
        "biodiversity",
        "biodiversidad",
        "ecosystem",
        "ecosistema",
        "ecological",
        "ecologico",
        "ecologia",
        "ecology",
        "population",
        "poblacion",
        "community",
        "comunidad",
        "trophic",
        "trofico",
        "biome",
        "bioma",
        "succession",
        "sucesion",
        "symbiosis",
        "predation",
        "parasitism",
        "mutualism",
        "competition",
        "dispersal",
        "migration",
        "phenology",
        "resilience",
        "disturbance",
        "perturbacion",
        "scale",
        "escala",
        "spatial",
        "temporal",
        "landscape",
        "paisaje",
        "habitat",
        "species",
        "especie",
        "organism",
        "organismo",
        # Biogeography / modeling
        "sdm",
        "maxent",
        "enm",
        "gbif",
        "worldclim",
        "bioclim",
        "raster",
        "occurrence",
        "ocurrencia",
        "distribution",
        "distribucion",
        "suitability",
        "idoneidad",
        "transferability",
        "transferibilidad",
        # Phylogenetics / evolution
        "phylogenetic",
        "filogenetico",
        "phylogeny",
        "filogenia",
        "clade",
        "clado",
        "speciation",
        "especiacion",
        "divergence",
        "divergencia",
        "monophyletic",
        "paraphyletic",
        "molecular clock",
        "reloj molecular",
        # Statistics / methods
        "regression",
        "regresion",
        "likelihood",
        "verosimilitud",
        "bayesian",
        "bootstrap",
        "permutation",
        "multivariate",
        "multivariado",
        "pca",
        "ordination",
        "ordenacion",
        "glm",
        "gam",
        "random forest",
        # Population ecology
        "carrying capacity",
        "capacidad de carga",
        "density dependence",
        "dependencia de densidad",
        "growth rate",
        "tasa de crecimiento",
        "metapopulation",
        "metapoblacion",
        "demographic",
        "demografico",
        # Diversity indices
        "shannon",
        "simpson",
        "chao",
        "rarefaction",
        "rarefaccion",
        "alpha diversity",
        "beta diversity",
        "gamma diversity",
        "species richness",
        "riqueza de especies",
        # Named concepts / people
        "hutchinson",
        "grinnell",
        "elton",
        "macarthur",
        "wilson",
        "hubbell",
        "neutral theory",
        "teoria neutral",
        "island biogeography",
    }
)

_COMPARISON_WORDS = frozenset(
    {
        "compare",
        "comparar",
        "comparison",
        "comparacion",
        "contrast",
        "contrastar",
        "differ",
        "diferir",
        "difference",
        "differences",
        "diferencia",
        "diferencias",
        "versus",
        "vs",
        "between",
        "entre",
        "advantage",
        "ventaja",
        "disadvantage",
        "desventaja",
        "tradeoff",
        "better",
        "mejor",
        "worse",
        "peor",
        "distinguish",
        "distinguir",
        "distinction",
        "distincion",
    }
)

_EXPLANATION_WORDS = frozenset(
    {
        "why",
        "por que",
        "porque",
        "how",
        "como",
        "explain",
        "explicar",
        "explica",
        "summarize",
        "resumir",
        "resumen",
        "synthesize",
        "sintetizar",
        "synthesis",
        "sintesis",
        "mechanism",
        "mecanismo",
        "mechanisms",
        "mecanismos",
        "cause",
        "causa",
        "reason",
        "razon",
        "interpret",
        "interpretar",
        "analysis",
        "analisis",
        "analyze",
        "analizar",
        "meaning",
        "significado",
        "implications",
        "implicaciones",
    }
)

_EVIDENCE_WORDS = frozenset(
    {
        "paper",
        "papers",
        "articulo",
        "articulos",
        "reference",
        "references",
        "referencia",
        "referencias",
        "cite",
        "citar",
        "citation",
        "citations",
        "cita",
        "citas",
        "evidence",
        "evidencia",
        "literature",
        "literatura",
        "review",
        "revision",
        "study",
        "studies",
        "estudio",
        "estudios",
        "research",
        "investigacion",
        "author",
        "authors",
        "autor",
        "autores",
        "published",
        "publicado",
        "journal",
        "revista",
        "doi",
        "pmid",
        "abstract",
        "resumen",
        "bibliography",
        "bibliografia",
        "source",
        "sources",
        "fuente",
        "fuentes",
    }
)

_UNCERTAINTY_WORDS = frozenset(
    {
        "debate",
        "controversy",
        "controversia",
        "limitation",
        "limitacion",
        "limitation",
        "critique",
        "critica",
        "challenge",
        "desafio",
        "interpretation",
        "interpretacion",
        "assumption",
        "supuesto",
        "uncertainty",
        "incertidumbre",
        "ambiguity",
        "ambiguedad",
        "contested",
        "disputed",
        "debatido",
        "questionable",
        "cuestionable",
    }
)

_REPORT_WORDS = frozenset(
    {
        "report",
        "reporte",
        "informe",
        "mini-report",
        "summary",
        "resumen",
        "overview",
        "revision",
        "deep",
        "profundo",
        "thorough",
        "exhaustivo",
        "comprehensive",
        "comprehensivo",
        "complete",
        "completo",
        "discussion",
        "discusion",
        "critique",
        "critica",
    }
)

_OPERATIONAL_PATTERNS = [
    r"\bport\b",
    r"\bpuerto\b",
    r"\bconfig\b",
    r"\bconfigur",
    r"\bsetup\b",
    r"\binstall\b",
    r"\bdocker\b",
    r"\bstart\b",
    r"\brestart\b",
    r"\bstatus\b",
    r"\berror\b",
    r"\bbug\b",
    r"\bfix\b",
    r"\bdeploy\b",
    r"\bui\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bapi\b",
    r"\bendpoint\b",
    r"\btoken\b",
    r"\bpassword\b",
    r"\bkey\b",
    r"\bcredential\b",
]

# Patterns that indicate an execution/action task (not a question).
# These should be routed to escalate_remote, not didal_protocol.
_EXECUTION_PATTERNS = [
    r"\bcrea\b",
    r"\bcreate\b",
    r"\bcorr[ea]\b",
    r"\brun\b",
    r"\bejecutar?\b",
    r"\bexecute\b",
    r"\bsubmit\b",
    r"\benviar?\b",
    r"\bsbatch\b",
    r"\bslurm\b",
    r"\bjob\b",
    r"\bscript\b",
    r"\bdownload\b",
    r"\bdescargar?\b",
    r"\bbaja\b",
    r"\bsleep\b",
    r"\binstalar?\b",
    r"\bcluster\b",
    r"\bhpc\b",
    r"\bgpu\b",
]


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

_WEB_SEARCH_PATTERNS = [
    r"\bsearch\b",
    r"\bbusca\b",
    r"\bbuscar\b",
    r"\bfind\b",
    r"\bencuentra\b",
    r"\blook\s*up\b",
    r"\bgoogle\b",
    r"\bgithub\b",
    r"\brepo\b",
    r"\brepository\b",
    r"\brepositorio\b",
    r"\bwebsite\b",
    r"\bsitio\b",
    r"\burl\b",
    r"\blink\b",
]


class ClassificationResult(NamedTuple):
    mode: str  # "direct" | "didal" | "didal_literature"
    complexity_score: float  # 0.0 - 1.0
    reasons: list[str]
    needs_clarification: bool
    expected_depth: str  # "low" | "medium" | "high"
    is_execution: bool = False  # True → route to escalate_remote, not didal
    is_web_search: bool = False  # True → route to web_search tool


# ---------------------------------------------------------------------------
# Tokenizer helper
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase and split into word tokens."""
    return re.findall(r"[a-záéíóúüñ]+", text.lower())


def _has_any(tokens: list[str], word_set: frozenset) -> list[str]:
    """Return matched words from word_set found in tokens (including bigrams)."""
    matched = []
    for w in tokens:
        if w in word_set:
            matched.append(w)
    # Check bigrams
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i + 1]}"
        if bigram in word_set:
            matched.append(bigram)
    return matched


def _is_operational(text: str) -> bool:
    """True if the prompt is about setup/config/status, not science."""
    lower = text.lower()
    hits = sum(1 for p in _OPERATIONAL_PATTERNS if re.search(p, lower))
    return hits >= 2


def _is_execution(text: str) -> bool:
    """True if the prompt asks to DO something (create, run, submit, download).

    These should route to escalate_remote, not didal_protocol.
    """
    lower = text.lower()
    hits = sum(1 for p in _EXECUTION_PATTERNS if re.search(p, lower))
    return hits >= 2


def _is_web_search(text: str) -> bool:
    """True if the prompt asks to search the web, GitHub, or look up info."""
    lower = text.lower()
    hits = sum(1 for p in _WEB_SEARCH_PATTERNS if re.search(p, lower))
    return hits >= 1


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------


def classify_complexity(prompt: str) -> ClassificationResult:
    """Classify a user prompt into direct, didal, or didal_literature mode.

    Uses the deterministic rules-plus-score approach from the DiDAL
    Improvement Protocol. Returns a ClassificationResult with mode,
    score, reasons, and expected depth.
    """
    tokens = _tokenize(prompt)
    n_tokens = len(tokens)
    reasons: list[str] = []
    score = 0.0
    execution = _is_execution(prompt)

    # --- Operational shortcut: always direct ---
    if _is_operational(prompt):
        return ClassificationResult(
            mode="direct",
            complexity_score=0.0,
            reasons=["operational_or_setup_question"],
            needs_clarification=False,
            expected_depth="low",
            is_execution=execution,
        )

    # --- Execution task: direct mode + flag for escalate_remote ---
    if execution:
        return ClassificationResult(
            mode="direct",
            complexity_score=0.0,
            reasons=["execution_task_use_escalate_remote"],
            needs_clarification=False,
            expected_depth="low",
            is_execution=True,
        )

    # --- Web search shortcut: direct mode + flag for web_search tool ---
    web_search = _is_web_search(prompt)
    if web_search:
        return ClassificationResult(
            mode="direct",
            complexity_score=0.0,
            reasons=["web_search_use_web_search_tool"],
            needs_clarification=False,
            expected_depth="low",
            is_web_search=True,
        )

    # --- Scoring heuristics (from protocol spec) ---

    # +0.10 if prompt length > 20 tokens
    if n_tokens > 20:
        score += 0.10
        reasons.append("prompt_length_over_20_tokens")

    # +0.10 if question contains why/how/compare/explain/synthesize
    expl_matches = _has_any(tokens, _EXPLANATION_WORDS)
    comp_matches = _has_any(tokens, _COMPARISON_WORDS)
    if expl_matches or comp_matches:
        score += 0.10
        reasons.append(
            f"contains_explanation_or_comparison: {', '.join(expl_matches + comp_matches)}"
        )

    # +0.15 if prompt contains scientific terms or named concepts
    sci_matches = _has_any(tokens, _SCIENTIFIC_TERMS)
    if sci_matches:
        score += 0.15
        reasons.append(f"scientific_terms: {', '.join(sci_matches[:5])}")

    # +0.20 if prompt asks for references, papers, evidence, citations
    ev_matches = _has_any(tokens, _EVIDENCE_WORDS)
    if ev_matches:
        score += 0.20
        reasons.append(f"requests_evidence: {', '.join(ev_matches[:3])}")

    # +0.15 if prompt includes multiple clauses or subquestions
    clause_markers = len(
        re.findall(r"[,;?]|\by\b|\band\b|\bademas\b|\btambien\b", prompt.lower())
    )
    if clause_markers >= 2:
        score += 0.15
        reasons.append(f"multiple_clauses_or_subquestions ({clause_markers} markers)")

    # +0.15 if prompt requires historical, theoretical, or methodological contrast
    hist_pattern = bool(
        re.search(
            r"(?:history|historia|evolution|evolucion|since|desde|origin|origen|development|desarrollo|changed|cambi)",
            prompt.lower(),
        )
    )
    if hist_pattern:
        score += 0.15
        reasons.append("requires_historical_or_theoretical_contrast")

    # +0.15 if prompt includes uncertainty words
    unc_matches = _has_any(tokens, _UNCERTAINTY_WORDS)
    if unc_matches:
        score += 0.15
        reasons.append(f"uncertainty_or_debate: {', '.join(unc_matches[:3])}")

    # Bonus: report/deep/thorough request
    rep_matches = _has_any(tokens, _REPORT_WORDS)
    if rep_matches:
        score += 0.10
        reasons.append(f"requests_depth: {', '.join(rep_matches[:3])}")

    # --- Combo bonuses (strong literature signals) ---

    # Named scientist + historical pattern → strong literature signal
    _named_scientists = {
        "hutchinson",
        "grinnell",
        "elton",
        "macarthur",
        "wilson",
        "hubbell",
    }
    has_named = any(t in _named_scientists for t in tokens)
    if has_named and hist_pattern:
        score += 0.10
        reasons.append("named_scientist_with_historical_context")

    # Evidence request + scientific terms → literature-grade question
    if ev_matches and sci_matches:
        score += 0.10
        reasons.append("evidence_plus_scientific_combo")

    # Explicit paper/reference request is a strong literature signal
    _strong_evidence = {
        "papers",
        "paper",
        "references",
        "citations",
        "bibliography",
        "articulos",
        "referencias",
        "citas",
        "bibliografia",
        "fuentes",
    }
    if any(t in _strong_evidence for t in tokens) and sci_matches:
        score += 0.05
        reasons.append("explicit_literature_request")

    # Scientific question too short for clause bonus but clearly conceptual
    if sci_matches and n_tokens >= 4 and n_tokens <= 15 and score < 0.25:
        score = 0.25
        reasons.append("short_scientific_question_promoted")

    # Cap at 1.0
    score = min(score, 1.0)

    # --- Determine needs_clarification ---
    # Short prompts with some complexity but no clear direction
    needs_clarification = (
        0.25 <= score < 0.50 and n_tokens < 15 and not ev_matches and not comp_matches
    )

    # --- Route ---
    if score < 0.25:
        mode = "direct"
        depth = "low"
    elif score < 0.60:
        mode = "didal"
        depth = "medium"
    else:
        mode = "didal_literature"
        depth = "high"

    if not reasons:
        reasons.append("simple_factual_prompt")

    return ClassificationResult(
        mode=mode,
        complexity_score=round(score, 2),
        reasons=reasons,
        needs_clarification=needs_clarification,
        expected_depth=depth,
    )
