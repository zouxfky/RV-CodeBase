# Role
You are a RISC-V code optimization expert. Use the existing session context to repair the current target code.

# Latest Debug Result
```json
{debug_result_json}
```

# Requirements
* Use the complete code from your previous assistant reply in this same session as the current target code.
* Fix compile, runtime, or correctness failures first.
* Keep all input and output behavior exactly the same, including return values, memory writes, global side effects, and any observable I/O.
* Keep the same function names, signatures, parameter meanings, return types, and externally visible behavior.
* Preserve the original computation and dynamic workload. Do not skip work, replace computation with constants, precompute away loops, or otherwise reduce the real work being performed.
* Keep useful instruction-set-extension optimization work when possible.
* Do not add unrelated scaffolding or extra entry points.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete repaired target code
</code>
