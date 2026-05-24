#!/usr/bin/env bash
# Train a LoRA adapter with Llama-Factory.
#
# Usage:
#   benchmark/sft/scripts/train.sh <config_yaml>
# Example:
#   benchmark/sft/scripts/train.sh benchmark/sft/configs/qwen3.5-9b_lora.yaml
set -euo pipefail

CONFIG="${1:-benchmark/sft/configs/qwen3.5-9b_lora.yaml}"

if ! command -v llamafactory-cli >/dev/null 2>&1; then
    echo "llamafactory-cli not found. Install with: pip install llamafactory" >&2
    exit 1
fi

llamafactory-cli train "${CONFIG}"
