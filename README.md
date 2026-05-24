# 🌾 RV-CodeBase: A Comprehensive Dataset for LLM-based Code Optimization on RISC-V

RV-CodeBase is, to the best of our knowledge, the first systematic dataset for code optimization on RISC-V. It addresses the gap between functional correctness and hardware-specific optimization in existing code corpora, and provides resources for LLMs to acquire RISC-V-specific capabilities. RV-CodeBase consists of two core components:

1. An **RVV instruction knowledge base** with fine-grained specifications, intrinsic mappings, and usage examples for the RISC-V vector extension (RVV).
2. A collection of **code optimization pairs**, where each baseline program is paired with a RISC-V-optimized version produced under the guidance of the RVV knowledge base and verified on hardware.

Built on top of these, RV-CodeBase also defines two downstream benchmark tasks: (1) RAG-based RVV instruction question answering, and (2) supervised fine-tuning for optimization-oriented code generation.

- 🤗 HF Datasets: [ ]( )

## Overview

![RV-CodeBase]( )

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

## Generate RV-CodeBase

The dataset construction pipeline is organized stage by stage, with each stage producing JSONL artifacts under `data/` for inspection and reuse:

```text
materials/   # RVV knowledge base sources and reference materials
seed/        # 1.x  embedding / matching / dedup / classification / transform / verify / repair
test/        # 2.x  test case generation and debugging
optimize/    # 3.x  RVV-oriented optimization: generation / improvement / repair / review
prompts/     # LLM prompts used at each stage
source/      # Raw code sources (PolyBenchC / RAJAPerf / TSVC / NPB / HeCBench / GitHub / OJ ...)
data/        # Intermediate and final artifacts (jsonl)
benchmark/   # Downstream benchmarks: RVV QA (RAG) and code optimization
```

Each stage script is runnable on its own, so the pipeline can be executed end to end or replayed from any intermediate JSONL.

## Downstream Tasks

**RAG-based RVV Instruction QA.** Use the RVV knowledge base as a retrieval source over multiple RAG configurations (No-RAG / TextRAG / GraphRAG) and evaluate answer quality on RVV instruction questions. Scaffolding lives under `benchmark/methods/qa/` and `benchmark/eval/qa/`.

**Instruction SFT for Code Optimization.** Convert the verified code optimization pairs into instruction-based SFT data, fine-tune LLMs with LoRA, and evaluate the resulting model on TSVC, PolyBench/C, and RAJAPerf. The SFT pipeline lives under `benchmark/sft/`; see `benchmark/sft/README.md` for the full flow.

## TODO

- [ ] One-line command to generate RV-CodeBase end to end
- [ ] Dockerized build and verification environment
- [ ] Expanded benchmark reports and leaderboard

## License

Please follow the original licenses of the upstream data sources. Code in this repository is released under the LICENSE file shipped with the repo.
