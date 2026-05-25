# EcoSeek Benchmarks

Compares ecological answer quality between [EcoCoder-7B](https://huggingface.co/alrobles/EcoCoder-7B) (domain-specialized, 4.5 GB local) and DeepSeek v4 (cloud API).

Uses the DiDAL judge component to score both models on 8 ecological prompts across three complexity levels:
- **Direct** (2 prompts): Simple factual questions
- **DiDAL** (3 prompts): Conceptual scientific questions
- **DiDAL Literature** (3 prompts): Deep synthesis requiring references

---

## Scripts

### `ecocoder_vs_deepseek.py` — Model Quality Benchmark

Compares EcoCoder-7B vs DeepSeek on ecological prompts using the DiDAL judge.

```bash
# Compare both models:
DEEPSEEK_API_KEY=sk-... python3 benchmarks/ecocoder_vs_deepseek.py

# EcoCoder only:
ECOCODER_URL=http://localhost:1234/v1 python3 benchmarks/ecocoder_vs_deepseek.py --ecocoder-only
```

---

### `generate_sft_corpus.py` — Nemotron SFT Corpus Generator

Builds a fine-tuning dataset for LoRA training on **Nemotron-3-Nano-30B** using the DiDAL protocol as a data pipeline.

For each prompt, DiDAL runs the full dialectical loop:
```
classify -> frame -> retrieve (literature only) -> expert_draft -> critique -> revise -> judge
```
Only examples scoring `>= JUDGE_THRESHOLD` (default 0.65) are kept.

#### Quick start

```bash
# Preview prompts (no API calls):
python3 benchmarks/generate_sft_corpus.py --dry-run

# Show prompt bank stats:
python3 benchmarks/generate_sft_corpus.py --stats-only

# Full run (requires HERMES_ECOSEEK_API_KEY):
HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py

# Only ecology + reasoning, Llama-3 format, higher threshold:
HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py \
    --categories ecology reasoning --threshold 0.70 --format llama3

# Alpaca format for other trainers:
HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py --format alpaca
```

#### Output formats

| Format | Description | Ready for |
|--------|-------------|----------|
| `llama3` | Llama-3 chat template (default) | Axolotl, TRL, Unsloth |
| `alpaca` | Instruction/response format | LLaMA-Factory, FastChat |
| `jsonl` | Raw `{prompt, response, meta}` | Custom trainers |

Each output record includes a `meta` block with `judge_score`, `mode`, `critique_rounds`, and `protocol_id` for traceability.

#### Prompt bank (45 prompts)

| Category | Count | Levels |
|----------|-------|--------|
| ecology | 14 | direct, didal, didal_literature |
| reasoning | 10 | direct, didal |
| math | 7 | direct, didal |
| science | 6 | didal, didal_literature |
| multistep | 5 | didal |
| analogy | 3 | didal |
| ethics | 2 | didal |

#### Connecting to Nemotron LoRA training

After generating the corpus, fine-tune with [Axolotl](https://github.com/OpenAccess-AI-Collective/axolotl) or [TRL](https://github.com/huggingface/trl):

```yaml
# axolotl config snippet
base_model: nvidia/Nemotron-3-Nano-30B
adapter: lora
lora_r: 16
lora_alpha: 32
datasets:
  - path: benchmarks/results/sft_corpus_<timestamp>.jsonl
    type: completion
```

The LoRA adapter can then be submitted to the [NVIDIA Nemotron Model Reasoning Challenge](https://www.kaggle.com/competitions/nvidia-nemotron-model-reasoning-challenge) as a Kaggle dataset.

---

## Results

Generated benchmark and corpus files are saved to `benchmarks/results/` (gitignored).
