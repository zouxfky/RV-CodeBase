# Role & Objective

You are given a previously verified C++ `main` test harness for the provided `solve(...)` algorithm.
Your task is to generate exactly 3 diverse test inputs for that verified `main`.

# Input
## C++ Code
{code}
## Verified main function
{program}

# Strict Output Requirements

## 1. Testcase Constraints

* **Quantity & Diversity:** Generate exactly 3 testcases (`testcase_index` 1 to 3). Make them structurally diverse, but keep all of them valid, meaningful, and suitable for later scaling.
* **Strict Adherence:** Follow the exact stdin protocol, parameter count, and order defined in the provided `main`.
* **Scale Awareness:** `Global_SF_N` is controlled externally and will be appended later by the runner. Generate only the non-`Global_SF_N` input parameters, but choose them so the program is still legal, stable, and meaningful when `Global_SF_N` becomes large. Do NOT include `Global_Result` as an input field.
* **Validity Over Extreme Boundaries:** Avoid empty, degenerate, or unsafe inputs unless the provided code clearly indicates they are valid and useful. Respect obvious implicit constraints from the code, such as matching dimensions, non-empty structures when indexing is used, safe string/array lengths, and dataset sizes that are compatible with folds, training loops, or other workload logic.

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
"param1": "[10,20,30,40]",
"param2": "[[1,1,1],[2,2,2],[3,3,3]]"
}
]
</testcase>
*(Note: Example truncated, your actual output must contain exactly 3 cases)*

# Output Format (CRITICAL)
Output ONLY the `<testcase>...</testcase>` block containing the final JSON array. Do NOT output markdown code fences, explanations, notes, or any text outside the XML tags.
