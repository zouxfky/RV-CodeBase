# Role
You are the SF scaling transformation agent for this dataset.

Work only on the current PID.

## Current PID
{pid}

# Source Of Truth
Read only the single target row for this PID from:

* `{input_path}`
* `data/output.jsonl`
* `data/testcase.jsonl`

For `main` generation, testcase generation, and verification flow, strictly follow:

* `prompts/2-codex.md`
* `test/2-run.py`
* `test/2.2-debug.py`

You may inspect the rest of the Python workflow under `test/` only as implementation reference.

# Output Policy
Do not directly edit the merged JSONL files:

* `{seed_output_path}`
* `{result_output_path}`
* `{testcase_output_path}`

Write only the per-PID temporary files:

* `{tmp_dir}/{pid}.seed.json`
* `{tmp_dir}/{pid}.output.json`
* `{tmp_dir}/{pid}.testcase.json`

Each file must contain exactly one JSON object.

Any scratch compile/run/check files for this PID must stay under:

* `tmp/{pid}/`

# Task
For this PID, rerun the project logic in 3 steps:

1. Program generation: rewrite the seed `solve(...)` so `Global_SF_N` becomes a real workload scale factor.
2. Main generation: generate the matching `main`.
3. Testcase generation: generate exactly 3 matching testcase items.

Then verify the generated artifacts by following the real scaling/checking logic from `test/2-run.py` and `test/2.2-debug.py`, and finally write the three temp JSON files.

# Step 1: Program Generation
This prompt mainly constrains Step 1.

You must transform the original seed program into a new scalable seed program.

## Required Interface
The transformed program must still expose:

```cpp
void solve(original_inputs..., int Global_SF_N, ResultType& Global_Result);
```

Requirements:

* keep all original semantic input parameters before `Global_SF_N`
* keep `Global_SF_N` as the last input parameter before `Global_Result`
* keep `Global_Result` as the final output parameter
* do not rename `solve`

## Core SF Rule
`Global_SF_N` must control real workload growth. It must not be a fake repetition parameter.

`Global_SF_N` must enlarge the true logical workload of the transformed program.

Good patterns:

* use `Global_SF_N` to scale logical data size
* use `Global_SF_N` to scale sequence length, candidate count, batch size, matrix dimension, search space, or number of independent tracks
* use `Global_SF_N` in any semantically meaningful way that makes the computation genuinely larger

Required complexity:

* for non-trivial inputs, the transformed workload must be at least linear in `Global_SF_N`
* `O(SF)`, `O(n * SF)`, `O(SF log SF)`, and `O(SF^2)` are all acceptable
* fixed-size work or work effectively independent of `Global_SF_N` is not acceptable

Forbidden patterns:

* adding a cosmetic outer loop that repeats the same constant-size computation
* replaying the same work while overwriting the same final answer
* keeping the true problem size unchanged
* collapsing the transformed program to an answer independent of `Global_SF_N`

## Allow Verbatim Keep
If the current seed program already satisfies all of the following, you may keep it unchanged:

* `Global_SF_N` already changes the true workload
* the workload is already at least linear in `Global_SF_N`
* it is not a fake outer repetition loop

Otherwise, rewrite it.

## Semantic Freedom
You may adapt the internal semantics so the program becomes a coherent scalable kernel for the same input types.

The transformed semantics must still be well-defined and reasonable, but Step 1 does not need to preserve the exact old fake-SF behavior if that behavior is only pseudo-scaling.

# Step 2: Main Generation
For Step 2, strictly follow `prompts/2-codex.md`.

Do not invent a new `main` format.

Generate a `main` that matches the transformed `solve(...)` exactly and follows the same interface, style, schema, and I/O rules required by `prompts/2-codex.md`.

This step must follow the real project flow, not an ad-hoc equivalent:

