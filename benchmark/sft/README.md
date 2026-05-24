# Instruction SFT for Code Optimization

The second downstream task in RV-CodeBase: turn the verified code optimization
pairs from the data construction pipeline into instruction-based SFT data, fine-tune
LLMs with LoRA, then evaluate the SFT model on the existing TSVC / PolyBench/C
/ RAJAPerf runners under `benchmark/methods/`.

## Layout

```text
benchmark/sft/
├── data/
│   └── build_sft.py             # out/{seed,rv2}.jsonl -> alpaca train/eval
├── configs/
│   ├── dataset_info.json        # Llama-Factory dataset registration
│   ├── qwen3.5-9b_lora.yaml
│   ├── qwen3.5-27b_lora.yaml
│   └── llama3.1-8b_lora.yaml
├── scripts/
│   ├── train.sh                 # llamafactory-cli train <yaml>
│   ├── merge_lora.sh            # merge adapter into base, export weights
│   └── serve_vllm.sh            # OpenAI-compatible vLLM serving
└── results/                     # checkpoints / merged weights (gitignored)

benchmark/datasets/sft/
├── train.jsonl
└── eval.jsonl
```

The instruction template reuses
`benchmark/common/prompts/generate.md`, so the training distribution matches
the prompt the evaluation runners send at inference time.

## 1. Build the SFT corpus

```bash
python3 benchmark/sft/data/build_sft.py \
    --eval-ratio 0.02 \
    --shuffle
```

Defaults read `out/seed.jsonl` (baseline source) and `out/rv2.jsonl`
(optimization result), then write
`benchmark/datasets/sft/{train,eval}.jsonl`.

Sample policy:

- **positive** (`status == success` and `speedup > 1`) → `output` is the
  optimized code.
- **negative** (anything else: compile / runtime / correctness fail or no
  speedup) → `output` is the unchanged baseline.

## 2. Train

```bash
benchmark/sft/scripts/train.sh benchmark/sft/configs/qwen3.5-9b_lora.yaml
```

The YAML registers the dataset via
`benchmark/sft/configs/dataset_info.json`. Adapter weights land under
`benchmark/sft/results/<run>/`.

## 3. Merge LoRA into the base model

```bash
benchmark/sft/scripts/merge_lora.sh \
    Qwen/Qwen2.5-Coder-7B-Instruct \
    benchmark/sft/results/qwen3.5-9b-lora \
    benchmark/sft/results/qwen3.5-9b-merged \
    qwen
```

## 4. Serve the SFT model

```bash
benchmark/sft/scripts/serve_vllm.sh \
    benchmark/sft/results/qwen3.5-9b-merged \
    qwen3.5-9b-sft 8000 1
```

Then point the repo-level `llm_config.env` at it:

```text
api_base_url=http://<host>:8000/v1
api_key=EMPTY
model=qwen3.5-9b-sft
temperature=0.0
```

## 5. Evaluate on the three external benchmarks

No new evaluation method is needed. Reuse the existing runners and write
results into a new model-named subdirectory:

```bash
python3 benchmark/methods/tsvc/run.py \
    --output benchmark/results/tsvc/qwen3.5-9b-sft/results.jsonl

python3 benchmark/methods/polybenchc/run.py \
    --output benchmark/results/polybenchc/qwen3.5-9b-sft/results.jsonl

python3 benchmark/methods/rajaperf/run.py \
    --output benchmark/results/rajaperf/qwen3.5-9b-sft/results.jsonl
```

Aggregate first-iteration and final metrics with:

```bash
python3 benchmark/eval/perf/summary.py \
    benchmark/results/tsvc/qwen3.5-9b-sft/results.jsonl
python3 benchmark/eval/perf/build_summary_table.py
```
