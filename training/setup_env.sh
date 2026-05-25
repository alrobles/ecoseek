#!/bin/bash
# One-time setup: creates conda env 'axolotl' with all training dependencies.
# Run from repo root before submitting the SLURM job:
#   bash training/setup_env.sh

set -euo pipefail

echo "Setting up Axolotl environment for Nemotron LoRA training..."

conda create -n axolotl python=3.11 -y
conda activate axolotl

# PyTorch with CUDA 12.1 (adjust if your cluster uses a different CUDA version)
pip install torch==2.3.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Axolotl with Flash Attention and FSDP support
pip install "axolotl[flash-attn,fsdp]"

# Core dependencies
pip install \
    "transformers>=4.40.0" \
    "peft>=0.10.0" \
    "datasets>=2.18.0" \
    "accelerate>=0.28.0" \
    "bitsandbytes>=0.43.0" \
    scipy \
    sentencepiece \
    protobuf

# Optional: W&B experiment tracking
# pip install wandb

echo ""
echo "Done. Verify with:"
echo "  conda activate axolotl && python -c 'import axolotl; print(axolotl.__version__)'"
