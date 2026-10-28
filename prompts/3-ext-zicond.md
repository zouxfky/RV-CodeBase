Target extension: RISC-V integer conditional operations extension Zicond (`czero.eqz`, `czero.nez`), together with Zba/Zbb. The program is control-intensive, with data-dependent conditions such as filtering, thresholding, selection, or state updates.
* `czero.eqz rd, rs1, rs2` writes 0 to `rd` if `rs2 == 0`, otherwise `rs1`; `czero.nez rd, rs1, rs2` writes 0 if `rs2 != 0`, otherwise `rs1`.
* First identify conditional structures suitable for branch elimination: hard-to-predict branches in hot loops whose two sides are cheap and free of side effects, such as conditional accumulation, clamping, conditional assignment, and flag or state updates.
* Rewrite them as branch-free selects, e.g. `x = c ? a : b` becomes `czero.nez(b, c) | czero.eqz(a, c)`, and a masked sum `if (m) s += v` becomes `s += czero.eqz(v, m)`.
* Express the select either as a branch-free C expression that the compiler maps to Zicond, or as short GCC inline assembly such as `asm("czero.eqz %0, %1, %2" : "=r"(d) : "r"(a), "r"(c));`.
* Zbb `min`/`max` can also remove compare-and-branch sequences. Keep branches that guard memory accesses or other side effects.
