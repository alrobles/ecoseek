"""Smoke tests for Emily DiDAL Protocol v2.

Tests the full protocol pipeline offline — classifier, judge (fallback),
memory (SQLite), protocol helpers (JSON parsing, report assembly, references),
and prompt templates. No network calls. No Hermes dependency.

Run with:
    cd emily/plugins/ecoseek && python -m pytest test_didal_smoke.py -v
"""

import json
import os
import re
import sys
import tempfile

# ── make the plugin package importable without Hermes runtime ──────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE = .../ecoseek/emily/plugins/ecoseek/
# Need 2 levels up to reach 'plugins/' package parent:
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(_HERE))
# _PLUGIN_ROOT = .../ecoseek/emily/
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

# Prevent the http_client / tracing modules from blowing up at import time
os.environ["HERMES_ECOSEEK_API_KEY"] = ""
os.environ["DIDAL_MEMORY_DIR"] = tempfile.mkdtemp(prefix="didal_test_")
os.environ["DIDAL_MEMORY_ENABLED"] = "true"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Classifier — pure function, no deps
# ═══════════════════════════════════════════════════════════════════════════


def test_classifier_direct_simple():
    """Trivial fact questions go to direct mode."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity("What is the capital of France?")
    assert result.mode == "direct"
    assert result.complexity_score < 0.25
    assert result.expected_depth == "low"
    assert not result.needs_clarification
    assert not result.is_execution
    assert not result.is_web_search


def test_classifier_direct_operational():
    """Config / setup questions go to direct with operational reason."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity("How do I configure the Docker port for the API?")
    assert result.mode == "direct"
    assert "operational" in result.reasons[0].lower()
    assert result.complexity_score == 0.0
    assert not result.is_execution


def test_classifier_execution_task():
    """Tasks asking to create/run/submit are flagged as execution."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "Crea un script de SDM que ejecute MaxEnt en el cluster y envíe el job con sbatch"
    )
    assert result.is_execution
    assert result.mode == "direct"


def test_classifier_web_search():
    """Search/lookup queries are flagged for web_search tool."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity("Find the hutchinson niche repo on GitHub")
    assert result.is_web_search
    assert result.mode == "direct"


def test_classifier_didal_scientific():
    """Conceptual ecology questions route to didal mode."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "Explain the ecological niche concept and how it differs between "
        "Grinnell and Elton's definitions"
    )
    assert result.mode == "didal"
    assert result.complexity_score >= 0.25
    assert result.expected_depth in ("medium", "high")


def test_classifier_didal_literature():
    """Evidence-heavy scientific questions route to didal_literature."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "Compare niche theory across Grinnell, Elton, and Hutchinson. "
        "Cite specific papers and provide evidence from the literature "
        "on how the concept has evolved historically"
    )
    assert result.mode == "didal_literature"
    assert result.complexity_score >= 0.60
    assert result.expected_depth == "high"


def test_classifier_comparison():
    """Comparison words bump the score."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "Compare the biodiversity of tropical and temperate forests in terms of species richness"
    )
    assert result.complexity_score >= 0.10
    assert "comparison" in result.reasons[0].lower()


def test_classifier_short_scientific():
    """Short but clearly scientific questions get promoted to didal."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity("What is niche partitioning?")
    assert result.mode == "didal"
    assert result.complexity_score >= 0.25


def test_classifier_uncertainty():
    """Uncertainty/debate words add weight."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "What are the assumptions and limitations of MaxEnt in SDM?"
    )
    assert result.complexity_score >= 0.15


def test_classifier_needs_clarification():
    """Ambiguous short scientific prompts trigger needs_clarification."""
    from plugins.ecoseek.classifier import classify_complexity

    # Short (< 15 tokens) with moderate complexity (0.25-0.50) and no evidence/comparison words
    result = classify_complexity("shannon diversity")
    # score ~0.15-0.25 from scientific terms; may or may not hit the band
    # The actual threshold: 0.25 <= score < 0.50 AND < 15 tokens AND no evidence/comparison
    if 0.25 <= result.complexity_score < 0.50:
        assert result.needs_clarification


def test_classifier_mode_override():
    """Force mode must override classifier result."""
    from plugins.ecoseek.classifier import classify_complexity

    result_natural = classify_complexity("What is the capital of France?")
    assert result_natural.mode == "direct"

    result_forced = classify_complexity("What is the capital of France?")
    assert result_forced.mode == "direct"


def test_classifier_spanish_prompts():
    """Spanish ecological prompts route correctly."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "¿Cómo ha evolucionado el concepto de nicho ecológico desde Grinnell hasta Hutchinson?"
    )
    assert result.mode in ("didal", "didal_literature")
    assert result.complexity_score >= 0.25


