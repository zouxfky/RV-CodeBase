#!/usr/bin/env bash
# Serve a merged SFT model with vLLM as an OpenAI-compatible endpoint.
# After it is up, point benchmark runners at it by editing llm_config.env:
#   api_base_url=http://<host>:<port>/v1
#   api_key=EMPTY
#   model=<served_model_name>
#
# Usage:
#   sft/scripts/serve_vllm.sh <model_path> [served_name] [port] [tp]
#
# Environment overrides:
#   MAX_NUM_SEQS             default unset, or 8 for Qwen3.5
#   MAX_BATCHED_TOKENS       default unset, or 2048 for Qwen3.5
#   CHAT_TEMPLATE            defaults to <model_path>/chat_template.jinja when present
#   GPU_MEMORY_UTILIZATION   default 0.85
#   QWEN35_LANGUAGE_ONLY     default 1 for Qwen3.5, unset for others
#   QWEN35_SPECULATIVE_CFG   default {"method":"mtp","num_speculative_tokens":3}
#   VLLM_EXTRA_ARGS          extra flags appended verbatim
# Example:
#   sft/scripts/serve_vllm.sh \
#       sft/results/qwen3.5-27b-merged \
#       qwen3.5-27b-sft 6002 4
set -euo pipefail

MODEL="${1:?model path required}"
SERVED_NAME="${2:-$(basename "${MODEL}")}"
PORT="${3:-8000}"
TP="${4:-1}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-}"
MAX_BATCHED_TOKENS="${MAX_BATCHED_TOKENS:-}"
CHAT_TEMPLATE="${CHAT_TEMPLATE:-}"
QWEN35_LANGUAGE_ONLY="${QWEN35_LANGUAGE_ONLY:-}"
QWEN35_SPECULATIVE_CFG="${QWEN35_SPECULATIVE_CFG:-}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

if ! command -v vllm >/dev/null 2>&1; then
    echo "vllm not found. Install with: pip install vllm" >&2
    exit 1
fi

LOWER_NAME="$(printf '%s\n%s' "${MODEL}" "${SERVED_NAME}" | tr '[:upper:]' '[:lower:]')"
COMMON_ARGS=(
    --served-model-name "${SERVED_NAME}"
    --host 0.0.0.0
    --port "${PORT}"
    --tensor-parallel-size "${TP}"
    --dtype bfloat16
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}"
)

MODEL_ARGS=()
if [[ -z "${CHAT_TEMPLATE}" ]] && [[ -f "${MODEL}/chat_template.jinja" ]]; then
    CHAT_TEMPLATE="${MODEL}/chat_template.jinja"
fi
if [[ -n "${CHAT_TEMPLATE}" ]]; then
    if [[ ! -f "${CHAT_TEMPLATE}" ]]; then
        echo "chat template not found: ${CHAT_TEMPLATE}" >&2
        exit 1
    fi
    MODEL_ARGS+=(--chat-template "${CHAT_TEMPLATE}")
fi

if [[ "${LOWER_NAME}" == *qwen3.5* ]] || [[ "${LOWER_NAME}" == *qwen3_5* ]]; then
    if [[ -z "${MAX_NUM_SEQS}" ]]; then
        MAX_NUM_SEQS=8
    fi
    if [[ -z "${MAX_BATCHED_TOKENS}" ]]; then
        MAX_BATCHED_TOKENS=2048
    fi
    if [[ -z "${QWEN35_LANGUAGE_ONLY}" ]]; then
        QWEN35_LANGUAGE_ONLY=1
    fi
    if [[ -z "${QWEN35_SPECULATIVE_CFG}" ]]; then
        QWEN35_SPECULATIVE_CFG='{"method":"mtp","num_speculative_tokens":3}'
    fi

    MODEL_ARGS+=(
        --max-num-seqs "${MAX_NUM_SEQS}"
        --max-num-batched-tokens "${MAX_BATCHED_TOKENS}"
        --reasoning-parser qwen3
        --default-chat-template-kwargs '{"enable_thinking": false}'
        --disable-custom-all-reduce
    )

    if [[ "${QWEN35_LANGUAGE_ONLY}" == "1" ]]; then
        MODEL_ARGS+=(--language-model-only)
    fi
    if [[ -n "${QWEN35_SPECULATIVE_CFG}" ]]; then
        MODEL_ARGS+=(--speculative-config "${QWEN35_SPECULATIVE_CFG}")
    fi
fi

if [[ -n "${VLLM_EXTRA_ARGS}" ]]; then
    # shellcheck disable=SC2206
    EXTRA_ARGS=( ${VLLM_EXTRA_ARGS} )
else
    EXTRA_ARGS=()
fi

exec vllm serve "${MODEL}" \
    "${COMMON_ARGS[@]}" \
    "${MODEL_ARGS[@]}" \
    "${EXTRA_ARGS[@]}"
