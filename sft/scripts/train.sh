#!/usr/bin/env bash
# Train a LoRA adapter with Llama-Factory.
#
# Usage:
#   sft/scripts/train.sh <config_yaml> [options]
#
# Options:
#   --model PATH    Override model_name_or_path (HF id or local checkpoint dir)
#   --gpus N        Number of GPUs to use (default: 1; >1 launches with accelerate)
#   --resume [DIR]  Resume from a checkpoint. Without DIR, picks up the most
#                   recent checkpoint-* under the yaml's output_dir.
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
#   # resume after a network/host crash (auto-pick latest checkpoint)
#   sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml --gpus 4 --resume
#
#   # resume from a specific checkpoint
#   sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml --resume sft/results/qwen3.5-9b-lora/checkpoint-1000
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <config_yaml> [--model PATH] [--gpus N] [--resume [DIR]]" >&2
    exit 1
fi

CONFIG="$1"; shift
MODEL_OVERRIDE=""
GPUS=1
RESUME_DIR=""
RESUME_AUTO=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            MODEL_OVERRIDE="$2"; shift 2 ;;
        --gpus)
            GPUS="$2"; shift 2 ;;
        --resume)
            # If next arg looks like a path (not another --flag), use it. Otherwise auto.
            if [[ $# -ge 2 && "$2" != --* ]]; then
                RESUME_DIR="$2"; shift 2
            else
                RESUME_AUTO=1; shift 1
            fi ;;
        *)
            echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if ! command -v llamafactory-cli >/dev/null 2>&1; then
    echo "llamafactory-cli not found. Install with: pip install llamafactory" >&2
    exit 1
fi

# Auto-pick the latest checkpoint-* under the yaml's output_dir.
if [[ "${RESUME_AUTO}" -eq 1 ]]; then
    OUTPUT_DIR="$(grep -E '^\s*output_dir:' "${CONFIG}" | head -1 | sed -E 's/.*output_dir:\s*//' | tr -d '"' | tr -d "'")"
    if [[ -z "${OUTPUT_DIR}" || ! -d "${OUTPUT_DIR}" ]]; then
        echo "[--resume] no output_dir found or directory missing: ${OUTPUT_DIR}" >&2
        exit 1
    fi
    RESUME_DIR="$(ls -d "${OUTPUT_DIR}"/checkpoint-* 2>/dev/null | sort -V | tail -1 || true)"
    if [[ -z "${RESUME_DIR}" ]]; then
        echo "[--resume] no checkpoint-* found under ${OUTPUT_DIR}" >&2
        exit 1
    fi
    echo "[--resume] picked latest checkpoint: ${RESUME_DIR}"
fi

EXTRA_ARGS=()
if [[ -n "${MODEL_OVERRIDE}" ]]; then
    EXTRA_ARGS+=("model_name_or_path=${MODEL_OVERRIDE}")
fi
if [[ -n "${RESUME_DIR}" ]]; then
    EXTRA_ARGS+=("resume_from_checkpoint=${RESUME_DIR}")
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
