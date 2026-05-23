# Role
You are a RISC-V code optimization expert. Optimize the target code below for RISC-V performance.

# Target Code
Modify only the following target code.

```c
{baseline_code}
```

# Requirements
* Return a complete replacement for the target code above.
* Keep all input and output behavior exactly the same, including return values, memory writes, global side effects, and any observable I/O.
* Keep the same function names, signatures, parameter meanings, return types, and externally visible behavior.
* Preserve the original computation and dynamic workload. Do not skip work, replace computation with constants, precompute away loops, or otherwise reduce the real work being performed.
* Optimize mainly with RISC-V Vector techniques. Use RISC-V Vector intrinsics or inline RVV assembly when useful. When using intrinsics, use the official `__riscv_*` names directly.
* If you use any `__riscv_*` intrinsic, you MUST include the header. Do not assume it is already included. Use the following guarded include exactly:
  ```c
  #if defined(__riscv_vector)
  #include <riscv_vector.h>
  #endif
  ```
* Do not add unrelated scaffolding or extra entry points.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete optimized target code
</code>