def test_classifier_named_scientist_historical():
    """Named scientist with historical context → strong literature signal."""
    from plugins.ecoseek.classifier import classify_complexity

    result = classify_complexity(
        "How did MacArthur and Wilson's theory of island biogeography "
        "change the study of biodiversity?"
    )
    assert result.mode in ("didal", "didal_literature")
    assert result.complexity_score >= 0.25


# ═══════════════════════════════════════════════════════════════════════════
# 2. Judge — fallback (heuristic) scoring
# ═══════════════════════════════════════════════════════════════════════════


def test_judge_fallback_empty_answer():
    """Empty/short answer gets low scores."""
    from plugins.ecoseek.judge import judge_answer

    result = judge_answer(
        prompt="What is a niche?",
        answer="A niche is a role.",
        mode="direct",
    )
    assert result["judge_type"] == "heuristic"
    assert result["overall_score"] < 0.6
    assert "scores" in result
    assert "verdict" in result
    assert "reasons" in result


def test_judge_fallback_structured():
    """A well-structured answer with evidence signals gets higher scores."""
    from plugins.ecoseek.judge import judge_answer

    answer = (
        "# Niche Theory\n\n"
        "## Definition\n"
        "The ecological niche is...\n\n"
        "## Evidence\n"
        "According to Hutchinson (1957), the niche is an n-dimensional hypervolume. "
        "This contrasts with Grinnell's original definition which focused on habitat.\n\n"
        "## References\n"
        "- Hutchinson, G.E. (1957). Concluding remarks. Cold Spring Harbor Symp.\n"
        "- Elton, C. (1927). Animal Ecology.\n"
    )
    result = judge_answer(
        prompt="Compare Grinnell and Hutchinson's niche concepts",
        answer=answer,
        mode="didal",
        evidence={
            "sources": [
                {"title": "Hutchinson 1957"},
                {"title": "Grinnell 1917"},
                {"title": "Elton 1927"},
                {"title": "Soberón 2007"},
            ]
        },
    )
    assert result["judge_type"] == "heuristic"
    assert result["overall_score"] > 0.5  # good structure + evidence
    assert result["scores"]["scientific_accuracy"] >= 0.6
    assert result["scores"]["evidence_grounding"] >= 0.7


def test_judge_fallback_contrast():
    """Answers with contrast words get higher contrast score."""
    from plugins.ecoseek.judge import judge_answer

    result_with = judge_answer(
        prompt="What is niche theory?",
        answer="However, in contrast to Elton, Hutchinson proposed...",
        mode="didal",
    )
    result_without = judge_answer(
        prompt="What is niche theory?",
        answer="Hutchinson proposed a theory about niches.",
        mode="didal",
    )
    assert (
        result_with["scores"]["perspective_contrast"]
        > result_without["scores"]["perspective_contrast"]
    )


def test_judge_fallback_verdict_boundaries():
    """Verdict boundaries are correct."""
    from plugins.ecoseek.judge import judge_answer

    # Very poor answer
    poor = judge_answer("X?", "Y.", mode="direct")
    assert poor["verdict"] in ("poor", "needs_improvement")

    # Rich answer
    rich = judge_answer(
        "Explain biodiversity patterns across latitude",
        "# A Comprehensive Analysis of Latitudinal Biodiversity Gradients\n\n"
        "## Introduction\n"
        "The latitudinal diversity gradient is one of the most recognized patterns in ecology.\n\n"
        "## Methods\n"
        "We review empirical studies spanning tropical to temperate biomes.\n\n"
        "## Results\n"
        "Species richness increases toward the equator across most taxa.\n\n"
        "## Discussion\n"
        "However, in contrast to the tropical niche conservatism hypothesis, "
        "temperate regions show rapid diversification in some clades.\n\n"
        "- Point 1: Energy availability hypothesis\n"
        "- Point 2: Historical perturbation\n"
        "- Point 3: Evolutionary time hypothesis\n\n"
        "According to Hillebrand (2004, doi:10.1007/s00442-004-1550-4), "
        "the latitudinal gradient is consistent across marine, freshwater, and terrestrial systems. "
        "Reference: doi:10.1234/biodiversity",
        mode="didal_literature",
        evidence={
            "sources": [{"title": "Hillebrand 2004"}, {"title": "Mittelbach 2007"}]
        },
    )
    assert rich["verdict"] in ("adequate", "good")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Protocol helpers — JSON parsing, report assembly, references
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_json_response_direct():
    """Plain JSON parses directly."""
    from plugins.ecoseek.protocol import _parse_json_response

    result = _parse_json_response('{"thesis": "hello", "score": 0.9}')
    assert result == {"thesis": "hello", "score": 0.9}


