# Role & Objective
You are given a previously verified C++ `main` test harness for the provided `solve(...)` algorithm.

Your task is to generate exactly 10 diverse test inputs for that verified `main`.

# Input
## C++ Code
{code}
## Verified main function
{program}

# Strict Output Requirements

## 1. Testcase Constraints
* **Quantity & Diversity:** Generate exactly 10 testcases (`testcase_index` 1 to 10). Include small, normal, boundary, and structurally diverse cases.
* **Strict Adherence:** Follow the exact stdin protocol, parameter count, and order defined in the provided `main`.
* **Do NOT generate `Global_SF_N`:** `Global_SF_N` is a scale factor controlled externally and will be appended later by the runner. Generate only the non-`Global_SF_N` input parameters. Do NOT include `Global_Result` as an input field.

## 2. JSON Schema & String Encoding
Output a single JSON array of objects. Each object represents one testcase and maps directly to the stdin lines expected by the `main` function.

{
"testcase_index": 1,
"param1": "[1,2,3]",
"param2": "[[4,5],[6,7]]",
"param3": "1"
}

* **Sequential Keys:** Keys must be strictly `testcase_index`, `param1`, `param2`, `param3`, etc., without gaps.
* **Stringified Values (Critical):** Every `paramN` value MUST be a single-line string exactly as it will be fed to stdin:
* Scalars: `"123"`, `"true"`, `"3.14"`
* Strings: Raw string value
* Containers (Vector/Matrix): JSON-like strings (e.g., `"[1,2,3]"`, `"[[1,2],[3,4]]"`)
* **Rule:** Do NOT use actual JSON arrays/numbers for `paramN`. They MUST be strings. Do NOT include embedded newlines in any parameter string.
* **Important:** Because `Global_SF_N` is injected separately, the final `paramN` in your JSON must be the last non-`Global_SF_N` input parameter from the verified `main`.

# Example Reference
### Verified main context
```cpp
// param1: vector<int>, example: [1,2,3]
// param2: vector<vector<int>>, example: [[1,2,3],[4,5,6]]
// Global_SF_N is injected externally and must NOT appear in testcase JSON
```

### Expected Output Block
<testcase>
[
{
"testcase_index": 1,
"param1": "[1,2,3]",
"param2": "[[4,5,6],[7,8,9]]"
},
{
"testcase_index": 2,
"param1": "[]",
"param2": "[]"
}
]
</testcase>
*(Note: Example truncated, your actual output must contain exactly 10 cases)*

# Output Format (CRITICAL)
Output ONLY the `<testcase>...</testcase>` block containing the final JSON array. Do NOT output markdown code fences, explanations, notes, or any text outside the XML tags.