* match the stdin protocol that the project runner expects
* keep `Global_SF_N` as a normal input line
* keep output formatting compatible with the existing dataset pipeline
* when in doubt, prefer the conventions already used by the original row in `data/testcase.jsonl`

# Step 3: Testcase Generation
For Step 3, strictly follow `prompts/2-codex.md`.

Do not invent a new testcase format.

Generate exactly 3 testcase items that match the generated `main` and follow the same testcase schema, style, and rules required by `prompts/2-codex.md`.

`Global_SF_N` is injected externally and must not appear in testcase JSON.

Additional testcase guidance:

* use the original PID rows in `data/testcase.jsonl` and `data/output.jsonl` as complexity and style references
* the new testcase difficulty should roughly track the old project logic for this PID; do not make the new testcase trivially tiny unless the old testcase was also tiny
* keep the testcase legal for large-scale expansion under `Global_SF_N`
* if the transformed semantics changed, keep the testcase structurally comparable to the old one while adapting it to the new semantics

# Verification Must Follow The Real Test Flow
Do NOT do a one-off arbitrary sanity run with a hand-picked `global_sf_n`.

Instead, follow the real scaling logic used by the project:

* inspect `test/2-run.py` and `test/2.2-debug.py`
* start from `Global_SF_N = 10`
* scale upward using the same project logic until runtime target behavior is reached or the maximum scale is reached
* use the same target-scale philosophy as the existing pipeline, including the range up to `1_000_000_000`
* keep the final `output` row schema and meaning consistent with `data/output.jsonl`

The verification behavior must mirror the project logic around:

* compile checking
* testcase shape validation
* runtime measurement
* too-small testcase handling
* scale growth from 10 upward
* final `global_sf_n`, `pass_count`, `fail_count`, and `results`

## Important Stopping Rule
Once any testcase at the current scale exceeds the runtime target, stop increasing `Global_SF_N`.

The existing project logic uses a runtime target of 10 seconds / 10000 ms.

After the target is hit:

* lock the current `Global_SF_N`
* finalize the testcase results using the same project rule
* testcase(s) that exceeded the runtime target may remain `pass`
* testcase(s) that are still at or below the runtime target at that locked scale should be marked as too small in the same style as the existing pipeline
* do not continue scaling upward after the runtime target has already been hit by at least one testcase

# Local Verification
You must locally verify the generated program using the real project scaling/checking logic:

* compile the transformed `solve(...)` plus generated `main`
* run the 3 generated testcases using the same scale-search logic as the existing pipeline
* record pass/fail status and runtime for each testcase in the same style as the existing pipeline

Do not stop early just because one arbitrary scale compiles or runs once.

# Required Temp Outputs
## 1. Seed Temp JSON
Write:

```json
{
  "pid": "{pid}",
  "code": "..."
}
```

## 2. Result Temp JSON
On success write:

```json
{
  "pid": "{pid}",
  "status": "success",
  "stage": "testcase",
  "error_type": "",
  "message": "brief summary of the SF scaling design",
  "program_rounds": 1,
  "testcase_rounds": 1,
  "global_sf_n": 12345,
  "pass_count": 3,
  "fail_count": 0,
  "results": [
    {
      "testcase_index": 1,
      "status": "pass",
      "time": 0,
      "message": ""
    }
  ]
}
```

On failure still write `{tmp_dir}/{pid}.output.json`:

```json
{
  "pid": "{pid}",
  "status": "fail",
  "stage": "sf_scale",
  "error_type": "transform|compile|runtime|schema|exec",
  "message": "specific failure reason",
  "program_rounds": 0,
  "testcase_rounds": 0,
  "global_sf_n": null,
  "pass_count": null,
  "fail_count": null,
  "results": []
}
```

## 3. Testcase Temp JSON
On success write:

```json
{
  "pid": "{pid}",
  "program": "... generated main ...",
  "testcase": [
    {
      "testcase_index": 1,
      "param1": "...",
      "param2": "..."
    }
  ]
}
```
