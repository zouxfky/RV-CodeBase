#!/usr/bin/env bash
# Merge a LoRA adapter into its base model and export full weights.
#
# Usage:
#   benchmark/sft/scripts/merge_lora.sh <base_model> <adapter_dir> <export_dir> [template]
# Example:
#   benchmark/sft/scripts/merge_lora.sh \
#       Qwen/Qwen2.5-Coder-7B-Instruct \
#       benchmark/sft/results/qwen3.5-9b-lora \
#       benchmark/sft/results/qwen3.5-9b-merged \
#       qwen
set -euo pipefail

BASE="${1:?base model path or HF id required}"
ADAPTER="${2:?adapter dir required}"
EXPORT_DIR="${3:?export dir required}"
TEMPLATE="${4:-qwen}"

if ! command -v llamafactory-cli >/dev/null 2>&1; then
    echo "llamafactory-cli not found. Install with: pip install llamafactory" >&2
    exit 1
fi

TMP_CFG="$(mktemp -t merge_lora.XXXXXX.yaml)"
trap 'rm -f "${TMP_CFG}"' EXIT

cat >"${TMP_CFG}" <<EOF
model_name_or_path: ${BASE}
adapter_name_or_path: ${ADAPTER}
template: ${TEMPLATE}
finetuning_type: lora
trust_remote_code: true
export_dir: ${EXPORT_DIR}
export_size: 4
export_legacy_format: false
EOF

llamafactory-cli export "${TMP_CFG}"
echo "merged model exported to: ${EXPORT_DIR}"
