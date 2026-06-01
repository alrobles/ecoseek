#!/usr/bin/env python3
"""Benchmark: EcoCoder-7B vs DeepSeek — ecological answer quality comparison.

Uses the DiDAL judge component to score both models on the same prompts.
Prompts are taken from the DiDAL Protocol benchmark suite covering three
complexity levels: direct, didal, and didal_literature.

Usage:
  # Compare EcoCoder (LM Studio) vs DeepSeek API:
  DEEPSEEK_API_KEY=sk-... python3 benchmarks/ecocoder_vs_deepseek.py

  # EcoCoder only (local):
  ECOCODER_URL=http://localhost:1234/v1 python3 benchmarks/ecocoder_vs_deepseek.py --ecocoder-only

  # DeepSeek only:
  DEEPSEEK_API_KEY=sk-... python3 benchmarks/ecocoder_vs_deepseek.py --deepseek-only

  # Custom EcoCoder endpoint:
  ECOCODER_URL=http://localhost:11434/v1 DEEPSEEK_API_KEY=sk-... python3 benchmarks/ecocoder_vs_deepseek.py

Requirements:
  - EcoCoder-7B running via LM Studio or Ollama (OpenAI-compatible endpoint)
  - DeepSeek API key (for DeepSeek v4 comparison)
  - No extra dependencies — uses only stdlib + the ecoseek judge module
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Add plugin path for judge import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "emily" / "plugins"))
from ecoseek.judge import judge_answer, _fallback_judge  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ECOCODER_URL = os.environ.get("ECOCODER_URL", "http://localhost:1234/v1").rstrip("/")
ECOCODER_MODEL = os.environ.get("ECOCODER_MODEL", "ecocoder-7b")
ECOCODER_KEY = os.environ.get("ECOCODER_API_KEY", "lm-studio")  # LM Studio default

DEEPSEEK_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

HERMES_URL = os.environ.get("HERMES_REMOTE_URL", "https://hermes.ecoseek.org").rstrip(
    "/"
)
HERMES_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")

TIMEOUT = int(os.environ.get("BENCHMARK_TIMEOUT", "120"))
OUTPUT_DIR = Path(__file__).resolve().parent / "results"

# ---------------------------------------------------------------------------
# Benchmark prompts (from DiDAL Protocol spec)
# ---------------------------------------------------------------------------

PROMPTS = [
    # Direct mode — simple/factual
    {
        "id": "direct_1",
        "level": "direct",
        "prompt": "What is the Shannon diversity index?",
        "expected_depth": "low",
    },
    {
        "id": "direct_2",
        "level": "direct",
        "prompt": "What is GBIF and what kind of data does it provide?",
        "expected_depth": "low",
    },
    # DiDAL mode — conceptual/scientific
    {
        "id": "didal_1",
        "level": "didal",
        "prompt": "Explain the difference between the fundamental niche and the realized niche.",
        "expected_depth": "medium",
    },
    {
        "id": "didal_2",
        "level": "didal",
        "prompt": "Why do ecological explanations often fail when they ignore spatial scale?",
        "expected_depth": "medium",
    },
    {
        "id": "didal_3",
        "level": "didal",
        "prompt": "Compare the logistic growth model with the Lotka-Volterra competition model. When is each appropriate?",
        "expected_depth": "medium",
    },
    # DiDAL Literature mode — deep scientific synthesis
    {
        "id": "lit_1",
        "level": "didal_literature",
        "prompt": "What is the fundamental niche, and how has the concept evolved since Hutchinson (1957)?",
        "expected_depth": "high",
    },
    {
        "id": "lit_2",
        "level": "didal_literature",
        "prompt": "Contrast niche theory and neutral theory in community assembly. What evidence supports each?",
        "expected_depth": "high",
    },
    {
        "id": "lit_3",
        "level": "didal_literature",
        "prompt": "Summarize the ecological meaning of density dependence and support the answer with key references.",
        "expected_depth": "high",
    },
]

SYSTEM_PROMPT = """You are Emily, an expert ecological scientist. Answer the following question with scientific rigor.

