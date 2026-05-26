#!/usr/bin/env python3
"""Benchmark hermes.ecoseek.org — TTFT, token throughput, total latency.

Measures all 3 models: hermes-fast, hermes-agent, hermes-reasoner.
Each model tested with short + medium + long prompts, 3 runs each.
"""
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field

HERMES_URL = os.environ.get("HERMES_URL", "https://hermes.ecoseek.org")
API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")

if not API_KEY:
    print("ERROR: HERMES_ECOSEEK_API_KEY not set")
    sys.exit(1)

MODELS = ["hermes-fast", "hermes-agent", "hermes-reasoner"]

PROMPTS = {
    "short": "Say pong.",
    "medium": "Explain the concept of species distribution modeling in 3 sentences.",
    "long": (
        "You are an ecological research assistant. Compare and contrast "
        "MaxEnt vs GLM approaches for presence-only species distribution "
        "modeling. Include: (1) mathematical foundations, (2) assumptions, "
        "(3) strengths and weaknesses, (4) when to use each. Be concise "
        "but thorough."
    ),
}

RUNS_PER_COMBO = 3


@dataclass
class RunResult:
    model: str
    prompt_type: str
    ttft_ms: float  # time to first token (streaming) or full response
    total_ms: float
    prompt_tokens: int
    completion_tokens: int
    tokens_per_sec: float
    cached_tokens: int
    error: str = ""


def benchmark_non_streaming(model: str, prompt: str) -> RunResult:
    """Non-streaming request — measures total latency + usage."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{HERMES_URL}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "EcoSeek-Benchmark/1.0",
            "Accept": "application/json",
        },
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return RunResult(
            model=model, prompt_type="", ttft_ms=0, total_ms=0,
            prompt_tokens=0, completion_tokens=0, tokens_per_sec=0,
            cached_tokens=0, error=str(e)[:200],
        )
    t1 = time.perf_counter()

    total_ms = (t1 - t0) * 1000
    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    tps = completion_tokens / (total_ms / 1000) if total_ms > 0 else 0

    return RunResult(
        model=model, prompt_type="",
        ttft_ms=total_ms,  # non-streaming: TTFT ≈ total
        total_ms=total_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens_per_sec=round(tps, 1),
        cached_tokens=cached_tokens,
    )


def benchmark_streaming(model: str, prompt: str) -> RunResult:
    """Streaming request — measures true TTFT + throughput."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.1,
        "stream": True,
    }).encode()

    req = urllib.request.Request(
        f"{HERMES_URL}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "EcoSeek-Benchmark/1.0",
            "Accept": "text/event-stream",
        },
    )

    t0 = time.perf_counter()
    ttft = None
    token_count = 0
    full_content = ""
    usage_data = {}

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            buffer = b""
            while True:
                chunk = resp.read(1)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line or line == b"data: [DONE]":
                        continue
                    if line.startswith(b"data: "):
                        try:
                            event = json.loads(line[6:])
                            # Check for first content token
                            choices = event.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content and ttft is None:
                                    ttft = (time.perf_counter() - t0) * 1000
                                if content:
                                    token_count += 1
                                    full_content += content
                            # Check for usage in final chunk
                            if "usage" in event:
                                usage_data = event["usage"]
                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        return RunResult(
            model=model, prompt_type="", ttft_ms=0, total_ms=0,
            prompt_tokens=0, completion_tokens=0, tokens_per_sec=0,
            cached_tokens=0, error=str(e)[:200],
        )

    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000
    if ttft is None:
        ttft = total_ms

    prompt_tokens = usage_data.get("prompt_tokens", 0)
    completion_tokens = usage_data.get("completion_tokens", token_count)
    cached_tokens = usage_data.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    gen_time = (total_ms - ttft) / 1000 if total_ms > ttft else total_ms / 1000
    tps = completion_tokens / gen_time if gen_time > 0 else 0

    return RunResult(
        model=model, prompt_type="",
        ttft_ms=round(ttft, 1),
        total_ms=round(total_ms, 1),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens_per_sec=round(tps, 1),
        cached_tokens=cached_tokens,
    )


