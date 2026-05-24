#!/usr/bin/env bash
# Serve a merged SFT model with vLLM as an OpenAI-compatible endpoint.
# After it is up, point benchmark runners at it by editing llm_config.env:
#   api_base_url=http://<host>:<port>/v1
#   api_key=EMPTY
#   model=<served_model_name>
#
# Usage:
#   benchmark/sft/scripts/serve_vllm.sh <model_path> [served_name] [port] [tp]
# Example:
#   benchmark/sft/scripts/serve_vllm.sh \
#       benchmark/sft/results/qwen3.5-9b-merged \
#       qwen3.5-9b-sft 8000 1
set -euo pipefail

MODEL="${1:?model path required}"
SERVED_NAME="${2:-$(basename "${MODEL}")}"
PORT="${3:-8000}"
TP="${4:-1}"

if ! command -v vllm >/dev/null 2>&1; then
    echo "vllm not found. Install with: pip install vllm" >&2
    exit 1
fi

exec vllm serve "${MODEL}" \
    --served-model-name "${SERVED_NAME}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --tensor-parallel-size "${TP}" \
    --dtype bfloat16 \
    --max-model-len 8192
