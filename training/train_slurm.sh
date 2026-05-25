#!/bin/bash
#SBATCH --job-name=nemotron-lora
#SBATCH --output=training/output/slurm_%j.log
#SBATCH --error=training/output/slurm_%j.err
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:a100:2          # 2x A100 80GB -- adjust to cluster availability
#SBATCH --mem=120G
#SBATCH --time=08:00:00            # 8h wall time (training ~3-5h)
#SBATCH --partition=gpu            # TODO: change to your KU cluster partition name
#SBATCH --account=ecoseek          # TODO: change to your SLURM account/project

# ---------------------------------------------------------------------------
# KU Cluster -- Nemotron LoRA Training Job
# Submits Axolotl fine-tuning of Nemotron-3-Nano-30B with DiDAL SFT corpus.
#
# Prerequisites:
#   1. Conda env 'axolotl' created: bash training/setup_env.sh
#   2. Corpus generated: training/data/sft_corpus.jsonl
#   3. Adjust --partition and --account above to your KU cluster values
#
# Submit:
#   sbatch training/train_slurm.sh
#
# Monitor:
#   squeue -u $USER
#   tail -f training/output/slurm_<jobid>.log
# ---------------------------------------------------------------------------

set -euo pipefail

echo "====================================================="
echo " Nemotron LoRA Training -- EcoSeek / DiDAL Corpus"
echo " Job ID : $SLURM_JOB_ID"
echo " Node   : $SLURM_NODELIST"
echo " GPUs   : $SLURM_GPUS_ON_NODE"
echo " Start  : $(date)"
echo "====================================================="

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
module purge
module load cuda/12.1          # adjust to your cluster's CUDA module
module load python/3.11

conda activate axolotl

export PYTHONPATH="$(pwd)/emily/plugins:$PYTHONPATH"
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Uncomment to use a local HF model cache and avoid re-downloading:
# export HF_HOME=/scratch/$USER/hf_cache
# export TRANSFORMERS_CACHE=/scratch/$USER/hf_cache

# Uncomment for W&B experiment tracking:
# export WANDB_API_KEY=your_key_here

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
if [ ! -f "training/data/sft_corpus.jsonl" ]; then
    echo "ERROR: training/data/sft_corpus.jsonl not found."
    echo "Generate it first:"
    echo "  HERMES_ECOSEEK_API_KEY=sk-... python3 benchmarks/generate_sft_corpus.py \\"
    echo "      --format llama3 --output training/data/sft_corpus.jsonl"
    exit 1
fi

CORPUS_LINES=$(wc -l < training/data/sft_corpus.jsonl)
echo "Corpus: $CORPUS_LINES examples"

mkdir -p training/output/nemotron_lora
mkdir -p training/output/logs

# ---------------------------------------------------------------------------
# Launch training
# ---------------------------------------------------------------------------
echo ""
echo "Launching Axolotl training..."
echo ""

torchrun \
    --nproc_per_node="$SLURM_GPUS_ON_NODE" \
    --master_port=29500 \
    -m axolotl.cli.train \
    training/nemotron_lora.yml

EXIT_CODE=$?

echo ""
echo "====================================================="
echo " Training finished -- exit code: $EXIT_CODE"
echo " End: $(date)"
echo "====================================================="

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "Adapter saved to: training/output/nemotron_lora/"
    echo ""
    echo "Next steps:"
    echo "  1. Test: python3 training/test_inference.py"
    echo "  2. Upload: kaggle datasets create -p training/output/nemotron_lora/"
fi

exit $EXIT_CODE
