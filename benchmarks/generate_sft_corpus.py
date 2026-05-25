#!/usr/bin/env python3
"""Nemotron SFT Corpus Generator — build a fine-tuning dataset using DiDAL.

This script runs the full DiDAL protocol over a curated set of prompts
(ecological + general reasoning) and exports high-quality (prompt, response)
pairs as a JSONL corpus suitable for LoRA fine-tuning on Nemotron-3-Nano-30B.

The DiDAL pipeline ensures each training example has gone through:
  classify → frame → retrieve (didal_literature) → expert_draft → critique → revise

Only examples scoring >= JUDGE_THRESHOLD are kept. This produces a smaller
but higher-quality corpus than raw LLM sampling.

Usage:
  # Full run (requires HERMES_ECOSEEK_API_KEY):
  HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py

  # Dry run — shows prompts without calling Hermes:
  python3 benchmarks/generate_sft_corpus.py --dry-run

  # Custom threshold and output:
  HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py \\
      --threshold 0.70 --output data/my_corpus.jsonl

  # Only a subset of prompt categories:
  HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py \\
      --categories ecology reasoning math

Output formats:
  --format jsonl       Raw JSONL: {prompt, response, judge_score, mode, ...}
  --format llama3      Llama-3 chat template (ready for Axolotl/TRL LoRA)
  --format alpaca      Alpaca instruction format

Requirements:
  - Hermes API key (HERMES_ECOSEEK_API_KEY) for full DiDAL loop
  - Python 3.10+, no extra dependencies
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "emily" / "plugins"))

OUTPUT_DIR = Path(__file__).resolve().parent / "results"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_sft_corpus")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JUDGE_THRESHOLD_DEFAULT = 0.65
MAX_RETRIES = 2
RETRY_DELAY = 5  # seconds

# ---------------------------------------------------------------------------
# Prompt bank
# ---------------------------------------------------------------------------
# Prompts are grouped by category and DiDAL complexity level.
# Each entry: {id, category, level, prompt}
#   level: "direct" | "didal" | "didal_literature"
#   category: used for --categories filtering

PROMPT_BANK: list[dict] = [

    # -- Ecology: Direct ------------------------------------------------
    {
        "id": "eco_direct_1",
        "category": "ecology",
        "level": "direct",
        "prompt": "What is the Shannon diversity index?",
    },
    {
        "id": "eco_direct_2",
        "category": "ecology",
        "level": "direct",
        "prompt": "What is GBIF and what kind of data does it provide?",
    },
    {
        "id": "eco_direct_3",
        "category": "ecology",
        "level": "direct",
        "prompt": "Define carrying capacity in population ecology.",
    },
    {
        "id": "eco_direct_4",
        "category": "ecology",
        "level": "direct",
        "prompt": "What is a trophic cascade?",
    },

    # -- Ecology: DiDAL -------------------------------------------------
    {
        "id": "eco_didal_1",
        "category": "ecology",
        "level": "didal",
        "prompt": "Explain the difference between the fundamental niche and the realized niche.",
    },
    {
        "id": "eco_didal_2",
        "category": "ecology",
        "level": "didal",
        "prompt": "Why do ecological explanations often fail when they ignore spatial scale?",
    },
    {
        "id": "eco_didal_3",
        "category": "ecology",
        "level": "didal",
        "prompt": "Compare the logistic growth model with the Lotka-Volterra competition model. When is each appropriate?",
    },
    {
        "id": "eco_didal_4",
        "category": "ecology",
        "level": "didal",
        "prompt": "How does habitat fragmentation affect species diversity and what mechanisms are responsible?",
    },
    {
        "id": "eco_didal_5",
        "category": "ecology",
        "level": "didal",
        "prompt": "What is beta diversity and how does it differ from alpha and gamma diversity?",
    },
    {
        "id": "eco_didal_6",
        "category": "ecology",
        "level": "didal",
        "prompt": "Explain island biogeography theory and its main predictions.",
    },

    # -- Ecology: DiDAL Literature ---------------------------------------
    {
        "id": "eco_lit_1",
        "category": "ecology",
        "level": "didal_literature",
        "prompt": "What is the fundamental niche, and how has the concept evolved since Hutchinson (1957)?",
    },
    {
        "id": "eco_lit_2",
        "category": "ecology",
        "level": "didal_literature",
        "prompt": "Contrast niche theory and neutral theory in community assembly. What evidence supports each?",
    },
    {
        "id": "eco_lit_3",
        "category": "ecology",
        "level": "didal_literature",
        "prompt": "Summarize the ecological meaning of density dependence and support the answer with key references.",
    },
    {
        "id": "eco_lit_4",
        "category": "ecology",
        "level": "didal_literature",
        "prompt": "What is the species-energy hypothesis and what empirical evidence supports or challenges it?",
    },

    # -- Reasoning: Deductive Logic -------------------------------------
    {
        "id": "reason_ded_1",
        "category": "reasoning",
        "level": "direct",
        "prompt": "All mammals are warm-blooded. Dolphins are mammals. What can you conclude about dolphins?",
    },
    {
        "id": "reason_ded_2",
        "category": "reasoning",
        "level": "direct",
        "prompt": "If it rains, the ground gets wet. The ground is wet. Can we conclude it rained? Explain.",
    },
    {
        "id": "reason_ded_3",
        "category": "reasoning",
        "level": "didal",
        "prompt": "What is the difference between deductive and inductive reasoning? Give a scientific example of each.",
    },
    {
        "id": "reason_ded_4",
        "category": "reasoning",
        "level": "didal",
        "prompt": "Explain the difference between correlation and causation and why it matters in scientific inference.",
    },
    {
        "id": "reason_ded_5",
        "category": "reasoning",
        "level": "didal",
        "prompt": "What is a null hypothesis and why is it logically necessary in hypothesis testing?",
    },
    {
        "id": "reason_ded_6",
        "category": "reasoning",
        "level": "didal",
        "prompt": "Three boxes contain: Box A has only apples, Box B has only oranges, Box C has both. "
                  "All labels are wrong. You pick one fruit from one box. How do you identify all boxes?",
    },

    # -- Reasoning: Causal / Counterfactual ----------------------------
    {
        "id": "reason_causal_1",
        "category": "reasoning",
        "level": "didal",
        "prompt": "A drug trial shows patients who took the drug recovered faster. "
                  "What alternative explanations should be ruled out before concluding the drug works?",
    },
    {
        "id": "reason_causal_2",
        "category": "reasoning",
        "level": "didal",
        "prompt": "Countries with more hospitals have higher death rates. Does this mean hospitals cause deaths? Explain.",
    },
    {
        "id": "reason_causal_3",
        "category": "reasoning",
        "level": "didal",
        "prompt": "What is Simpson's paradox? Give an example and explain why it matters for data interpretation.",
    },
    {
        "id": "reason_causal_4",
        "category": "reasoning",
        "level": "didal",
        "prompt": "Explain the concept of confounding variables and how randomized controlled trials address them.",
    },

    # -- Math: Quantitative Reasoning ----------------------------------
    {
        "id": "math_1",
        "category": "math",
        "level": "direct",
        "prompt": "A population doubles every 3 years. Starting at 100 individuals, what is the population after 9 years?",
    },
    {
        "id": "math_2",
        "category": "math",
        "level": "direct",
        "prompt": "If a species has a growth rate r=0.2 per year and current population N=500, "
                  "what is the instantaneous rate of change dN/dt?",
    },
    {
        "id": "math_3",
        "category": "math",
        "level": "didal",
        "prompt": "Explain the logistic growth equation dN/dt = rN(1 - N/K). "
                  "What does each parameter mean and what happens as N approaches K?",
    },
    {
        "id": "math_4",
        "category": "math",
        "level": "didal",
        "prompt": "A coin is flipped 10 times and lands heads 8 times. "
                  "What is the probability of this outcome if the coin is fair? Show the calculation.",
    },
    {
        "id": "math_5",
        "category": "math",
        "level": "didal",
        "prompt": "Explain the difference between Type I and Type II errors in statistical testing. "
                  "How do they trade off and what determines acceptable thresholds?",
    },
    {
        "id": "math_6",
        "category": "math",
        "level": "didal",
        "prompt": "What is Bayes' theorem? Derive it from conditional probability and give a practical example.",
    },
    {
        "id": "math_7",
        "category": "math",
        "level": "didal",
        "prompt": "Explain the central limit theorem. Why is it important for statistical inference?",
    },

    # -- Science: Hypothesis & Experiment Design -----------------------
    {
        "id": "sci_1",
        "category": "science",
        "level": "didal",
        "prompt": "What makes a good scientific hypothesis? What properties must it have to be testable?",
    },
    {
        "id": "sci_2",
        "category": "science",
        "level": "didal",
        "prompt": "Explain the principle of parsimony (Occam's razor) in scientific model selection.",
    },
    {
        "id": "sci_3",
        "category": "science",
        "level": "didal",
        "prompt": "What is a meta-analysis and when is it more informative than a single study?",
    },
    {
        "id": "sci_4",
        "category": "science",
        "level": "didal",
        "prompt": "Compare frequentist and Bayesian approaches to statistical inference. "
                  "What are the philosophical differences and practical consequences?",
    },
    {
        "id": "sci_5",
        "category": "science",
        "level": "didal_literature",
        "prompt": "What is reproducibility in science and what are the main causes of the reproducibility crisis?",
    },
    {
        "id": "sci_6",
        "category": "science",
        "level": "didal_literature",
        "prompt": "Summarize the debate between gradualism and punctuated equilibrium in evolutionary biology "
                  "and what empirical evidence exists for each.",
    },

    # -- Multi-step Reasoning ------------------------------------------
    {
        "id": "multistep_1",
        "category": "multistep",
        "level": "didal",
        "prompt": "A researcher finds that forest bird diversity decreases near roads. "
                  "Design a study to determine whether this is caused by noise, habitat loss, or predator attraction.",
    },
    {
        "id": "multistep_2",
        "category": "multistep",
        "level": "didal",
        "prompt": "You have two species with overlapping niches. Species A dominates in all lab trials "
                  "but both coexist in the field. What mechanisms could explain this coexistence?",
    },
    {
        "id": "multistep_3",
        "category": "multistep",
        "level": "didal",
        "prompt": "A city introduces a predator to control a pest population. "
                  "Trace the possible consequences through the food web over 5 years.",
    },
    {
        "id": "multistep_4",
        "category": "multistep",
        "level": "didal",
        "prompt": "An AI model performs well on training data but poorly on new data. "
                  "List all possible explanations and how you would diagnose each.",
    },
    {
        "id": "multistep_5",
        "category": "multistep",
        "level": "didal",
        "prompt": "A company's revenue increases every month that they run ads, but also increases "
                  "in months with no ads. How do you determine the true effect of advertising?",
    },

    # -- Analogy & Conceptual Transfer ---------------------------------
    {
        "id": "analogy_1",
        "category": "analogy",
        "level": "didal",
        "prompt": "How is natural selection analogous to a search algorithm? What are the limits of this analogy?",
    },
    {
        "id": "analogy_2",
        "category": "analogy",
        "level": "didal",
        "prompt": "How is the concept of ecological niche similar to and different from the concept of market niche in economics?",
    },
    {
        "id": "analogy_3",
        "category": "analogy",
        "level": "didal",
        "prompt": "Compare the immune system's response to pathogens with how a machine learning model "
                  "generalizes from training data. What are the deep parallels?",
    },

    # -- Ethical Reasoning ---------------------------------------------
    {
        "id": "ethics_1",
        "category": "ethics",
        "level": "didal",
        "prompt": "A conservation program requires culling invasive deer to protect native plants. "
                  "What ethical frameworks apply and how would each evaluate the action?",
    },
    {
        "id": "ethics_2",
        "category": "ethics",
        "level": "didal",
        "prompt": "When is it ethical to use animals in scientific research? "
                  "Describe the key principles and how they are balanced.",
    },
]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

LLAMA3_TEMPLATE = (
    "<|begin_of_text|>"
    "<|start_header_id|>user<|end_header_id|>\n\n"
    "{prompt}"
    "<|eot_id|>"
    "<|start_header_id|>assistant<|end_header_id|>\n\n"
    "{response}"
    "<|eot_id|>"
)

ALPACA_TEMPLATE = (
    "### Instruction:\n{prompt}\n\n"
    "### Response:\n{response}"
)


def format_example(prompt: str, response: str, fmt: str) -> dict:
    """Format a (prompt, response) pair into the requested output format."""
    if fmt == "llama3":
        return {"text": LLAMA3_TEMPLATE.format(prompt=prompt, response=response)}
    elif fmt == "alpaca":
        return {"text": ALPACA_TEMPLATE.format(prompt=prompt, response=response)}
    else:  # jsonl (raw)
        return {"prompt": prompt, "response": response}


# ---------------------------------------------------------------------------
# DiDAL runner
# ---------------------------------------------------------------------------

def run_didal_safe(prompt: str, retries: int = MAX_RETRIES) -> dict | None:
    """Run DiDAL protocol with retry logic. Returns parsed result or None."""
    try:
        from ecoseek.protocol import run_didal_protocol
    except ImportError as e:
        log.error("Cannot import DiDAL protocol: %s", e)
        log.error("Make sure emily/plugins is in sys.path and dependencies are installed.")
        return None

    for attempt in range(retries + 1):
        try:
            raw = run_didal_protocol(prompt)
            result = json.loads(raw)
            return result
        except Exception as exc:
            if attempt < retries:
                log.warning("Attempt %d failed: %s -- retrying in %ds", attempt + 1, exc, RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                log.error("All attempts failed for prompt: %s\nError: %s", prompt[:60], exc)
                return None
    return None


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_corpus(
    prompts: list[dict],
    output_path: Path,
    threshold: float,
    fmt: str,
    dry_run: bool,
) -> dict:
    """Run DiDAL on all prompts and write passing examples to output_path."""
    stats = {
        "total": len(prompts),
        "processed": 0,
        "passed": 0,
        "failed": 0,
        "skipped_low_score": 0,
        "scores": [],
        "by_mode": {},
        "by_category": {},
        "start_time": datetime.now().isoformat(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Starting corpus generation -- %d prompts, threshold=%.2f, format=%s",
             len(prompts), threshold, fmt)
    if dry_run:
        log.info("DRY RUN -- printing prompts only, no Hermes calls")

    with open(output_path, "w", encoding="utf-8") as out_f:
        for i, p in enumerate(prompts, 1):
            prompt_text = p["prompt"]
            category = p.get("category", "unknown")
            level = p.get("level", "didal")
            pid = p.get("id", f"p{i}")

            print(f"\n[{i}/{len(prompts)}] {pid} ({category}/{level})")
            print(f"  Q: {prompt_text[:80]}{'...' if len(prompt_text) > 80 else ''}")

            if dry_run:
                print("  -> DRY RUN skipped")
                continue

            result = run_didal_safe(prompt_text)
            stats["processed"] += 1

            if result is None or not result.get("success"):
                log.warning("  -> FAILED (no result)")
                stats["failed"] += 1
                continue

            judge_score = result.get("judge", {}).get("overall_score", 0.0)
            verdict = result.get("judge", {}).get("verdict", "unknown")
            mode = result.get("mode", level)
            critique_rounds = result.get("critique_rounds", 0)
            elapsed = result.get("elapsed_seconds", 0)

            stats["scores"].append(judge_score)
            stats["by_mode"][mode] = stats["by_mode"].get(mode, 0) + 1
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

            print(f"  -> score={judge_score:.3f} verdict={verdict} mode={mode} "
                  f"rounds={critique_rounds} elapsed={elapsed}s")

            if judge_score < threshold:
                log.info("  -> REJECTED (score %.3f < threshold %.2f)", judge_score, threshold)
                stats["skipped_low_score"] += 1
                continue

            # Build output record
            base = format_example(prompt_text, result["content"], fmt)
            record = {
                **base,
                "meta": {
                    "id": pid,
                    "category": category,
                    "level": level,
                    "mode": mode,
                    "judge_score": judge_score,
                    "verdict": verdict,
                    "critique_rounds": critique_rounds,
                    "elapsed_seconds": elapsed,
                    "protocol_id": result.get("protocol_id", ""),
                    "generated_at": datetime.now().isoformat(),
                },
            }

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()  # flush per record for crash safety
            stats["passed"] += 1
            log.info("  -> ACCEPTED (%.3f)", judge_score)

    stats["end_time"] = datetime.now().isoformat()
    if stats["scores"]:
        stats["avg_score"] = round(sum(stats["scores"]) / len(stats["scores"]), 3)
        stats["min_score"] = round(min(stats["scores"]), 3)
        stats["max_score"] = round(max(stats["scores"]), 3)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate SFT corpus from DiDAL protocol for Nemotron LoRA fine-tuning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--threshold", type=float, default=JUDGE_THRESHOLD_DEFAULT,
        help=f"Minimum judge score to include an example (default: {JUDGE_THRESHOLD_DEFAULT})",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSONL path (default: benchmarks/results/sft_corpus_<timestamp>.jsonl)",
    )
    parser.add_argument(
        "--format", choices=["jsonl", "llama3", "alpaca"], default="llama3",
        help="Output format (default: llama3 -- ready for Axolotl/TRL)",
    )
    parser.add_argument(
        "--categories", nargs="+",
        choices=["ecology", "reasoning", "math", "science", "multistep", "analogy", "ethics"],
        help="Only run prompts from these categories (default: all)",
    )
    parser.add_argument(
        "--levels", nargs="+",
        choices=["direct", "didal", "didal_literature"],
        help="Only run prompts at these DiDAL levels (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print prompts without calling Hermes (no API calls)",
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Print stats about the prompt bank and exit",
    )
    args = parser.parse_args()

    # Stats mode
    if args.stats_only:
        from collections import Counter
        cats = Counter(p["category"] for p in PROMPT_BANK)
        levels = Counter(p["level"] for p in PROMPT_BANK)
        print(f"Total prompts: {len(PROMPT_BANK)}")
        print("By category:", dict(cats))
        print("By level:", dict(levels))
        return

    # Filter prompts
    prompts = PROMPT_BANK
    if args.categories:
        prompts = [p for p in prompts if p["category"] in args.categories]
    if args.levels:
        prompts = [p for p in prompts if p["level"] in args.levels]

    if not prompts:
        log.error("No prompts match the selected filters.")
        sys.exit(1)

    # Resolve output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"sft_corpus_{timestamp}.jsonl"

    # Check Hermes key
    if not args.dry_run and not os.environ.get("HERMES_ECOSEEK_API_KEY"):
        log.error("HERMES_ECOSEEK_API_KEY is not set.")
        log.error("Set it or use --dry-run to preview prompts without API calls.")
        sys.exit(1)

    # Run
    print("=" * 70)
    print("Nemotron SFT Corpus Generator -- DiDAL Protocol")
    print(f"Prompts: {len(prompts)} | Threshold: {args.threshold} | Format: {args.format}")
    print(f"Output: {output_path}")
    print("=" * 70)

    stats = generate_corpus(
        prompts=prompts,
        output_path=output_path,
        threshold=args.threshold,
        fmt=args.format,
        dry_run=args.dry_run,
    )

    # Print summary
    print("\n" + "=" * 70)
    print("CORPUS GENERATION SUMMARY")
    print("=" * 70)
    if not args.dry_run:
        print(f"  Total prompts   : {stats['total']}")
        print(f"  Processed       : {stats['processed']}")
        print(f"  Accepted        : {stats['passed']}  (score >= {args.threshold})")
        print(f"  Rejected        : {stats['skipped_low_score']}  (score < {args.threshold})")
        print(f"  Failed          : {stats['failed']}")
        if stats.get("avg_score"):
            print(f"  Avg score       : {stats['avg_score']}")
            print(f"  Score range     : [{stats['min_score']}, {stats['max_score']}]")
        print(f"  By mode         : {stats['by_mode']}")
        print(f"  By category     : {stats['by_category']}")
        print(f"  Output file     : {output_path}")

        # Save stats JSON alongside corpus
        stats_path = output_path.with_suffix(".stats.json")
        with open(stats_path, "w") as sf:
            json.dump(stats, sf, indent=2, ensure_ascii=False)
        print(f"  Stats file      : {stats_path}")
    else:
        print(f"  DRY RUN: {len(prompts)} prompts would be processed.")
        for p in prompts:
            print(f"  [{p['level']:20s}] {p['prompt'][:65]}")


if __name__ == "__main__":
    main()
