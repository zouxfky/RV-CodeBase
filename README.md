# 🌾 RV-CodeBase: A Dataset for LLM-based Code Optimization on RISC-V Extensions

RV-CodeBase is a dataset of hardware-verified code optimization pairs for RISC-V. Each baseline program is paired with a version rewritten to use RISC-V extensions and verified for correctness and speed on real hardware. The work has two parts:

1. **Dataset construction:** build 32,220 seed programs from 41,417 raw programs collected from 15 sources, reconstruct their workloads so that they can be timed reliably, and let an LLM optimize each program for a target extension with compilation, correctness and hardware-performance feedback. Successful and failed attempts are both kept.
2. **Fine-tuning:** fine-tune code LLMs on the pairs with positive speedups and evaluate them on four extension benchmarks.

## Construction Pipeline

| Stage | Directory | Steps |
|---|---|---|
| 1. Seed program construction | `seed/` | `1.1` embed task descriptions, `1.2` retrieve the top-10 similar programs and let an LLM judge duplicates, `1.3` merge duplicates, `1.4` classify each program into one of four categories |
| 2. Scalable workload reconstruction | `workload/` | `2.1` let an LLM expose the workload parameters through a scaling factor `Global_SF_N`, `2.2` compile and run checks, `2.3` repair invalid transformations, `2.4` generate the test harness and test cases and grow `Global_SF_N` until the runtime is long enough for stable timing |
| 3. Extension-guided optimization | `optimize/` | `3.1` generate / repair / improve optimized code with the guidance prompt of the program's target extension (`prompts/3-ext-*.md`), `3.2` build it with that extension's `-march`, check and time it on the board; `3-run.py` drives up to three refinement rounds and keeps the final code and validation result of every program, successful or not |

Stage 1 assigns each program a category and its target extension:

| Category | Typical computation | Extension | Programs |
|---|---|---|---|
| Numerical Computation | vector operations, statistics, numerical methods | RVV | 15,208 |
| Bit-level Computation | encoding, hashing, encryption | B | 4,736 |
| Control-intensive Computation | conditional filtering, thresholding, state updates | Zicond | 5,929 |
| Machine Learning | matrix multiplication, convolution | IME | 6,347 |

All stages read and write JSONL under `data/`. Stage 1 starts from `data/collected_seeds.jsonl` (one raw program per row with `pid`, `quertion`, `tags` and `solution`); `python download.py --subset pipeline` places the pipeline files under `data/`. Each stage resumes from the `stage` field of every row, so a script can be re-run after an interruption.

## Overview

![RV-CodeBase](fig/overview.png)

## Extensions and Benchmarks

| Extension | Benchmark | Tasks |
|---|---|---|
| RVV (vector) | TSVC | 135 loop kernels |
| B (Zba/Zbb/Zbc/Zbs) | Mbed TLS 3.6.2 | 27 (hashes, block/stream ciphers, MACs, DRBGs, DHM) |
| Zicond | TACLeBench | 26 (kernel, sequential and app programs) |
| IME (SpacemiT integer matrix) | CMSIS-NN int8 unit tests | 21 (convolutions, FC, matmul, LSTM, SVDF, pooling, softmax) |

All programs run on Milk-V Jupiter (SpacemiT M1, X60 cores, VLEN 256, gcc 14.2). 209 tasks; each benchmark is evaluated on its target extension. Models are compared before (Base) and after (SFT) fine-tuning by correctness rate (CR), positive speedup rate (PSR) and speedup (SR, geometric mean, failed tasks count as 1). Per-program classification: [benchmark/PROGRAMS.md](benchmark/PROGRAMS.md).

## Repository Layout