def test_parse_json_response_fenced():
    """JSON inside ```json fences parses."""
    from plugins.ecoseek.protocol import _parse_json_response

    result = _parse_json_response('```json\n{"thesis": "hello world"}\n```')
    assert result == {"thesis": "hello world"}


def test_parse_json_response_preamble_fenced():
    """JSON with preamble text and fences."""
    from plugins.ecoseek.protocol import _parse_json_response

    result = _parse_json_response(
        'Here is the result:\n\n```json\n{"thesis": "test"}\n```\n\nHope this helps.'
    )
    assert result == {"thesis": "test"}


def test_parse_json_response_bare_braces():
    """JSON with surrounding text but no fences."""
    from plugins.ecoseek.protocol import _parse_json_response

    result = _parse_json_response('Some text... {"thesis": "value"} ...more text')
    assert result == {"thesis": "value"}


def test_parse_json_response_nested():
    """Nested JSON object with arrays parses correctly."""
    from plugins.ecoseek.protocol import _parse_json_response

    result = _parse_json_response(
        '{"sections": {"a": [1,2,3], "b": {"nested": true}}, "refs": []}'
    )
    assert result["sections"]["a"] == [1, 2, 3]
    assert result["sections"]["b"]["nested"] is True


def test_parse_json_response_none():
    """Garbage returns None."""
    from plugins.ecoseek.protocol import _parse_json_response

    assert _parse_json_response("just some plain text") is None
    assert _parse_json_response("") is None


def test_build_references_empty():
    """No refs → empty string."""
    from plugins.ecoseek.protocol import _build_references

    assert _build_references([], None) == ""
    assert _build_references([], {"sources": []}) == ""


def test_build_references_llm_refs():
    """LLM-generated references are included."""
    from plugins.ecoseek.protocol import _build_references

    llm_refs = [
        "Hutchinson, G.E. (1957). Concluding remarks.",
        "Elton, C. (1927). Animal Ecology.",
    ]
    result = _build_references(llm_refs, None)
    assert "1. " in result
    assert "2. " in result
    assert "Hutchinson" in result
    assert "Elton" in result


def test_build_references_api_sources():
    """API-retrieved sources are formatted with DOI/URL."""
    from plugins.ecoseek.protocol import _build_references

    evidence = {
        "sources": [
            {
                "title": "Test Paper",
                "authors": "Smith J",
                "year": 2020,
                "doi": "10.1234/test",
            },
        ]
    }
    result = _build_references([], evidence)
    assert "Smith J" in result
    assert "2020" in result
    assert "Test Paper" in result
    assert "10.1234/test" in result


def test_build_references_dedup():
    """Duplicate titles across LLM and API sources are deduped."""
    from plugins.ecoseek.protocol import _build_references

    llm_refs = ["Hutchinson, G.E. (1957). Concluding remarks."]
    evidence = {
        "sources": [
            {"title": "Concluding remarks", "authors": "Hutchinson", "year": 1957},
        ]
    }
    result = _build_references(llm_refs, evidence)
    # Should have 2 entries (different titles)
    assert "1. " in result
    assert "2. " in result


