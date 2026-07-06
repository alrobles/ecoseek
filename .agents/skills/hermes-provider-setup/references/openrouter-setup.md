# OpenRouter Provider Setup

Added 2026-06-18. OpenRouter gives access to hundreds of models via a single API endpoint.

## Credentials

- **Key format**: `sk-or-...`
- **Key location**: `/home/reumanlab/env/openrouter-key`
- **Endpoint**: `https://openrouter.ai/api/v1` (built-in, no need to set base_url)
- **Env var**: `OPENROUTER_API_KEY`

## Setup

```bash
# Add key to .env
echo "OPENROUTER_API_KEY=$(cat /home/reumanlab/env/openrouter-key)" >> ~/.hermes/.env

# Register provider
hermes config set providers.openrouter.api_mode chat_completions

# Add to fallback chain
hermes config set fallback_providers "[deepseek, openrouter]"
```

No need to set `base_url` — OpenRouter is a built-in provider in Hermes.

## Fusion Plugin

OpenRouter Fusion sends a prompt to a panel of models in parallel, then a judge
model synthesizes structured analysis (consensus, contradictions, unique insights,
blind spots). Useful for complex queries where single-model answers aren't enough.

### API usage (direct, not via Hermes)
```bash
curl -s https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $(cat /home/reumanlab/env/openrouter-key)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter/fusion",
    "messages": [{"role": "user", "content": "your prompt"}]
  }'
```

### Custom panel config
```json
{
  "model": "openrouter/fusion",
  "plugins": [{
    "id": "fusion",
    "analysis_models": [
      "~anthropic/claude-opus-latest",
      "~openai/gpt-latest",
      "~google/gemini-pro-latest"
    ],
    "model": "~openai/gpt-latest"
  }]
}
```

### Presets
- `general-high` — strongest all-round panel (claude opus, gpt, gemini)
- `general-budget` — cheaper panel with frontier judge

### How it works
1. Panel (up to 8 models) answers in parallel, each with web_search + web_fetch
2. Judge compares all responses → structured JSON (consensus, contradictions, coverage, unique insights, blind spots)
3. Your model uses that analysis to write the final answer

### Cost consideration
Each Fusion call uses ~4-9 API calls (panel + judge). Reserve for complex tasks.

### Fusion DIY (free alternative)
Imitate Fusion using free providers — no OpenRouter cost:

```
Panel (parallel, free):
  - xiaomi/mimo-v2.5-pro
  - deepseek/deepseek-v4-pro

Judge (sequential, free):
  - deepseek-v4-pro (or mimo)
```

Total: 3 calls per query, $0 cost. For complex queries where single-model
answers aren't enough. Use Hermes `delegate_task` with parallel subagents
for the panel, then a final subagent as judge.

Quality comparison: run same prompts through single model vs DIY fusion,
measure with a scoring rubric. If DIY fusion gets 80%+ of OpenRouter Fusion
quality at $0 cost, it wins for most tasks.

## Key models available via OpenRouter (Jun 2026)
- `~anthropic/claude-opus-latest` — strongest reasoning
- `~openai/gpt-latest` — GPT-4.x series
- `~google/gemini-pro-latest` — Google flagship
- `openrouter/fusion` — meta-model using Fusion plugin
- Free models available with rate limits (see FAQ)

## Pitfalls
- OpenRouter is paid — unlike xiaomi/deepseek which are free Token Plan
- Fusion model alias `openrouter/fusion` resolves to a real model + plugin automatically
- `analysis_models` in Fusion config uses `~provider/model` syntax (tilde prefix)
- Hermes built-in provider means no `base_url` config needed, just the API key
