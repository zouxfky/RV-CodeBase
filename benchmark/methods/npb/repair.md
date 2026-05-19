# Role
You are a RISC-V code optimization expert. Use the existing session context and repair the current NPB code block for RISC-V performance.

# Target Sample
Sample id: `{sample_id}`
Target function: `{target_name}`

# Latest Debug Result
```json
{debug_result_json}
```

# Task
Use the complete code from your previous assistant reply in this same session as the current code block. Repair it while preserving the same target function, benchmark semantics, and dynamic computation amount. Fix compile, runtime, and correctness issues first, preserve useful RVV optimization work when possible, and keep helper code coherent.

# Constraints
{main_constraint}
* Keep RVV as the primary optimization mechanism.
* Do not remove real work or replace the computation with a cheaper surrogate.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete repaired NPB code block
</code>
