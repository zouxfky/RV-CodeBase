# TSVC Method

This method runs three-round RISC-V optimization on the TSVC kernel dataset.

Input:

- `benchmark/datasets/tsvc.jsonl`

Output:

- `benchmark/results/tsvc/<method>/results.jsonl`

Each sample is optimized in up to three rounds:

1. generate an RVV-based candidate
2. repair it if compile/runtime/correctness fails
3. improve it further if correctness passes but performance is still unsatisfactory

The method reuses the existing remote benchmark runner logic, but adapts the
TSVC dataset into a standalone build:

- `common.h`, `array_defs.h`, `common.c`, `dummy.c`, `globals.c` are written as
  fixed support files
- the sample kernel block (`prefix_code + code + suffix_code`) is compiled with
  the fixed driver from `driver_code`
- the driver is normalized to print only the checksum so remote correctness
  comparison is deterministic while wall-clock time is measured externally

Example:

```bash
python3 benchmark/methods/tsvc/run.py \
  --dataset benchmark/datasets/tsvc.jsonl \
  --output benchmark/results/tsvc/qwen3.5-9b/results.jsonl \
  --remote-host sg2044 \
  --max-rounds 3 \
  -n 10
```
