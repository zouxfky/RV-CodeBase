Target extension: RISC-V Vector extension (RVV 1.0). The program is a numerical computation over arrays, vectors, or matrices.
* Vectorize the hot loops with RVV intrinsics from `<riscv_vector.h>`, using the official intrinsic names with the `__riscv_` prefix (for example `__riscv_vsetvl_e32m1`, `__riscv_vle32_v_f32m1`, `__riscv_vfmacc_vv_f32m1`, `__riscv_vse32_v_f32m1`).
* Strip-mine every loop with `vsetvl` so the code is correct for any VLEN and for trip counts that are not a multiple of the vector length; do not assume a fixed VLEN.
* Match intrinsic types to the element type and LMUL (for example `vfloat32m1_t` with `_f32m1` intrinsics), and use the `vfred*` / `vred*` reductions with a scalar seed for sums, minima, and maxima.
* Keep the floating-point evaluation order close to the baseline; reordered reductions are allowed only within the output tolerance of the correctness check.
* Use masks (`vmflt`, `vmseq`, ...) and masked or merge intrinsics for element-wise conditions instead of scalar branches inside vectorized loops.
