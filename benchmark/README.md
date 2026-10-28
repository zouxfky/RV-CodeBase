# Benchmarks

| Suite | Target extension | Tasks |
|---|---|---|
| `tsvc/` | RVV | 135 |
| `mbedtls/` | B | 27 |
| `tacle/` | Zicond | 26 |
| `cmsisnn/` | IME | 21 |
| **Total** | | **209** |

Each suite is evaluated on its target extension and each program is one task; the lists are in `classes.json`.

All timing runs on Milk-V Jupiter (SpacemiT M1, X60 cores, VLEN 256, gcc 14.2); `--platform` defaults to `milkv`.

Per-program classification: [PROGRAMS.md](PROGRAMS.md).

## Layout

```text
<suite>/dataset.jsonl                          programs (ready to run)
<suite>/baseline/<method>/<ext>.jsonl          optimized code   {id, extension, code}
<suite>/results/<method>/<ext>.jsonl           status, speedup, timings, extension-instruction counts
```

`<method>` is a model name (`<model>` for Base, `<model>-sft` for SFT) or `manual`. Every run resumes from a work file under `tmp/` and, when it finishes, merges into `baseline/` and `results/`.

## Running

Run on the board, from a copy of the repo. The original and the optimized code are both compiled with `-O3` and the extension `-march`; each is run once to warm up and then timed five times. `benchmark/run.py` evaluates the programs listed for the suite in `classes.json`. `--run-j` is the number of programs compiled and timed at once; `--llm-j` the number of concurrent LLM requests. Set the model in `llm_config.env`.

**LLM** (the model rewrites `code`; timed against the original compiled with extension flags):

```bash
python3 benchmark/tsvc/run.py --method <model> --llm-j 8
python3 benchmark/run.py --suite mbedtls --mode llm --method <model> --llm-j 8   # B
python3 benchmark/run.py --suite tacle   --mode llm --method <model> --llm-j 8   # Zicond
python3 benchmark/run.py --suite cmsisnn --mode llm --method <model> --llm-j 8   # IME
```

**Manual** (times the code in `<suite>/baseline/manual/<ext>.jsonl`; programs without an entry are skipped):

```bash
python3 benchmark/run.py --suite tacle --mode manual
```

Use `-n <k>` to try the first k programs only.

Use `--method <model>` for the base model and `--method <model>-sft` for the fine-tuned one.

## Metrics

Computed over all tasks of a benchmark (`common/metrics.py`):

- **CR** (correctness rate): share of tasks whose generated program compiles and passes the functional tests.
- **PSR** (positive speedup rate): share of tasks that are correct and faster than the original program.
- **SR** (speedup): geometric mean of original/generated execution time; tasks that fail compilation or the functional tests count as 1.

```bash
python3 benchmark/tsvc/summary.py --input benchmark/tsvc/results/<model>/rvv.jsonl   # one results file
python3 benchmark/table.py > benchmark/table.md                                         # Base vs SFT, eight models
python3 benchmark/table.py --format latex
```

## Rebuilding a dataset

Not needed for running: every row carries all of its files. build.py amalgamates each program from `<suite>/src` and shrinks it with `common/compact.py` (comments stripped, `#if` blocks resolved with the `unifdef` tool, unused static functions removed); Mbed TLS rows are built with only the modules they need, programs above the size cap (TACLe 2800 lines, Mbed TLS 6000) are left out, and only programs listed in `classes.json` are written. `repeat.json` holds the repetition counts that make one run of the original take about 300 ms; `common/calibrate.py` measures them on a board (`--jobs N` calibrates N programs at once; keep 1 on the Jupiter boards).

```bash
python3 -I benchmark/mbedtls/build.py
python3 -I benchmark/tacle/build.py   --tacle <tacle-bench checkout>
python3 -I benchmark/cmsisnn/build.py --cmsis <CMSIS-NN checkout>
python3 benchmark/common/calibrate.py --suite tacle --output benchmark/tacle/repeat.json
```