def main():
    print("=" * 80)
    print("HERMES ENDPOINT BENCHMARK")
    print(f"URL: {HERMES_URL}")
    print(f"Models: {', '.join(MODELS)}")
    print(f"Runs per combo: {RUNS_PER_COMBO}")
    print("=" * 80)

    # Warmup
    print("\n--- Warmup (1 request per model) ---")
    for model in MODELS:
        r = benchmark_non_streaming(model, "Say hi.")
        status = f"{r.total_ms:.0f}ms" if not r.error else f"ERROR: {r.error}"
        print(f"  {model}: {status}")

    results: list[RunResult] = []

    # Non-streaming benchmark
    print("\n--- Non-Streaming Benchmark ---")
    print(f"{'Model':<20} {'Prompt':<10} {'Run':<5} {'Total ms':<12} {'Comp tok':<10} {'tok/s':<10} {'Cached':<8}")
    print("-" * 80)

    for model in MODELS:
        for ptype, prompt in PROMPTS.items():
            for run in range(RUNS_PER_COMBO):
                r = benchmark_non_streaming(model, prompt)
                r.prompt_type = ptype
                results.append(r)
                if r.error:
                    print(f"{model:<20} {ptype:<10} {run+1:<5} ERROR: {r.error[:40]}")
                else:
                    print(f"{model:<20} {ptype:<10} {run+1:<5} {r.total_ms:<12.0f} {r.completion_tokens:<10} {r.tokens_per_sec:<10.1f} {r.cached_tokens:<8}")

    # Streaming benchmark (TTFT focus)
    print("\n--- Streaming Benchmark (TTFT) ---")
    print(f"{'Model':<20} {'Prompt':<10} {'Run':<5} {'TTFT ms':<12} {'Total ms':<12} {'Comp tok':<10} {'tok/s':<10}")
    print("-" * 80)

    streaming_results: list[RunResult] = []
    for model in MODELS:
        for ptype, prompt in PROMPTS.items():
            for run in range(RUNS_PER_COMBO):
                r = benchmark_streaming(model, prompt)
                r.prompt_type = ptype
                streaming_results.append(r)
                if r.error:
                    print(f"{model:<20} {ptype:<10} {run+1:<5} ERROR: {r.error[:40]}")
                else:
                    print(f"{model:<20} {ptype:<10} {run+1:<5} {r.ttft_ms:<12.1f} {r.total_ms:<12.1f} {r.completion_tokens:<10} {r.tokens_per_sec:<10.1f}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY (averages across runs)")
    print("=" * 80)

    print(f"\n{'Model':<20} {'Prompt':<10} {'Avg Total ms':<14} {'Avg TTFT ms':<14} {'Avg tok/s':<12} {'Avg Comp tok':<14}")
    print("-" * 80)

    for model in MODELS:
        for ptype in PROMPTS:
            ns_runs = [r for r in results if r.model == model and r.prompt_type == ptype and not r.error]
            s_runs = [r for r in streaming_results if r.model == model and r.prompt_type == ptype and not r.error]

            avg_total = sum(r.total_ms for r in ns_runs) / len(ns_runs) if ns_runs else 0
            avg_ttft = sum(r.ttft_ms for r in s_runs) / len(s_runs) if s_runs else 0
            avg_tps = sum(r.tokens_per_sec for r in ns_runs) / len(ns_runs) if ns_runs else 0
            avg_comp = sum(r.completion_tokens for r in ns_runs) / len(ns_runs) if ns_runs else 0

            print(f"{model:<20} {ptype:<10} {avg_total:<14.0f} {avg_ttft:<14.1f} {avg_tps:<12.1f} {avg_comp:<14.0f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
