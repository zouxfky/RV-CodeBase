# Role
You are a RISC-V code optimization expert. Optimize the baseline code below for RISC-V performance using the {extension} extension, and strictly follow all requirements below.

# Target Extension
{extension_guidance}

# Baseline Code To Modify
Modify this baseline code directly. Keep the same `solve(...)` interface and keep any required headers/helpers that this code needs.

```cpp
{baseline_code}
```

# Fixed main()
Do not regenerate or modify this `main`. Your optimized `solve(...)` will be concatenated with this exact program.

```cpp
{main_program}
```

# Constraints
* Return a complete replacement for the baseline code block above, do not include `main`, and do not change the `solve(...)` signature or the meaning, type, or role of `Global_SF_N` and `Global_Result`.
* Preserve the baseline algorithm and dynamic computation path exactly. You may map original operations or consecutive original iterations onto {extension} instructions, but you must not remove or skip any original logical work. You must not reduce computation amount in any way, even if some computation appears redundant. Do not remove loops, collapse repeated work, fold nested counting into a formula, precompute results that replace runtime work, skip iterations, fuse logically repeated passes into one cheaper pass, strengthen conditions to avoid work, or introduce any shortcut that lowers the executed arithmetic/comparison/memory-work amount.
* The optimization must rely on the {extension} extension described above, through intrinsics, code patterns that the compiler maps to {extension} instructions, or inline assembly. Do not rely on pure scalar refactoring as the main optimization method.
* Apart from the required {extension}-based rewrite, keep the same semantics and the same effective work as the baseline.
* The returned code must be self-contained and compile as the first part of one translation unit before the fixed `main()`: include any required standard headers inside `<code>`, do not rely on headers that appear later in `main()`, and do not reference undefined external helpers, constants, classes, namespaces, or macros.
* Correctness against the baseline output is mandatory, and the goal is to improve performance on RISC-V.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete modified baseline code block
</code>
