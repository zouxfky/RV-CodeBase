# Role & Objective


# Input 
Work only on the current PID.

## Current PID
{pid}

Focus on these sources of truth:

* `data/seed.jsonl`
* `test/` directory Python scripts
* `prompts/1-transform.md`
* `prompts/2-program-generate.md`
* `prompts/2-testcase-generate.md`

# Task

For this PID, follow the real project flow:

1. Start from the current transformed program in `data/seed.jsonl`
2. Check whether that stored SF-transformed program is actually valid
3. If the seed program is wrong, repair it first
4. Then generate the corresponding `main`
5. Then generate the corresponding `testcase`

The overall logic must follow the Python workflow implemented under `test/`.

In particular:

* do not invent a new pipeline，do not invent a new schema，do not skip the SF step
* do not generate `main` or `testcase` using assumptions that conflict with the Python scripts

## 1. SF Program Repair

You must inspect the current seed program for this PID and decide whether it already satisfies the project SF requirements. If not, repair it first.

The repaired program must follow:

* `prompts/1-transform.md`

In particular:

* the code must expose a valid `solve(...)`
* `Global_SF_N` must be integrated semantically
* `Global_Result` must be the final output parameter
* the transformed code must remain compilable and faithful to the original problem

## 2. Main Generation

After the SF program is valid, generate the `main` for this PID.

The `main` must follow:

* `prompts/2-program-generate.md`

It must also match the actual project flow defined by the Python scripts under `test/`.

In particular:

* stdin parsing must match the repaired `solve(...)` signature exactly
* `Global_SF_N` must be treated as a normal input parameter in `main`
* output formatting must be deterministic and compatible with the existing pipeline
* do not invent a different interface format

## 3. Testcase Generation

After the SF program and `main` are valid, generate the testcase row for this PID.

The testcase must follow:

* `prompts/2-testcase-generate.md`

It must also match the Python logic under `test/`.

In particular:

* testcase structure must match the generated `main`
* all `paramN` values must be single-line strings
* testcase SF behavior must stay consistent with the SF rules used by the Python pipeline
* testcase generation must stay compatible with the verifier assumptions in the project

## 4. Follow Test Pipeline, Not Ad-Hoc Logic

The implementation must follow the real `test/` Python flow for this project.

That means:

* use the `test/` scripts as the process reference
* keep the order `SF -> main -> testcase`
* keep SF-related testcase behavior consistent with the Python definitions
* keep the generated program and testcase consistent with:
  * `prompts/1-transform.md`
  * `prompts/2-program-generate.md`
  * `prompts/2-testcase-generate.md`

## 5. Output File Rule

Do not directly modify:

* `data/seed.jsonl`
* `data/output.jsonl`
* `data/testcase.jsonl`

Instead, write the result for this PID only into:

* `tmp/codex_exec/{pid}.seed.json`
* `tmp/codex_exec/{pid}.output.json`
* `tmp/codex_exec/{pid}.testcase.json`

Requirements:

* each file must contain exactly one JSON object
* only write the target PID
* do not rewrite unrelated PID entries
* write the repaired seed row to `tmp/codex_exec/{pid}.seed.json`
* write the generated main/result row to `tmp/codex_exec/{pid}.output.json`
* write the generated testcase row to `tmp/codex_exec/{pid}.testcase.json`
* if this PID fails, the testcase temporary file may be omitted, but `tmp/codex_exec/{pid}.output.json` must still be written

## 6. Verification Workspace Rule

During local verification, any temporary source files, binaries, logs, testcase inputs, or other scratch artifacts for this PID must be written only under:

* `tmp/{pid}/`

Requirements:

* do not scatter verification files elsewhere in the repository
* keep the three JSON output files in `tmp/codex_exec/` exactly as specified above; do not move or rename them
* all verification-only files created under `tmp/{pid}/` must be deleted before finishing
* after cleanup, `tmp/{pid}/` itself should be removed if it is empty
