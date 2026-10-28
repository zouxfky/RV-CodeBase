Target extensions: RISC-V bit-manipulation extensions Zba, Zbb, Zbs, and Zbc. The program is a bit-level computation such as encoding, hashing, or encryption.
* Zba: address generation (`sh1add`, `sh2add`, `sh3add`, `add.uw`, `slli.uw`).
* Zbb: basic bit manipulation (`andn`, `orn`, `xnor`, `clz`, `ctz`, `cpop` and their `*w` forms, `min`/`max`, `sext.b`/`sext.h`, `zext.h`, `rol`/`ror`/`rori`, `rev8`, `orc.b`).
* Zbs: single-bit operations (`bclr`, `bset`, `binv`, `bext` and their immediate forms).
* Zbc: carry-less multiplication (`clmul`, `clmulh`, `clmulr`).
* Typical patterns: rotations written with shifts and OR, byte swaps, bit counting loops, AND with an inverted mask, single-bit set/clear/test, shift-and-add index computation, and polynomial multiplication over GF(2) in CRC and GHASH.
* Reach these instructions in one of two ways: rewrite the source so that the compiler matches the instruction (`__builtin_clz`, `__builtin_ctz`, `__builtin_popcount`, `__builtin_bswap32/64`, rotate idioms such as `(x << r) | (x >> (32 - r))`), or replace an operation sequence with short GCC inline assembly such as `asm("clmul %0, %1, %2" : "=r"(d) : "r"(a), "r"(b));`.
* Keep the exact bit widths of the baseline: use the `*w` forms for 32-bit values on RV64 and mask or sign-extend results where the baseline relies on 32-bit wrap-around.
