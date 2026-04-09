# Role & Objective
You are continuing a previous multi-turn conversation about generating a C++ test `main` function for the provided `solve(...)` algorithm.

Your previous answer already produced a candidate `main` function, but it did not pass local program verification. Repair that existing `main` function so that, after the user concatenates it with the provided C++ code, the combined code can compile and run correctly.

# Input

## C++ Code
{code}

## Current main function candidate
{program}

## Verification message
{error}

# Repair Requirements
* Keep the same rules and conventions as the previous generation step unless the verification message forces a change.
* You are repairing the existing `main`, not writing a brand-new unrelated solution.
* Preserve already-correct parts when possible.
* Fix the issue indicated by the verification message first.

## Repeat The Important Rules
* Output exactly one `main` function definition.
* Do NOT redefine `solve(...)`.
* Do NOT add extra top-level declarations.
* Keep the stdin protocol consistent with the previous rules:
  * one input parameter per line,
  * exact parameter order,
  * `Global_SF_N` treated as a normal input parameter,
  * `Global_Result` created inside `main`, not read from stdin.
* Keep the final output as exactly one deterministic string line ending with a newline.
* If the verification message conflicts with your previous assumptions, trust the verification message and revise the `main` accordingly.

# Output Format
* You MUST output ONLY one `<program>...</program>` block.
* The block must contain exactly one repaired `main` function definition.
* Do NOT output explanations, analysis, greetings, markdown fences, notes, or any text outside the `<program>...</program>` block.