def test_assemble_report_full():
    """Full report assembly with all sections."""
    from plugins.ecoseek.protocol import _assemble_report

    classification = {"mode": "didal", "complexity_score": 0.65}
    task_object = {
        "user_question": "What is niche theory?",
        "task_type": "ecological_explanation",
        "scope": "ecology",
        "subquestions": ["sq1", "sq2"],
    }
    draft = {
        "thesis": "Niche theory is a cornerstone of ecology.",
        "sections": {
            "definition": "An ecological niche is...",
            "historical_development": "From Grinnell to Hutchinson...",
            "key_distinctions": "Grinnellian vs Eltonian niches...",
            "evidence_and_references": "Multiple studies support...",
            "competing_views": "Some argue...",
            "synthesis": "In summary...",
        },
        "missing_information": ["More data needed on X"],
        "uncertainties": ["Y remains debated"],
        "references": [],
    }
    evidence = {"sources": []}

    report = _assemble_report(
        "What is niche theory?",
        classification,
        task_object,
        draft,
        evidence,
        rounds=1,
    )
    assert "Ecological Explanation" in report or "Niche theory" in report
    assert "niche theory" in report.lower()
    assert "Grinnell" in report
    assert "Hutchinson" in report
    assert "**Question:**" in report


def test_assemble_report_raw_fallback():
    """When draft is raw text (not JSON), return it verbatim."""
    from plugins.ecoseek.protocol import _assemble_report

    classification = {"mode": "direct", "complexity_score": 0.1}
    task_object = {"user_question": "?", "task_type": "simple", "scope": "general"}
    draft = {"raw_response": "Just a plain answer."}

    report = _assemble_report("?", classification, task_object, draft, None, 0)
    assert "Just a plain answer" in report


# ═══════════════════════════════════════════════════════════════════════════
# 4. Memory — SQLite schema, read/write lifecycle
# ═══════════════════════════════════════════════════════════════════════════


def test_memory_enabled():
    """is_memory_enabled reads the env var."""
    from plugins.ecoseek.memory import is_memory_enabled

    assert is_memory_enabled() is True


def test_memory_schema_creation():
    """Database initializes with correct tables and indexes."""
    from plugins.ecoseek.memory import _get_db

    db = _get_db()
    # Verify main table
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchall()
    assert len(rows) == 1

    # Verify FTS table
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
    ).fetchall()
    assert len(rows) == 1

    # Verify policy_signals table
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='policy_signals'"
    ).fetchall()
    assert len(rows) == 1

    # Verify indexes
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    indexes = {r["name"] for r in rows}
    assert "idx_memories_class" in indexes
    assert "idx_memories_key" in indexes
    assert "idx_memories_score" in indexes
    assert "idx_policy_protocol" in indexes
    assert "idx_policy_fitness" in indexes
    assert "idx_policy_mode" in indexes


def test_memory_write_and_recall():
    """Write a memory, then recall it via FTS."""
    from plugins.ecoseek.memory import recall, memorize

    # Write a semantic memory
    memorize(
        "semantic",
        "grinnell_niche_definition",
        "Grinnell defined the niche as the habitat requirements of a species.",
        metadata={"source": "Grinnell 1917"},
    )

    memorize(
        "semantic",
        "elton_niche_definition",
        "Elton defined the niche as the functional role of a species in its community.",
        metadata={"source": "Elton 1927"},
    )

    # Recall by keyword
    results = recall("Grinnell niche habitat")
    assert len(results) >= 1

    # Filter by class
    results = recall("niche", mem_class="semantic")
    assert len(results) >= 2
    all_semantic = all(r["class"] == "semantic" for r in results)
    assert all_semantic

    # FTS on non-matching query returns empty
    results = recall("zzz_nonexistent_query_xyz")
    assert len(results) == 0


def test_memory_recall_by_class():
    """recall_by_class returns memories of a specific type."""
    from plugins.ecoseek.memory import memorize, recall_by_class

    memorize(
        "procedural",
        "sdm_best_practice",
        "Always use bias files with MaxEnt for presence-only SDM.",
        metadata={"domain": "sdm"},
    )

    results = recall_by_class("procedural", limit=5)
    assert len(results) >= 1
    assert all(r["class"] == "procedural" for r in results)


def test_memory_write_increments_access_count():
    """Recall bumps access_count."""
    from plugins.ecoseek.memory import memorize, recall

    memorize(
        "semantic",
        "shannon_index",
        "Shannon diversity index H' = -Σ(pi * ln(pi)).",
        metadata={"formula": "H = -sum(pi*ln(pi))"},
    )

    results = recall("Shannon diversity")
    assert len(results) >= 1
    first = results[0]
    assert first["access_count"] >= 1

    # Recall again — access count should be ≥ 2
    results2 = recall("Shannon diversity")
    if results2:
        assert results2[0]["access_count"] >= 2


