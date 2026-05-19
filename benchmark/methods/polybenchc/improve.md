# Role
You are a RISC-V code optimization expert. Use the existing session context and improve the current PolyBench/C code block for RISC-V performance.

# Target Sample
Sample id: `{sample_id}`
Target function: `{target_name}`

# Latest Debug Result
```json
{debug_result_json}
```

# Task
Use the complete code from your previous assistant reply in this same session as the current code block. Improve it for RISC-V performance while keeping the same target function `{target_name}`, the same signature, the same baseline algorithm, and the same dynamic computation amount. The improvement must be RVV-based: use RISC-V Vector intrinsics or inline RVV assembly. Preserve correctness, keep helper functions coherent, and do not include `main`.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete improved program block without main
</code>
