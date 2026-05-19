# Role
You are a RISC-V code optimization expert. Optimize the NPB code block below for RISC-V performance, and strictly follow all requirements below.

# Target Sample
Sample id: `{sample_id}`
Target function: `{target_name}`

# Baseline Program Block To Modify
Modify this baseline code block directly. Keep the target function and keep any helper code in this block that the target function needs.

```c
{baseline_code}
```

# Fixed Runtime Context
{driver_context}

# Constraints
{main_constraint}
* Preserve the original benchmark semantics, input/output behavior, and dynamic computation amount exactly. You may change loop structure, data access order, and local helper logic only when the resulting execution remains semantically equivalent.
* The optimization must rely mainly on RVV. Use RISC-V Vector intrinsics or inline RVV assembly. When using intrinsics, use the official `__riscv_*` names directly.
* Do not skip work, precompute away major loops, replace computation with constants, or otherwise reduce the real workload.
* Keep the returned block self-contained with respect to the baseline block.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete modified NPB code block
</code>
