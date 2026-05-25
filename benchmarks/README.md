# EcoSeek Benchmarks

## EcoCoder-7B vs DeepSeek

Compares ecological answer quality between [EcoCoder-7B](https://huggingface.co/alrobles/EcoCoder-7B) (domain-specialized, 4.5 GB local) and DeepSeek v4 (cloud API).

Uses the DiDAL judge component to score both models on 8 ecological prompts across three complexity levels:
- **Direct** (2 prompts): Simple factual questions
- **DiDAL** (3 prompts): Conceptual scientific questions
- **DiDAL Literature** (3 prompts): Deep synthesis requiring references

### Judge Criteria (6 dimensions)

| Criterion | Weight | What it measures |
|-----------|--------|------------------|
| Scientific accuracy | 0.25 | Factual correctness |
| Evidence grounding | 0.20 | Source citation and support |
| Depth | 0.15 | Avoids superficiality |
| Report structure | 0.15 | Mini-report format quality |
| Definition clarity | 0.15 | Distinguishes definition from interpretation |
| Perspective contrast | 0.10 | Contrasts competing views |

### Usage

```bash
# Both models (requires both endpoints):
ECOCODER_URL=http://localhost:1234/v1 \
DEEPSEEK_API_KEY=sk-... \
python3 benchmarks/ecocoder_vs_deepseek.py

# EcoCoder only (via LM Studio):
ECOCODER_URL=http://localhost:1234/v1 \
python3 benchmarks/ecocoder_vs_deepseek.py --ecocoder-only

# EcoCoder via Ollama:
ECOCODER_URL=http://localhost:11434/v1 \
ECOCODER_MODEL=hf.co/alrobles/EcoCoder-7B \
python3 benchmarks/ecocoder_vs_deepseek.py --ecocoder-only

# DeepSeek only:
DEEPSEEK_API_KEY=sk-... \
python3 benchmarks/ecocoder_vs_deepseek.py --deepseek-only
```

### Output

The script prints a comparison table and saves full results (including raw responses and per-criterion scores) to `benchmarks/results/benchmark_YYYYMMDD_HHMMSS.json`.

### EcoCoder-7B Setup

**LM Studio** (recommended for interactive use):
1. Download from [HuggingFace](https://huggingface.co/alrobles/EcoCoder-7B)
2. Load `ecocoder-7b-q4_k_m.gguf` in LM Studio
3. Start the server (default: `http://localhost:1234/v1`)

**Ollama**:
```bash
ollama run hf.co/alrobles/EcoCoder-7B
# Endpoint: http://localhost:11434/v1
```

> **Note:** EcoCoder-7B is a ~4.5 GB GGUF model (Qwen2.5-Coder-7B + ecological LoRA, Q4_K_M quantization). First download may take several minutes depending on connection speed.
