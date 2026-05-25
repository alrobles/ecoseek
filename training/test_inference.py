#!/usr/bin/env python3
"""Quick inference test for the trained Nemotron LoRA adapter.

Runs 3 sample prompts at temperature=0.0 (same as Kaggle eval)
to verify the adapter loads and produces reasonable output.

Usage:
  python3 training/test_inference.py
  python3 training/test_inference.py --adapter training/output/nemotron_lora
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

DEFAULT_ADAPTER = "training/output/nemotron_lora"
DEFAULT_BASE = "metric/nemotron-3-nano-30b-a3b-bf16"

TEST_PROMPTS = [
    "What is the Shannon diversity index?",
    "Explain the difference between correlation and causation.",
    "A population doubles every 3 years. Starting at 100, what is the size after 9 years?",
]

LLAMA3_TEMPLATE = (
    "<|begin_of_text|>"
    "<|start_header_id|>user<|end_header_id|>\n\n"
    "{prompt}"
    "<|eot_id|>"
    "<|start_header_id|>assistant<|end_header_id|>\n\n"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default=DEFAULT_ADAPTER)
    parser.add_argument("--base-model", default=DEFAULT_BASE)
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    adapter_path = Path(args.adapter)
    if not adapter_path.exists():
        print(f"ERROR: Adapter not found at {adapter_path}")
        print("Run training first: sbatch training/train_slurm.sh")
        return

    print("Loading model + adapter...")
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("ERROR: pip install transformers peft torch")
        return

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base, str(adapter_path))
    model.eval()

    print(f"\nTesting {len(TEST_PROMPTS)} prompts (temperature=0.0, same as Kaggle eval)")
    print("=" * 70)

    for i, prompt in enumerate(TEST_PROMPTS, 1):
        print(f"\n[{i}] {prompt}")
        print("-" * 50)
        formatted = LLAMA3_TEMPLATE.format(prompt=prompt)
        inputs = tokenizer(formatted, return_tensors="pt").to(model.device)

        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_tokens,
                do_sample=False,           # greedy = temperature 0.0
                pad_token_id=tokenizer.eos_token_id,
            )
        elapsed = round((time.time() - t0) * 1000)

        generated = outputs[0][inputs["input_ids"].shape[1]:]
        response = tokenizer.decode(generated, skip_special_tokens=True)
        print(response[:800])
        print(f"\n[{len(generated)} tokens, {elapsed}ms]")

    print("\n" + "=" * 70)
    print("All prompts done. If output looks good, upload adapter to Kaggle:")
    print("  kaggle datasets create -p training/output/nemotron_lora/")


if __name__ == "__main__":
    main()
