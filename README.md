# 🌾 RV-CodeBase: A Comprehensive Dataset for LLM-based Code Optimization on RISC-V

RV-CodeBase is, to the best of our knowledge, the first systematic dataset for code optimization on RISC-V. It addresses the gap between functional correctness and hardware-specific optimization in existing code corpora, and provides resources for LLMs to acquire RISC-V-specific capabilities. RV-CodeBase consists of two core components:

1. An **RVV instruction knowledge base** with fine-grained specifications, intrinsic mappings, and usage examples for the RISC-V vector extension (RVV).
2. A collection of **code optimization pairs**, where each baseline program is paired with a RISC-V-optimized version produced under the guidance of the RVV knowledge base and verified on hardware.

Built on top of these, RV-CodeBase also defines two downstream benchmark tasks: (1) RAG-based RVV instruction question answering, and (2) supervised fine-tuning for optimization-oriented code generation.

- 🤗 HF Dataset: [RV-CodeBase/dataset](https://huggingface.co/datasets/RV-CodeBase/dataset)
- 🤗 HF Models:
  [qwen3.5-9b-sft](https://huggingface.co/RV-CodeBase/qwen3.5-9b-sft),
  [qwen3.5-27b-sft](https://huggingface.co/RV-CodeBase/qwen3.5-27b-sft),
  [llama3.1-8b-sft](https://huggingface.co/RV-CodeBase/llama3.1-8b-sft)

## Overview

![RV-CodeBase](fig/overview.png)

## Features

- **First-of-its-kind RISC-V optimization dataset:** focuses on hardware-specific optimization rather than only functional correctness, targeting the open-source RISC-V ISA and its modular extensions (RVV in particular).
- **RVV instruction knowledge base:** structured from official RISC-V specifications into entries that capture functional semantics, instruction formats, intrinsic interfaces, and usage examples.
- **Optimization pair collection:** seed programs are gathered from multiple sources (benchmarks, open-source datasets, and projects), scaled with adjustable workload factors, and rewritten by LLMs guided by the RVV knowledge base.
- **Hardware-verified pipeline:** specification modeling, program collection and scaling, LLM-based optimization, and hardware verification are integrated into a single data generation pipeline.
- **Two downstream benchmarks:** RAG over the RVV knowledge base for instruction QA, and SFT data construction for code optimization, both with reproducible evaluation scaffolding.

## Installation

RV-CodeBase uses a two-machine setup: a **host machine** runs the Python pipeline (data collection, LLM-based optimization, prompt orchestration), and a **RISC-V machine with RVV support** runs the build and verification of the generated programs.

**1. Host machine: Python environment**

```bash
conda create -n rvcodebase python=3.11 -y
conda activate rvcodebase
pip install -r requirements.txt
```

**2. RISC-V machine: build and verification**

Prepare a RISC-V machine with RVV support and a working C/C++ toolchain. The build and verification scripts default to `g++`.

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y g++

# CentOS / Rocky / AlmaLinux
sudo yum install -y gcc-c++
```

After the host machine produces the dataset artifacts, sync them to the RISC-V machine and run the build and verification scripts there to compile and execute each generated program, collecting correctness and performance results.

## Download

Download RV-CodeBase artifacts from Hugging Face:

```bash
python download.py
```

## Generate RV-CodeBase

The dataset construction pipeline runs stage by stage, with each stage producing JSONL artifacts under `data/` for inspection and reuse. Each stage script is runnable on its own, so the pipeline can be executed end to end or replayed from any intermediate JSONL.

## Benchmark Tasks

Both tasks call an OpenAI-compatible chat endpoint configured in the repo-level `llm_config.env`:

```text
api_base_url = http://<host>:<port>/v1
api_key      = <key or EMPTY>
model        = <model name>
temperature  = 0
```

### RAG-based RVV Instruction QA

Run any of the three QA settings against `benchmark/datasets/questions.jsonl`. Each runner writes `predictions.jsonl` under `benchmark/results/qa/<method>/`:

```bash
# No-RAG: model-only baseline
python3 benchmark/methods/qa/no_rag/run.py     --method <method> --jobs 8

# TextRAG: embedding retrieval over the RVV knowledge base
python3 benchmark/methods/qa/text_rag/run.py   --method <method> --jobs 8 --top-k 3

# GraphRAG: knowledge graph retrieval over the RVV knowledge base
python3 benchmark/methods/qa/graph_rag/run.py  --method <method> --jobs 8 --top-k 5
```

Score predictions and aggregate:

```bash
python3 benchmark/eval/qa/eval_qa.py       --method <method>   # writes metrics.jsonl
python3 benchmark/eval/qa/aggregate_qa.py  --method <method>   # writes summary.json
```

### Code Optimization on TSVC, PolyBench/C, RAJAPerf

Run a model on each benchmark; results land at `benchmark/results/<bench>/<model>/results.jsonl`:

```bash
python3 benchmark/methods/tsvc/run.py        --output benchmark/results/tsvc/<model>/results.jsonl
python3 benchmark/methods/polybenchc/run.py  --output benchmark/results/polybenchc/<model>/results.jsonl
python3 benchmark/methods/rajaperf/run.py    --output benchmark/results/rajaperf/<model>/results.jsonl
```

Score per-run and build the cross-model summary table:

```bash
python3 benchmark/eval/perf/summary.py             --input benchmark/results/<bench>/<model>/results.jsonl
python3 benchmark/eval/perf/build_summary_table.py     # writes benchmark/results/summary_table.xlsx
```
