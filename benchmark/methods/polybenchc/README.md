# PolyBench/C Method

This method runs three-round RISC-V optimization on the PolyBench/C dataset.

Input:

- `benchmark/datasets/polybenchc.jsonl`

Output:

- `benchmark/results/polybenchc/<method>/results.jsonl`

Each sample is optimized in up to three rounds:

1. generate an RVV-based candidate
2. repair it if compile/runtime/correctness fails
3. improve it further if correctness passes but performance is still unsatisfactory

The method adapts each PolyBench/C sample into a standalone remote build:

- `polybench.h`, `polybench.c`, `papi_counters.list`, and the benchmark-specific
  header are written as fixed support files
- the sample block (`prefix_code + code + suffix_code`) is compiled as one C
  translation unit
- `polybench_print_instruments` is removed from the fixed `main` so baseline and
  optimized binaries produce deterministic comparable output while wall-clock
  time is measured externally

Example:

```bash
python3 benchmark/methods/polybenchc/run.py \
  --dataset benchmark/datasets/polybenchc.jsonl \
  --output benchmark/results/polybenchc/qwen3.5-9b/results.jsonl \
  --remote-host root@172.19.101.70 \
  --ssh-password milkv \
  --max-rounds 3 \
  -n 10
```