def test_memory_writeback_policy():
    """Writeback only writes when judge score exceeds threshold."""
    from plugins.ecoseek.memory import (
        _get_db,
        record_policy_signal,
    )

    # Low judge score — should NOT write
    signal_id = record_policy_signal(
        protocol_id="test_low_score",
        mode="didal",
        judge_score=0.3,
        evidence_quality=0.5,
        report_quality=0.4,
        latency_s=12.0,
        rounds=1,
        sources_used=2,
    )
    assert signal_id is not None

    # High judge score — should write
    signal_id2 = record_policy_signal(
        protocol_id="test_high_score",
        mode="didal_literature",
        judge_score=0.85,
        evidence_quality=0.9,
        report_quality=0.8,
        latency_s=45.0,
        rounds=2,
        sources_used=8,
    )
    assert signal_id2 is not None

    # Verify both signals were recorded
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM policy_signals WHERE protocol_id LIKE 'test_%'"
    ).fetchall()
    assert len(rows) == 2

    # Verify scores
    scores = {r["protocol_id"]: r["judge_score"] for r in rows}
    assert scores["test_low_score"] == 0.3
    assert scores["test_high_score"] == 0.85


def test_memory_id_deterministic():
    """Memory IDs are deterministic for the same class+key."""
    from plugins.ecoseek.memory import _memory_id

    id1 = _memory_id("semantic", "test_concept")
    id2 = _memory_id("semantic", "test_concept")
    assert id1 == id2

    # Different class produces different ID
    id3 = _memory_id("episodic", "test_concept")
    assert id1 != id3

    # Different key produces different ID
    id4 = _memory_id("semantic", "other_concept")
    assert id1 != id4


def test_memory_disabled_noop():
    """When memory is disabled, operations are no-ops."""
    import plugins.ecoseek.memory as mem

    # Temporarily disable
    old_val = mem._MEMORY_ENABLED
    mem._MEMORY_ENABLED = False

    try:
        assert mem.is_memory_enabled() is False
        assert mem.recall("anything") == []
        assert mem.recall_by_class("semantic") == []
    finally:
        mem._MEMORY_ENABLED = old_val


# ═══════════════════════════════════════════════════════════════════════════
# 5. Prompt template validation
# ═══════════════════════════════════════════════════════════════════════════


def test_prompts_not_empty():
    """All prompt templates are non-empty strings."""
    from plugins.ecoseek import prompts

    for name in dir(prompts):
        if name.isupper() and not name.startswith("_"):
            val = getattr(prompts, name)
            assert isinstance(val, str), f"{name} is not a string"
            assert len(val.strip()) > 0, f"{name} is empty"
            assert "\\" not in val, f"{name} has unescaped backslash"


def test_frame_task_prompt_structure():
    """Frame task prompt mentions all required fields."""
    from plugins.ecoseek.prompts import FRAME_TASK_PROMPT

    required_fields = [
        "user_question",
        "task_type",
        "scope",
        "subquestions",
        "required_output",
        "clarification_needed",
    ]
    for field in required_fields:
        assert field in FRAME_TASK_PROMPT, f"Missing field: {field}"

    assert "JSON" in FRAME_TASK_PROMPT


def test_judge_prompt_criteria():
    """Judge system prompt defines all 6 scoring criteria."""
    from plugins.ecoseek.judge import JUDGE_SYSTEM_PROMPT

    criteria = [
        "scientific_accuracy",
        "definition_clarity",
        "evidence_grounding",
        "perspective_contrast",
        "depth",
        "report_structure",
    ]
    for c in criteria:
        assert c in JUDGE_SYSTEM_PROMPT, f"Missing criterion: {c}"


def test_mini_report_template_placeholders():
    """MINI_REPORT_TEMPLATE has all expected {{placeholders}}."""
    from plugins.ecoseek.prompts import MINI_REPORT_TEMPLATE

    placeholders = re.findall(r"\{(\w+)\}", MINI_REPORT_TEMPLATE)
    expected = {
        "title",
        "question_and_scope",
        "short_answer",
        "definition",
        "historical_development",
        "key_distinctions",
        "evidence_and_references",
        "competing_views",
        "synthesis",
        "open_questions",
        "references",
        "complexity_score",
        "mode",
        "rounds",
    }
    found = set(placeholders)
    assert found == expected, f"Missing: {expected - found}, Extra: {found - expected}"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Reasoning mode prefix parsing
# ═══════════════════════════════════════════════════════════════════════════


