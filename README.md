# 🌾 RV-CodeBase: A Dataset for LLM-based Code Optimization on RISC-V Extensions

RV-CodeBase is a dataset of 32,220 program optimization tasks for RISC-V ISA extensions, covering RVV, B, Zicond, and IME. It is designed to improve the ability of large language models (LLMs) to generate correct and efficient programs for RISC-V hardware-software co-optimization.

This repository provides the complete construction pipeline, the fine-tuning recipes, and the evaluation benchmarks:

- **Dataset construction.** Programs are collected from 15 sources, deduplicated, and reconstructed with scalable workloads. LLMs then iteratively optimize each program for its target extension, and every result is validated through correctness tests and performance measurements on real RISC-V hardware.
- **Fine-tuning and evaluation.** Eight code LLMs are fine-tuned on the samples with positive speedups and evaluated on four independent external benchmarks, achieving gains of up to 28.8 percentage points in overall correctness and 37.8% in overall speedup.

![RV-CodeBase](fig/overview.png)

## Construction Pipeline

| Stage | Directory | What it does |
|---|---|---|
| 1. Seed program construction | `seed/` | embed, match duplicates with an LLM, dedupe, classify into four categories |
| 2. Scalable workload reconstruction | `workload/` | expose the workload through a scaling factor `Global_SF_N`, verify and repair, generate test cases, scale the runtime |
| 3. Extension-guided optimization | `optimize/` | generate / repair / improve code for the target extension, build, check and time it on the board (up to three rounds) |

| Category | Extension | Programs |
|---|---|---|
| Numerical Computation | RVV | 15,208 |
| Bit-level Computation | B | 4,736 |
| Control-intensive Computation | Zicond | 5,929 |
| Machine Learning | IME | 6,347 |

All stages read and write JSONL under `data/` and resume from the `stage` field of each row. Prompts are in `prompts/`, prefixed by stage number.

## Installation

```bash
conda create -n rvcodebase python=3.11 -y && conda activate rvcodebase
pip install -r requirements.txt
python download.py --subset sft pipeline   # SFT pairs and pipeline data
python download.py --subset models         # fine-tuned models
```

A host runs the pipeline and calls the LLM; programs are compiled and timed on a RISC-V board (GCC 14+, `objdump`) through `optimize/_remote.sh`. The LLM endpoint is set in `llm_config.env` (see `llm_config.example.env`; any OpenAI-compatible API).

## Fine-tuning

LoRA on the pairs with positive speedups, 4× RTX Pro 6000, one config per model in `sft/configs/`.

```bash
python sft/scripts/build_sft.py      # data/{seed,optimized}.jsonl -> sft/data/pairs.jsonl
python sft/scripts/render_sft.py     # -> sft/data/{train,eval}.jsonl
sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml --gpus 4
sft/scripts/merge_lora.sh Qwen/Qwen3.5-9B sft/results/qwen3.5-9b-lora sft/results/qwen3.5-9b-merged qwen3_5
sft/scripts/serve_vllm.sh sft/results/qwen3.5-9b-merged qwen3.5-9b-sft 8000 1
```

Gemma4 models train with `sft/scripts/train_gemma4.py` instead of `train.sh`.

## Benchmarks

| Suite | Extension | Tasks |
|---|---|---|
| TSVC | RVV | 135 |
| Mbed TLS | B | 27 |
| TACLeBench | Zicond | 26 |
| CMSIS-NN | IME | 21 |

All suites share one entry point and one set of prompts (`benchmark/common/prompts/`). Programs run on Milk-V Jupiter at `-O3` (one warm-up, five runs, median).

```bash
python3 benchmark/run.py --suite tsvc|mbedtls|tacle|cmsisnn --method <model>|<model>-sft --llm-j 8
python3 benchmark/table.py > benchmark/results.md
```

Each suite has `dataset.jsonl`, and a run writes `baseline/<method>/<ext>.jsonl` (code) and `results/<method>/<ext>.jsonl` (status, speedup). Metrics are CR (correctness rate), PSR (positive speedup rate) and SR (geometric-mean speedup, failures count as 1). Results from the paper: [benchmark/results.md](benchmark/results.md).
