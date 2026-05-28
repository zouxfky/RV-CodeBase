#!/usr/bin/env bash
# Train a LoRA adapter with Llama-Factory.
#
# Usage:
#   sft/scripts/train.sh <config_yaml> [options]
#
# Options:
#   --model PATH    Override model_name_or_path (HF id or local checkpoint dir)
#   --gpus N        Number of GPUs to use (default: 1; >1 launches with accelerate)
#
# Examples:
#   # single GPU, model from yaml
#   sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml
#
#   # single GPU, override base model with local checkpoint
#   sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml --model /data/models/Qwen3.5-9B
#
#   # 4-GPU multi-card training
#   sft/scripts/train.sh sft/configs/qwen3.5-27b_lora.yaml --gpus 4
#
#   # 8-GPU + local model
#   sft/scripts/train.sh sft/configs/qwen3.5-27b_lora.yaml --gpus 8 --model /data/models/Qwen3.5-27B
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <config_yaml> [--model PATH] [--gpus N]" >&2
    exit 1
fi

CONFIG="$1"; shift
MODEL_OVERRIDE=""
GPUS=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            MODEL_OVERRIDE="$2"; shift 2 ;;
        --gpus)
            GPUS="$2"; shift 2 ;;
        *)
            echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if ! command -v llamafactory-cli >/dev/null 2>&1; then
    echo "llamafactory-cli not found. Install with: pip install llamafactory" >&2
    exit 1
fi

EXTRA_ARGS=()
if [[ -n "${MODEL_OVERRIDE}" ]]; then
    EXTRA_ARGS+=("model_name_or_path=${MODEL_OVERRIDE}")
fi

if [[ "${GPUS}" -le 1 ]]; then
    llamafactory-cli train "${CONFIG}" "${EXTRA_ARGS[@]}"
else
    # llamafactory-cli detects FORCE_TORCHRUN and dispatches to torchrun.
    # NPROC_PER_NODE controls visible local GPUs.
    export FORCE_TORCHRUN=1
    export NPROC_PER_NODE="${GPUS}"
    llamafactory-cli train "${CONFIG}" "${EXTRA_ARGS[@]}"
fi
