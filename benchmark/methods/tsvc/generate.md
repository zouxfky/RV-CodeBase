# Role
You are a RISC-V code optimization expert. Optimize the TSVC kernel below for RISC-V performance, and strictly follow all requirements below.

# Target Sample
Sample id: `{sample_id}`

# Baseline Kernel Block To Modify
Modify this baseline kernel block directly. Keep the same target function name and signature, and keep any helper functions in this block that the target function needs.

```c
{baseline_code}
```

# Fixed Driver
Do not regenerate or modify this driver. Your optimized kernel block will be compiled together with fixed support files (`common.h`, `array_defs.h`, `common.c`, `dummy.c`, `globals.c`) and this exact driver.

```c
{driver_code}
```

# Constraints
* Return a complete replacement for the baseline kernel block above. Do not include `main`.
* Keep the target function `{target_name}` with the same signature and the same externally visible behavior.
* Preserve the baseline algorithm and dynamic computation path exactly. You may use RVV to process consecutive original iterations in chunks, but you must not remove, skip, shortcut, precompute away, fold away, or otherwise reduce the original logical work.
* The optimization must rely mainly on RVV. Use RISC-V Vector intrinsics or inline RVV assembly. When using intrinsics, use the official `__riscv_*` names directly.
* Keep the code self-contained with respect to the baseline kernel block. If the baseline block contains helper functions, preserve or update them as needed, but do not introduce `main` or unrelated scaffolding.
* Correctness against the baseline output is mandatory, and the goal is to improve performance on RISC-V.

# Output Format
Strictly return only one code block enclosed by `<code>` and `</code>`. Do not return any other text, explanation, Markdown fence, or extra content.

<code>
// complete modified kernel block
</code>