```text
seed/         stage 1: seed program construction (embedding, duplicate matching, dedupe, classification)
workload/     stage 2: scalable workload reconstruction (transform, verify, repair, harness / test cases, runtime scaling)
optimize/     stage 3: extension-guided optimization (generate / debug / improve); _remote.sh builds, checks and times on the board
prompts/      prompts for stages 1-3, prefixed by stage number
sft/          fine-tuning: configs/ (LoRA per model), scripts/ (build data, train, merge, serve)
benchmark/
  common/      shared code: I/O, LLM config, local job runner, extension table, metrics.py (CR/PSR/SR), runner.py, prompts/
  run.py       Mbed TLS / TACLeBench / CMSIS-NN runner (--suite, --mode, --method)
  table.py     main results table (CR / PSR / SR, Base vs SFT) from <suite>/results/
  tsvc/        RVV           run.py, summary.py, analyze.py, prompts/
  mbedtls/     B             build.py, src/ (vendored Mbed TLS, used only by build.py)
  tacle/       Zicond        build.py
  cmsisnn/     IME           build.py, src/ (vendored CMSIS-NN, int8 unit tests and test data; used only by build.py)
```

Every suite directory has the same layout, all JSONL:

```text
<suite>/dataset.jsonl                          original programs
<suite>/baseline/<method>/<ext>.jsonl          optimized code, one {id, extension, code} per program
<suite>/results/<method>/<ext>.jsonl           status, speedup, timings, extension-instruction counts
```

`<method>` is a model name (`<model>` for Base, `<model>-sft` for SFT) or `manual` (hand-optimized).

Each row's `code` is the one file the model rewrites; `files` holds the fixed harness and the rest of the program, so every row builds on its own with no vendored tree. Rows are kept small (comments stripped, unused #if branches and functions removed) so that they compile in seconds. Repetition counts (`*_REPEAT`) were chosen so that one run of the original takes about 300 ms on the board.

## Installation

A **host machine** runs the Python pipeline and calls the LLM. **RISC-V boards** compile, run and time the programs. The scripts call `optimize/_remote.sh` on the board, so run them from a copy of this repo on the board.

```bash
conda create -n rvcodebase python=3.11 -y
conda activate rvcodebase
pip install -r requirements.txt
```

Boards need GCC 14 or newer (for Zicond and the B extensions), and `objdump` for counting extension instructions.

## Download

```bash
python download.py --subset sft pipeline   # SFT pairs and pipeline data
python download.py --subset models         # fine-tuned models
```

The benchmark datasets ship with the repo (`benchmark/<suite>/dataset.jsonl`).

## LLM Configuration

All LLM calls use an OpenAI-compatible endpoint set in `llm_config.env` (see `llm_config.example.env`):

```text
api_base_url = http://<host>:<port>/v1
api_key      = <key or EMPTY>
model        = <model name>
temperature  = 0
```

## Fine-tuning

The models are fine-tuned with LoRA (rank 16) on four NVIDIA RTX Pro 6000 GPUs, using only the pairs with positive speedups. The training prompt is the same as the benchmark prompt (`benchmark/common/prompts/generate.md`), with the description of each pair's target extension filled in.

```bash
python sft/scripts/build_sft.py                      # data/{seed,optimized}.jsonl -> sft/data/pairs.jsonl
python sft/scripts/render_sft.py                     # pairs.jsonl -> sft/data/{train,eval}.jsonl
sft/scripts/train.sh sft/configs/qwen3.5-9b_lora.yaml --gpus 4
sft/scripts/merge_lora.sh Qwen/Qwen3.5-9B sft/results/qwen3.5-9b-lora sft/results/qwen3.5-9b-merged qwen3_5
sft/scripts/serve_vllm.sh sft/results/qwen3.5-9b-merged qwen3.5-9b-sft 8000 1
```

`sft/configs/` has one config per model: DeepSeek-Coder 7B/33B, CodeLlama 13B/34B and Qwen3.5 9B/27B train with Llama-Factory through `train.sh`; Gemma4 12B/31B train with `sft/scripts/train_gemma4.py` (text-only LoRA on the language model). All configs use an effective batch size of 16 on 4 GPUs.

## Running the Benchmarks

See [benchmark/README.md](benchmark/README.md) for the commands (LLM and manual baselines) and the result layout.
