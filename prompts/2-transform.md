# Role & Objective
You are an expert code transformation agent. Your task is to refactor a provided source program into a pure, deterministic, and reusable callable unit.

# Task Requirements
You must extract the core algorithmic behavior of the input program and expose it through a single, standardized public entry function, stripping away all execution scaffolding.

## Input Code

The source program to transform is:

{code}

## 1. Interface Specifications (Strict)
The transformed code MUST expose exactly one public external entry function. The required interface template is:

`void solve(original_input_1, original_input_2, ..., int Global_SF_N, ResultType& Global_Result);`

* **`solve`:** The public external entry function name MUST be exactly `solve`. Do not rename it. Do not use any other public entry name. All original semantic inputs of the program MUST appear as explicit parameters in `solve(...)`, and they MUST all be placed before `Global_SF_N`.
* **`Global_SF_N`:** The parameter name MUST be exactly `Global_SF_N`. The spelling must not change. It MUST appear in `solve(...)` after all original input parameters.
* **`Global_Result`:** The output parameter name MUST be exactly `Global_Result`. The spelling must not change. It MUST appear as the final parameter of `solve(...)`. Its type MUST match the true semantics of the final verifiable output, such as `int`, `long long`, `double`, `std::vector<int>`, `std::vector<double>`, `std::vector<std::vector<double>>`, or another semantically correct result container.

## 2. Semantic Scaling Guidelines (`Global_SF_N`)
`Global_SF_N` must scale the real computational workload of the specific program according to that program's actual semantics. You MUST first understand what truly determines the workload of the original code, then attach `Global_SF_N` to that exact part of the computation. Do not add it mechanically, do not treat it as a cosmetic parameter, and do not use one fixed scaling template for every task. The scaling rule must be chosen program-by-program.

Use `Global_SF_N` to enlarge the real problem size or workload: dimensions for grids or tables, epochs or dataset repetitions for machine learning, state space or search depth for search / graph / DP problems, and mathematically meaningful iteration or size parameters for numerical routines. Do NOT wrap the whole program in a dummy outer loop, do NOT keep the real problem size unchanged, and do NOT use repetition unless it is the only semantically valid way to increase the true workload.

## 3. Code Preservation Rules (What to Keep)
* **Core Logic:** Preserve the original algorithm completely. Do not replace it with a simpler or different approach.
* **Dependencies:** Keep all necessary helper functions, class definitions, and methods required by the core algorithm.
* **Style:** Maintain the original naming conventions and coding style. Do not invent prefix names like `transformed_*`.
* **Compilability:** The final transformed code must be valid compilable C++ code, not pseudo-code, not partial code, and not C code pasted into C++ without proper correction. Avoid non-standard shortcuts such as `bits/stdc++.h`, avoid C++ keyword or identifier conflicts, preserve required namespace qualifiers and symbol references, do not leave unresolved names, broken declarations, or half-merged multi-file code, and explicitly include every standard header required by the standard library types and functions you actually use.
* **Determinism:** If the original code relies on randomness, refactor it to be deterministic so repeated calls to `solve()` yield perfectly reproducible results.
* **State Safety:** Do not rely on mutable global state that persists across calls unless it is fully reset inside `solve()`.
* **Semantic Fidelity:** The transformed code must preserve the original task meaning. Adding `Global_SF_N` is allowed to scale the computation, but it must not change what problem is being solved.

## 4. Code Purge Rules (What to Remove)
You MUST rigorously remove the following:
* The `main` function.
* Any test, demo, example runner, or benchmark-only logic.
* All console interaction (e.g., `std::cin`, `std::cout`, `printf`, waiting for stdin).
* Any file-reading/writing I/O logic that exists solely for the original demo path.
* Validation/verification scaffolding not required by the core algorithmic computation.

## 5. Output Format
* You MUST output ONLY the transformed code wrapped in a standard markdown code block (e.g., ```cpp ... ```).
* DO NOT output any conversational text, explanations, greetings, or thought processes before or after the code block.
* DO NOT include any comments outside of the markdown code block.
* DO NOT output analysis, plans, TODOs, summaries, placeholders, or pseudo-code.
* DO NOT output a code block that lacks the final implemented `solve(...)` function.