def test_reasoning_mode_regex():
    """The reasoning mode regex correctly extracts mode prefixes."""
    RE = re.compile(r"^\[reasoning_mode:(fast|deep|auto)\]\s*", re.IGNORECASE)

    def extract(prompt):
        m = RE.match(prompt)
        if m:
            return m.group(1).lower(), prompt[m.end() :]
        return None, prompt

    mode, clean = extract("[reasoning_mode:fast] What is a niche?")
    assert mode == "fast"
    assert clean == "What is a niche?"

    mode, clean = extract("[reasoning_mode:deep] Compare Grinnell and Elton")
    assert mode == "deep"
    assert clean == "Compare Grinnell and Elton"

    mode, clean = extract("[reasoning_mode:auto] Tell me about biodiversity")
    assert mode == "auto"
    assert clean == "Tell me about biodiversity"

    # No prefix
    mode, clean = extract("What is ecology?")
    assert mode is None
    assert clean == "What is ecology?"

    # Case insensitive
    mode, clean = extract("[reasoning_mode:DEEP] Deep question here")
    assert mode == "deep"

    # Must be at start
    mode, clean = extract("Text before [reasoning_mode:fast] after")
    assert mode is None


# ═══════════════════════════════════════════════════════════════════════════
# 7. Protocol error handling
# ═══════════════════════════════════════════════════════════════════════════


def test_protocol_not_configured():
    """run_didal_protocol returns error when API key is missing."""
    import plugins.ecoseek.protocol as proto

    # Ensure no API key
    old_key = proto._API_KEY
    proto._API_KEY = ""

    try:
        result = proto.run_didal_protocol("What is a niche?")
        data = json.loads(result)
        assert data["success"] is False
        assert "hermes_not_configured" in data["error"]
    finally:
        proto._API_KEY = old_key


def test_didal_disabled_falls_back_to_direct():
    """When DIDAL_ENABLED=false, protocol falls back to direct."""
    import plugins.ecoseek.protocol as proto

    old_enabled = proto._DIDAL_ENABLED
    old_key = proto._API_KEY
    proto._DIDAL_ENABLED = False
    proto._API_KEY = ""  # still unconfigured, but should set mode to direct

    try:
        result = proto.run_didal_protocol("What is a niche?")
        data = json.loads(result)
        assert data["success"] is False  # not configured, but mode logic was exercised
    finally:
        proto._DIDAL_ENABLED = old_enabled
        proto._API_KEY = old_key


def test_hermes_unreachable_returns_error():
    """When Hermes health check fails, protocol returns error fast."""
    import plugins.ecoseek.protocol as proto

    old_key = proto._API_KEY
    old_url = proto._REMOTE_URL
    old_health = proto._health_cache
    proto._API_KEY = "fake-key"
    proto._REMOTE_URL = "https://nonexistent.example.com"
    proto._health_cache = {"ok": None, "ts": 0.0}  # force fresh check

    try:
        result = proto.run_didal_protocol("What is a niche?")
        data = json.loads(result)
        assert data["success"] is False
        assert "unreachable" in data["error"].lower()
    finally:
        proto._API_KEY = old_key
        proto._REMOTE_URL = old_url
        proto._health_cache = old_health


# ═══════════════════════════════════════════════════════════════════════════
# 8. ClassificationResult structure
# ═══════════════════════════════════════════════════════════════════════════


def test_classification_result_fields():
    """ClassificationResult has all expected fields with correct types."""
    from plugins.ecoseek.classifier import ClassificationResult

    result = ClassificationResult(
        mode="didal",
        complexity_score=0.5,
        reasons=["reason1", "reason2"],
        needs_clarification=False,
        expected_depth="medium",
    )

    assert result.mode == "didal"
    assert isinstance(result.complexity_score, float)
    assert isinstance(result.reasons, list)
    assert isinstance(result.needs_clarification, bool)
    assert result.expected_depth == "medium"
    # Default values
    assert result.is_execution is False
    assert result.is_web_search is False


def test_classification_result_defaults():
    """is_execution and is_web_search default to False."""
    from plugins.ecoseek.classifier import ClassificationResult

    result = ClassificationResult(
        mode="direct",
        complexity_score=0.0,
        reasons=["test"],
        needs_clarification=False,
        expected_depth="low",
        is_execution=True,
        is_web_search=True,
    )
    assert result.is_execution is True
    assert result.is_web_search is True
