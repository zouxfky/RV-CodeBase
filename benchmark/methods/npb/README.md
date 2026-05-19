# NPB Benchmark Method

This method optimizes `benchmark/datasets/npb.jsonl` with the same three-round workflow used by the other benchmark methods:

1. `generate`: produce an RVV-oriented candidate.
2. `repair`: fix compile, runtime, or correctness failures.
3. `improve`: refine a correct candidate for better speedup.

Implementation notes:

* Each dataset row is compiled as a self-contained NPB benchmark unit with the required support files (`npb-C.h`, `npbparams.h`, benchmark header, timing helpers, and math helpers).
* Rows that have a separate `driver_code` keep that driver fixed; the model only rewrites the target block.
* The method strips `c_print_results(...)` from both baseline and optimized builds so runtime-dependent text does not break correctness comparison.
* Benchmark input files such as `inputbt.data` and `mg.input` are materialized from dataset fields when present.

Example:

```bash
python3 benchmark/methods/npb/run.py \
  --dataset benchmark/datasets/npb.jsonl \
  --output benchmark/results/npb/test10/results.jsonl \
  --remote-host root@172.19.101.70 \
  --ssh-password milkv \
  --remote-root /tmp/benchmark_npb \
  --max-rounds 3 \
  -n 10
```