Use Markdown formatting: headers, bold, lists, tables, blockquotes.
For mathematical expressions, use LaTeX: $inline$ and $$display$$.
Cite sources when making empirical claims. Distinguish definitions from interpretations.
For deep questions, structure your answer as a mini-report with sections."""

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def call_llm(
    url: str,
    model: str,
    api_key: str,
    prompt: str,
    timeout: int = TIMEOUT,
) -> dict:
    """Call an OpenAI-compatible chat completions endpoint.

    Returns dict with 'content', 'latency_ms', 'tokens', 'error'.
    """
    start = time.time()
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{url}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        latency_ms = round((time.time() - start) * 1000)

        return {
            "content": content,
            "latency_ms": latency_ms,
            "tokens": usage.get("total_tokens", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "error": None,
        }
    except Exception as exc:
        return {
            "content": "",
            "latency_ms": round((time.time() - start) * 1000),
            "tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error": str(exc)[:200],
        }


# ---------------------------------------------------------------------------
# Judge wrapper
# ---------------------------------------------------------------------------


def judge_response(prompt: str, answer: str, level: str) -> dict:
    """Score an answer using the DiDAL judge (LLM or heuristic fallback)."""
    mode_map = {
        "direct": "direct",
        "didal": "didal",
        "didal_literature": "didal_literature",
    }
    mode = mode_map.get(level, "didal")

    # Try LLM judge if Hermes key is available, otherwise heuristic
    if HERMES_KEY:
        result = judge_answer(
            prompt=prompt,
            answer=answer,
            mode=mode,
        )
    else:
        result = _fallback_judge(answer, mode, None)

    return result


# ---------------------------------------------------------------------------
# Check endpoint availability
# ---------------------------------------------------------------------------


def check_endpoint(url: str, api_key: str, model: str, name: str) -> bool:
    """Quick health check — try a minimal completion."""
    print(f"  Checking {name} at {url}...", end=" ", flush=True)
    result = call_llm(url, model, api_key, "Say hello in one word.", timeout=30)
    if result["error"]:
        print(f"UNAVAILABLE ({result['error'][:80]})")
        return False
    print(f"OK ({result['latency_ms']}ms)")
    return True


# ---------------------------------------------------------------------------
# Run benchmark
# ---------------------------------------------------------------------------


def run_benchmark(
    run_ecocoder: bool = True,
    run_deepseek: bool = True,
) -> dict:
    """Run the full benchmark and return results dict."""
    print("=" * 70)
    print("EcoCoder-7B vs DeepSeek Benchmark")
    print(f"Date: {datetime.now().isoformat()}")
    print("=" * 70)

    # Check availability
    print("\n--- Endpoint Availability ---")
    ecocoder_ok = False
    deepseek_ok = False

    if run_ecocoder:
        ecocoder_ok = check_endpoint(
            ECOCODER_URL, ECOCODER_KEY, ECOCODER_MODEL, "EcoCoder-7B"
        )
    if run_deepseek:
        deepseek_ok = check_endpoint(
            DEEPSEEK_URL, DEEPSEEK_KEY, DEEPSEEK_MODEL, "DeepSeek"
        )

    if not ecocoder_ok and not deepseek_ok:
        print("\nERROR: No models available. Set ECOCODER_URL or DEEPSEEK_API_KEY.")
        sys.exit(1)

    models = {}
    if ecocoder_ok:
        models["ecocoder"] = {
            "url": ECOCODER_URL,
            "model": ECOCODER_MODEL,
            "key": ECOCODER_KEY,
            "label": "EcoCoder-7B",
        }
    if deepseek_ok:
        models["deepseek"] = {
            "url": DEEPSEEK_URL,
            "model": DEEPSEEK_MODEL,
            "key": DEEPSEEK_KEY,
            "label": f"DeepSeek ({DEEPSEEK_MODEL})",
        }

    results = {
        "date": datetime.now().isoformat(),
        "models": {k: v["label"] for k, v in models.items()},
        "prompts": [],
    }

    print(f"\n--- Running {len(PROMPTS)} prompts × {len(models)} models ---\n")

    for i, p in enumerate(PROMPTS, 1):
        print(f"[{i}/{len(PROMPTS)}] {p['level'].upper()}: {p['prompt'][:60]}...")
        prompt_result = {
            "id": p["id"],
            "level": p["level"],
            "prompt": p["prompt"],
            "responses": {},
        }

        for model_key, model_info in models.items():
            print(f"  → {model_info['label']}...", end=" ", flush=True)

            # Get response
            resp = call_llm(
                model_info["url"],
                model_info["model"],
                model_info["key"],
                p["prompt"],
            )

            if resp["error"]:
                print(f"ERROR: {resp['error'][:60]}")
                prompt_result["responses"][model_key] = {
                    "error": resp["error"],
                    "latency_ms": resp["latency_ms"],
                }
                continue

            # Judge the response
            judge = judge_response(p["prompt"], resp["content"], p["level"])

            score = judge.get("overall_score", 0)
            verdict = judge.get("verdict", "unknown")
            print(
                f"score={score:.2f} ({verdict}) [{resp['latency_ms']}ms, {resp['completion_tokens']}tok]"
            )

            prompt_result["responses"][model_key] = {
                "content": resp["content"],
                "latency_ms": resp["latency_ms"],
                "tokens": resp["tokens"],
                "completion_tokens": resp["completion_tokens"],
                "judge": judge,
            }

        results["prompts"].append(prompt_result)
        print()

    return results


def print_summary(results: dict):
    """Print a comparison summary table."""
    print("=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    model_keys = list(results["models"].keys())

    # Aggregate scores
    aggregates: dict[str, dict] = {
        k: {"scores": [], "latencies": [], "tokens": []} for k in model_keys
    }
    level_scores: dict[str, dict[str, list]] = {}

    for p in results["prompts"]:
        level = p["level"]
        if level not in level_scores:
            level_scores[level] = {k: [] for k in model_keys}

        for mk in model_keys:
            resp = p["responses"].get(mk, {})
            if "judge" in resp:
                score = resp["judge"].get("overall_score", 0)
                aggregates[mk]["scores"].append(score)
                aggregates[mk]["latencies"].append(resp.get("latency_ms", 0))
                aggregates[mk]["tokens"].append(resp.get("completion_tokens", 0))
                level_scores[level][mk].append(score)

    # Overall table
    header = f"{'Model':<25} {'Avg Score':>10} {'Avg Latency':>12} {'Avg Tokens':>11} {'N':>4}"
    print(f"\n{header}")
    print("-" * len(header))
    for mk in model_keys:
        agg = aggregates[mk]
        n = len(agg["scores"])
        if n == 0:
            print(
                f"{results['models'][mk]:<25} {'N/A':>10} {'N/A':>12} {'N/A':>11} {0:>4}"
            )
            continue
        avg_score = sum(agg["scores"]) / n
        avg_lat = sum(agg["latencies"]) / n
        avg_tok = sum(agg["tokens"]) / n
        print(
            f"{results['models'][mk]:<25} {avg_score:>9.3f} {avg_lat:>10.0f}ms {avg_tok:>10.0f} {n:>4}"
        )

    # Per-level breakdown
    print(f"\n{'Level':<20}", end="")
    for mk in model_keys:
        print(f" {results['models'][mk]:>22}", end="")
    print()
    print("-" * (20 + 23 * len(model_keys)))

    for level in ["direct", "didal", "didal_literature"]:
        if level not in level_scores:
            continue
        print(f"{level:<20}", end="")
        for mk in model_keys:
            scores = level_scores[level].get(mk, [])
            if scores:
                avg = sum(scores) / len(scores)
                print(f" {avg:>21.3f}", end="")
            else:
                print(f" {'N/A':>22}", end="")
        print()

    # Per-prompt comparison
    print(f"\n{'Prompt':<50}", end="")
    for mk in model_keys:
        print(f" {results['models'][mk]:>12}", end="")
    print(f" {'Winner':>10}")
    print("-" * (50 + 13 * len(model_keys) + 11))

    for p in results["prompts"]:
        prompt_short = (
            p["prompt"][:47] + "..." if len(p["prompt"]) > 47 else p["prompt"]
        )
        print(f"{prompt_short:<50}", end="")

        scores = {}
        for mk in model_keys:
            resp = p["responses"].get(mk, {})
            if "judge" in resp:
                s = resp["judge"].get("overall_score", 0)
                scores[mk] = s
                print(f" {s:>11.3f}", end="")
            else:
                print(f" {'ERR':>12}", end="")

        if len(scores) >= 2:
            winner_key = max(scores, key=scores.get)
            margin = scores[winner_key] - min(scores.values())
            label = results["models"][winner_key].split()[0]
            if margin < 0.02:
                print(f" {'TIE':>10}", end="")
            else:
                print(f" {label:>10}", end="")
        print()

    # Winner declaration
    if len(model_keys) >= 2:
        print()
        totals = {}
        for mk in model_keys:
            agg = aggregates[mk]
            totals[mk] = sum(agg["scores"]) / len(agg["scores"]) if agg["scores"] else 0

        winner = max(totals, key=totals.get)
        loser = min(totals, key=totals.get)
        diff = totals[winner] - totals[loser]
        print(
            f"Overall winner: {results['models'][winner]} ({totals[winner]:.3f} vs {totals[loser]:.3f}, +{diff:.3f})"
        )


def save_results(results: dict):
    """Save full results to JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"benchmark_{timestamp}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="EcoCoder vs DeepSeek benchmark")
    parser.add_argument(
        "--ecocoder-only", action="store_true", help="Only benchmark EcoCoder"
    )
    parser.add_argument(
        "--deepseek-only", action="store_true", help="Only benchmark DeepSeek"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Don't save results to file"
    )
    args = parser.parse_args()

    run_eco = not args.deepseek_only
    run_ds = not args.ecocoder_only

    results = run_benchmark(run_ecocoder=run_eco, run_deepseek=run_ds)
    print_summary(results)

    if not args.no_save:
        save_results(results)


if __name__ == "__main__":
    main()
