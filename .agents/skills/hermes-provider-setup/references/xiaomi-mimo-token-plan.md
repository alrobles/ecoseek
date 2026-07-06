# Xiaomi MiMo Token Plan

Session reference — MiMo Token Plan configuration on Hermes Agent (2026-06-10).

## Credentials

- **Plan**: Token Plan (monthly subscription)
- **Key format**: `tp-` (NOT `sk-`)
- **Endpoint**: `https://token-plan-sgp.xiaomimimo.com/v1` (Singapore region)
- **Other regional endpoints**: `token-plan-cn.xiaomimimo.com` (China)
- **Key location**: `/home/reumanlab/env/mimo-key`

## Models Available (Jun 2026)

| Model | Status |
|---|---|
| `mimo-v2.5-pro` | ✅ Current pro — recommended for agent use |
| `mimo-v2.5` | ✅ Current base |
| `mimo-v2.5-tts` | ✅ TTS |
| `mimo-v2.5-asr` | ✅ Speech recognition |
| `mimo-v2-pro` | ⚠️ Deprecated — auto-routes to v2.5 since Jun 1 |
| `mimo-v2-omni` | ⚠️ Deprecated — auto-routes to v2.5 since Jun 1 |
| `mimo-v2-tts` | ⚠️ Legacy TTS |

Deprecation notice: MiMo-V2-Pro / Omni auto-route to V2.5 (with V2.5 pricing) since June 1, 2026, fully deprecated by June 30, 2026.

## Hermes Config (working setup)

```yaml
# config.yaml
model:
  provider: xiaomi
  default: mimo-v2.5-pro
  base_url: https://token-plan-sgp.xiaomimimo.com/v1

providers:
  xiaomi:
    api_mode: chat_completions
    base_url: https://token-plan-sgp.xiaomimimo.com/v1

fallback_providers: [deepseek, opencode-go, opencode]

credential_pool_strategies:
  xiaomi:
    strategy: rotate_on_quota
    max_retries: 3
```

```bash
# .env
XIAOMI_API_KEY=tp-squrlae560k8pmu7bvi5ttt50s2o4dbio8gpx9h8gluxmctp
XIAOMI_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1
```

## Debugging 401 Errors

When you get `Invalid API Key`:

1. Check key format — Token Plan uses `tp-`, Pay-as-you-go uses `sk-`
2. Check endpoint matches key type — tp- keys need `token-plan-*.xiaomimimo.com`
3. Verify env var name — built-in `xiaomi` provider uses `XIAOMI_API_KEY`, NOT `MIMO_API_KEY`
4. Test key directly: `ExecuteCode` block with `urllib` (avoids shell escaping issues with special chars)
5. `XIAOMI_BASE_URL` env var is read by the built-in `xiaomi` provider to override the default endpoint — without it, the provider uses the default `api.xiaomimimo.com` which rejects tp- keys

## Auth Methods Tested

All three work with the MiMo endpoint (OpenAI-compatible):
- `Authorization: Bearer <key>`
- `X-API-Key: <key>`
- `api-key: <key>`

## Commands Used

```bash
# Register provider
hermes config set providers.xiaomi.api_mode chat_completions
hermes config set providers.xiaomi.base_url https://token-plan-sgp.xiaomimimo.com/v1
hermes config set credential_pool_strategies.xiaomi.strategy rotate_on_quota
hermes config set credential_pool_strategies.xiaomi.max_retries 3

# Set as primary
hermes config set model.provider xiaomi
hermes config set model.default mimo-v2.5-pro
hermes config set model.base_url https://token-plan-sgp.xiaomimimo.com/v1

# Fallback chain (deepseek kicks in if xiaomi fails)
hermes config set fallback_providers "[deepseek, opencode-go, opencode]"
```
