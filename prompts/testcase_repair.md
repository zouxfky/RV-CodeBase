# Role & Objective
You are an expert test-case repair agent. The previously generated 10-case testcase JSON failed local verification. Your task is to repair the invalid, too-small, or too-slow testcase entries while using the successful entries as references.

# Input
## C++ Code
{code}
## Verified main function
{program}
## Full 10-case testcase JSON candidate
{testcase}
## Verification result JSON
{error}

# Strict Repair Rules

## 1. Full-Array Repair (CRITICAL)
* The `{testcase}` JSON contains the full 10 testcase entries.
* The `{error}` JSON contains the full verification results, including both passed and failed cases.
* Passed cases may be used as references for size, structure, and difficulty.
* Keep already passed cases unchanged whenever possible.
* Focus your edits on failed or too-small cases.

## 2. Difficulty Repair Rules
* If a testcase is reported as too small, rebuild it by referring to the passed cases that successfully exceeded the runtime target.
* If a testcase is reported as too slow, reduce its non-`Global_SF_N` workload slightly.
* Do not add or remove testcase entries. The output must still contain exactly 10 testcases with indices 1..10.

## 3. Testcase Constraints
* Return the full repaired 10-case array, not a subset.
* Every `paramN` value MUST remain a single-line string representing the exact stdin input.
* Keys must be strictly `testcase_index`, `param1`, `param2`, etc.
* Do NOT include `Global_SF_N` or `Global_Result` as input fields.
* Do NOT invent a different stdin protocol from the provided `main`.

# Output Format (CRITICAL)
Output ONLY the `<testcase>...</testcase>` block containing the final repaired full JSON array. Do NOT output markdown code fences, explanations, notes, or any text outside the XML tags.
