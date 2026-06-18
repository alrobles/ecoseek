---
name: model-fusion
description: "Multi-model fusion pattern — combine free/cheap LLMs to match expensive model quality. Panel + Judge architecture for ensemble reasoning."
category: devops
---

# Model Fusion: Multi-Model Ensemble with Judge

Combine multiple free/cheap LLMs to achieve quality comparable to expensive frontier models. Inspired by OpenRouter's Fusion plugin, but implemented with any providers.

## Architecture

```
User Prompt
    |
    v
+-------------------+
|   PANEL (parallel) |
|   - mimo-v2.5-pro  |
|   - deepseek-v4    |
|   - (option: 3rd)  |
+-------------------+
    |
    v (all responses)
+-------------------+
|   JUDGE model      |
|   Compares, finds: |
|   - consensus      |
|   - contradictions |
|   - unique insights|
|   - blind spots    |
+-------------------+
    |
    v (structured analysis)
+-------------------+
|   FINAL ANSWER     |
|   Model uses judge |
|   analysis to write|
|   best response    |
+-------------------+
```

## When to Use

- Complex questions where being wrong is costly
- Research, expert critique, multi-perspective tasks
- Ecological analysis, SDM decisions, literature review
- NOT for simple/short prompts (overkill)

## Implementation

### Python Script (recommended)

```python
import asyncio
import httpx
import json
import time

PROVIDERS = {
    "xiaomi": {
        "url": "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
        "model": "mimo-v2.5-pro",
        "key_env": "XIAOMI_API_KEY"
    },
    "deepseek": {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY"
    }
}

JUDGE_PROVIDER = "deepseek"  # or use openrouter for better judge

async def call_model(provider_config, messages, api_key):
    """Call a single model and return response."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            provider_config["url"],
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": provider_config["model"],
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 2000
            }
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

async def panel_call(prompt, providers_to_use=None):
    """Send prompt to multiple models in parallel."""
    if providers_to_use is None:
        providers_to_use = list(PROVIDERS.keys())
    
    import os
    tasks = []
    for name in providers_to_use:
        cfg = PROVIDERS[name]
        api_key = os.environ.get(cfg["key_env"], "")
        messages = [{"role": "user", "content": prompt}]
        tasks.append(call_model(cfg, messages, api_key))
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    results = {}
    for name, resp in zip(providers_to_use, responses):
        if isinstance(resp, Exception):
            results[name] = f"ERROR: {resp}"
        else:
            results[name] = resp
    return results

def build_judge_prompt(original_prompt, panel_responses):
    """Build prompt for judge model."""
    responses_text = ""
    for model, response in panel_responses.items():
        responses_text += f"\n--- {model} ---\n{response}\n"
    
    return f"""You are a judge comparing multiple AI model responses.

ORIGINAL QUESTION: {original_prompt}

MODEL RESPONSES:{responses_text}

Analyze ALL responses and produce a structured JSON analysis:
{{
  "consensus": ["points all/most models agree on"],
  "contradictions": ["where models disagree"],
  "unique_insights": {{"model": ["unique points from each model"]}},
  "blind_spots": ["what none of them addressed"],
  "best_elements": ["the strongest parts from any response"],
  "recommended_approach": "your recommendation for the best answer"
}}

Respond ONLY with valid JSON."""

async def fusion(prompt):
    """Full fusion pipeline: panel → judge → final answer."""
    import os
    start = time.time()
    
    # Step 1: Panel
    print("Step 1: Running panel...")
    panel_responses = await panel_call(prompt)
    for model, resp in panel_responses.items():
        print(f"  {model}: {len(resp)} chars")
    
    # Step 2: Judge
    print("Step 2: Running judge...")
    judge_prompt = build_judge_prompt(prompt, panel_responses)
    judge_key = os.environ.get(PROVIDERS[JUDGE_PROVIDER]["key_env"], "")
    judge_messages = [{"role": "user", "content": judge_prompt}]
    judge_analysis = await call_model(
        PROVIDERS[JUDGE_PROVIDER], judge_messages, judge_key
    )
    print(f"  Judge analysis: {len(judge_analysis)} chars")
    
    # Step 3: Final answer
    print("Step 3: Generating final answer...")
    final_prompt = f"""Based on this multi-model analysis:

{judge_analysis}

Original question: {prompt}

Write the best possible answer combining the consensus points, 
unique insights, and best elements identified by the judge."""
    
    final_key = os.environ.get(PROVIDERS[JUDGE_PROVIDER]["key_env"], "")
    final_messages = [{"role": "user", "content": final_prompt}]
    final_answer = await call_model(
        PROVIDERS[JUDGE_PROVIDER], final_messages, final_key
    )
    
    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")
    
    return {
        "answer": final_answer,
        "panel_responses": panel_responses,
        "judge_analysis": judge_analysis,
        "elapsed_seconds": elapsed
    }

# Usage:
# result = asyncio.run(fusion("Your complex question here"))
# print(result["answer"])
```

### Hermes Subagents (alternative)

```python
# Using Hermes delegate_task for parallel execution
# 1. Spawn 2 subagents with different providers
# 2. Collect responses
# 3. Spawn judge subagent
# 4. Return final answer
```

## Measuring Quality

### Benchmark Protocol

1. Create 10-20 test questions with known good answers
2. Run single model (baseline) → score
3. Run fusion → score
4. Compare: quality improvement vs latency cost

### Metrics

| Metric | Single Model | Fusion |
|--------|-------------|--------|
| Accuracy | baseline | +X% |
| Completeness | baseline | +X% |
| Latency | ~3s | ~8-12s |
| Cost (free providers) | $0 | $0 |
| Cost (openrouter) | $0 | ~$0.05-0.20/query |

### Scoring Rubric

- 0: Wrong/misleading
- 1: Partially correct, missing key points
- 2: Correct but incomplete
- 3: Correct and complete
- 4: Correct, complete, with unique insights

## Cost Analysis

| Setup | Cost/Query | Quality |
|-------|-----------|---------|
| Single free model | $0 | Good |
| Fusion (all free) | $0 | Better |
| Fusion (free panel + paid judge) | ~$0.01-0.05 | Best |
| OpenRouter Fusion | ~$0.05-0.20 | Best+ |

## Pitfalls

1. **Latency**: Fusion takes 3-4x longer than single model. Don't use for simple queries.
2. **Judge quality matters most**: A weak judge can't synthesize well. Use the best model you can afford as judge.
3. **Panel diversity helps**: Using 2 copies of the same model is less useful than 2 different models.
4. **JSON parsing**: Judge output may not be valid JSON. Use try/except and fallback to raw text.
5. **Token limits**: Panel responses + judge prompt can be long. Watch context windows.

## For Ebbe Nielsen Challenge

This pattern demonstrates that:
- Free/cheap models can match expensive ones through ensemble
- The "wisdom of crowds" applies to LLMs
- Structured deliberation (judge) improves over simple averaging
- Cost: $0 with free providers vs $0.20+ with frontier models

Key message: "You don't need GPT-4 to get GPT-4 quality."
