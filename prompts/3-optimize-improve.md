# Role
You are a RISC-V code optimization expert. Use the existing session context and improve the current code below for RISC-V performance.

# Latest Debug Result
```json
{debug_result_json}
```

# Task
Use the complete code from your previous assistant reply in this same session as the current code. Improve it for RISC-V performance while keeping the same `solve(...)` interface, the same meaning and role of `Global_SF_N` and `Global_Result`, the same baseline algorithm, and the same dynamic computation amount. The improvement must be based on the {extension} extension, following the target-extension guidance given at the start of this session. You must not remove or skip any original logical work. Do not reduce work by removing loops, collapsing repeated computation, replacing runtime computation with formulas or precomputation, skipping iterations, or otherwise making the computation cheaper than the baseline. Preserve correctness, keep the code self-contained, and do not include `main`.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete improved code block
</code>
