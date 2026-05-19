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

* Output optional minimal standard-library `#include <...>` directives followed by exactly one repaired `main` function definition. Do NOT redefine `solve(...)` or add any other top-level declarations.
* Prefer the existing include and namespace environment when possible. Add only truly necessary standard-library headers, avoid clearly redundant duplicate headers already present in the provided code, prefer the existing namespace environment or explicit `std::` qualifiers, and do NOT use `extern "C"` header-avoidance hacks inside `main`.
* Keep the stdin/stdout protocol unchanged: one input parameter per line, exact parameter order, `Global_SF_N` treated as a normal input parameter, `Global_Result` created inside `main` rather than read from stdin, and the final output printed as exactly one deterministic line ending with a newline.
* If the verification message conflicts with your previous assumptions, trust the verification message, preserve already-correct parts when possible, and revise only what is needed to make the concatenated code compile and run correctly.

# Output Format

* You MUST output ONLY one `<program>...</program>` block.
* The block must contain optional minimal standard-library `#include <...>` lines followed by exactly one repaired `main` function definition.
* Do NOT output explanations, analysis, greetings, markdown fences, notes, or any text outside the `<program>...</program>` block.
