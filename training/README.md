# Nemotron LoRA Training

Fine-tunes **Nemotron-3-Nano-30B** with a LoRA adapter using the DiDAL-generated SFT corpus, targeting the [NVIDIA Nemotron Model Reasoning Challenge](https://www.kaggle.com/competitions/nvidia-nemotron-model-reasoning-challenge).

---

## Pipeline

```
[Your machine / Hermes]                    [KU Cluster]
benchmarks/generate_sft_corpus.py  -->  training/data/sft_corpus.jsonl
                                                 |
                                       sbatch training/train_slurm.sh
                                                 |
                                       training/output/nemotron_lora/
                                                 |
                                       kaggle datasets create ...
                                                 |
                                       [Kaggle Notebook -> Submit]
```

---

## Files

| File | Purpose |
|------|---------|
| `nemotron_lora.yml` | Axolotl config: LoRA rank=16, FSDP multi-GPU, bf16, flash-attention |
| `train_slurm.sh` | SLURM job script for KU cluster (2x A100 80GB) |
| `setup_env.sh` | One-time conda env setup |
| `test_inference.py` | Smoke-test adapter at temperature=0.0 before Kaggle submit |
| `data/` | SFT corpus output (gitignored) |
| `output/` | Checkpoints and logs (gitignored) |

---

## Step-by-step

### 1. Setup environment (once)

```bash
bash training/setup_env.sh
```

### 2. Generate corpus

```bash
HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py \
    --format llama3 \
    --output training/data/sft_corpus.jsonl
```

### 3. Edit SLURM settings

In `train_slurm.sh`, update:
```bash
#SBATCH --partition=gpu       # -> your KU partition (check with: sinfo)
#SBATCH --account=ecoseek     # -> your SLURM account (check with: sacctmgr show user)
```

### 4. Submit job

```bash
sbatch training/train_slurm.sh

# Monitor:
squeue -u $USER
tail -f training/output/slurm_<jobid>.log
```

Expected runtime: **3-5 hours** on 2x A100 80GB.

### 5. Test the adapter

```bash
python3 training/test_inference.py
```

### 6. Upload to Kaggle and submit

```bash
pip install kaggle
kaggle datasets create -p training/output/nemotron_lora/ --dir-mode zip
# Then reference /kaggle/input/your-dataset-name/ in your submission notebook
```

---

## Hardware requirements

| Config | GPUs | VRAM | Est. time |
|--------|------|------|-----------|
| Recommended | 2x A100 80GB | 160 GB | 3-5 h |
| Alternative | 4x A40 48GB | 192 GB | 5-8 h |
| Minimum | 1x H100 80GB | 80 GB | 4-6 h |

---

## Key parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `lora_r` | 16 | Within competition limit of 32 |
| `lora_alpha` | 32 | Standard 2x ratio |
| `sequence_len` | 4096 | Covers full DiDAL responses |
| `learning_rate` | 2e-4 | Standard LoRA SFT |
| `num_epochs` | 4 | Safe for ~40 training examples |
| `bf16` | true | Matches base model dtype |
| `flash_attention` | true | Required for 4096 ctx on A100 |

---

## Troubleshooting

**OOM error on GPU?**
- Reduce `micro_batch_size` to 1
- Reduce `sequence_len` to 2048
- Add `load_in_4bit: true` to switch to QLoRA

**Corpus too small (< 20 examples)?**
- Lower threshold: `--threshold 0.55`
- Add more prompts to `PROMPT_BANK` in `benchmarks/generate_sft_corpus.py`

**SLURM partition not found?**
- Check available partitions: `sinfo`
- Update `#SBATCH --partition=` in `train_slurm.sh`
