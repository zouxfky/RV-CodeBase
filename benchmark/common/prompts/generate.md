# Role
You are a RISC-V code optimization expert. Optimize the target code below for a RISC-V processor that implements the instruction set extensions described below.

# Instruction Set Extensions
{extension_info}

# Target Code
Modify only the following target code.

```c
{baseline_code}
```

# Requirements
* Return a complete replacement for the target code above.
* Keep all input and output behavior exactly the same, including return values, memory writes, global side effects, and any observable I/O.
* Keep the same function names, signatures, parameter meanings, return types, global variable names, and externally visible behavior.
* Preserve the original computation and dynamic workload. Do not skip work, replace computation with constants, precompute away loops, or otherwise reduce the real work being performed.
* Optimize mainly by using the instruction set extensions above where they apply.
* Do not add a `main` function, unrelated scaffolding, or extra entry points.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete optimized target code
</code>
