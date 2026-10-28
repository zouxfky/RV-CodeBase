"""Per-extension settings: target -march, objdump mnemonic regex, and the
extension description passed to the LLM."""

BASE_MARCH = "rv64gc"

EXTENSIONS = {
    "rvv": {
        "march": "rv64gcv",
        "insn_regex": r"vset[i]?vli|vl[0-9a-z]*\.v|vs[0-9a-z]*\.v|v[a-z0-9]+\.(vv|vx|vf|vi|vs|wv|wx|vm|v)",
        "info": """Target extension: RISC-V Vector extension (RVV 1.0).
* Use RVV intrinsics from `<riscv_vector.h>` with the official `__riscv_*` names, with `vsetvl`-based strip-mining so the code is correct for any VLEN.
* Match the element type of the data: `float` arrays use `f32` intrinsics (e.g. `__riscv_vle32_v_f32m*`, `__riscv_vfadd_vv_f32m*`), not `f64`.
* Guard the header exactly as:
  #if defined(__riscv_vector)
  #include <riscv_vector.h>
  #endif""",
    },
    "b": {
        "march": "rv64gc_zba_zbb_zbc_zbs",
        "insn_regex": r"sh[123]add(\.uw)?|add\.uw|slli\.uw|andn|orn|xnor|clzw?|ctzw?|cpopw?|max|maxu|min|minu|sext\.[bh]|zext\.h|rolw?|rorw?|roriw?|rev8|orc\.b|bclri?|bseti?|binvi?|bexti?|clmulh?|clmulr",
        "info": """Target extensions: RISC-V bit-manipulation extensions Zba, Zbb, Zbs, and Zbc.
* Zba: address generation (sh1add, sh2add, sh3add, add.uw, slli.uw).
* Zbb: basic bit manipulation (andn, orn, xnor, clz, ctz, cpop and their *w forms, min/max, sext.b/h, zext.h, rol/ror/rori, rev8, orc.b).
* Zbs: single-bit operations (bclr, bset, binv, bext and immediate forms).
* Zbc: carry-less multiplication (clmul, clmulh, clmulr).
* Reach these instructions through code patterns the compiler maps to them (`__builtin_clz`, `__builtin_ctz`, `__builtin_popcount`, `__builtin_bswap32/64`, rotate idioms such as `(x << r) | (x >> (32 - r))`), or through short GCC inline assembly such as `asm("clmul %0, %1, %2" : "=r"(d) : "r"(a), "r"(b));`.""",
    },
    "zicond": {
        "march": "rv64gc_zicond_zba_zbb",
        "insn_regex": r"czero\.(eqz|nez)",
        "info": """Target extension: RISC-V integer conditional operations extension Zicond (czero.eqz, czero.nez), together with Zba/Zbb.
* `czero.eqz rd, rs1, rs2` writes 0 to rd if rs2 == 0, otherwise rs1; `czero.nez rd, rs1, rs2` writes 0 if rs2 != 0, otherwise rs1.
* Use them to replace hard-to-predict branches with branch-free selects, e.g. `x = c ? a : b` becomes `czero.nez(b, c) | czero.eqz(a, c)`. Write branch-free C select idioms the compiler maps to Zicond, or short GCC inline assembly such as `asm("czero.eqz %0, %1, %2" : "=r"(d) : "r"(a), "r"(c));`.
* Zbb min/max can also remove compare-and-branch sequences.""",
    },
    "ime": {
        "march": "rv64gcv",
        "insn_regex": r"e[23][0-9a-f]{4}[2a]b",
        "info": """Target extensions: RISC-V Vector extension (VLEN = 256) and the SpacemiT integer matrix extension (IME) on the SpacemiT X60 core.
* The IME instruction `vmadotu vd, vs1, vs2` performs an unsigned 8-bit integer matrix multiply-accumulate: with SEW=8 the register vs1 holds a 4x8 uint8 tile A (row-major, 32 bytes) and vs2 holds a 4x8 uint8 tile B (row-major, 32 bytes); the even/odd register pair vd, vd+1 holds a 4x4 uint32 tile C (row-major, 64 bytes), and the instruction computes C += A * B^T.
* The assembler does not accept the mnemonic. Emit it as a raw word: encoding = (0x71 << 25) | (vs2 << 20) | (vs1 << 15) | (vd << 7) | 0x2b, where vd must be even. Example: `vmadotu v16, v8, v9` is `.word 0xe294082b`.
* Because the registers are fixed in the encoding, load and store the operands inside the same inline assembly block, for example:
  asm volatile("vsetvli t0, zero, e8, m1, ta, ma\\n vle8.v v8, (%1)\\n vle8.v v9, (%2)\\n"
               "vsetvli t0, zero, e32, m2, ta, ma\\n vle32.v v16, (%0)\\n"
               ".word 0xe294082b\\n vse32.v v16, (%0)\\n"
               :: "r"(c_tile), "r"(a_tile), "r"(b_tile) : "t0", "v8", "v9", "v16", "v17", "memory");
* Pack the operands into contiguous tiles first (B must be packed so that each 8-byte row is one column of the original matrix). Keep the C tile in registers across the k loop when possible. RVV intrinsics may be used for packing and for the remaining elements.""",
    },
}


def march_for(extension: str, *, with_extension: bool = True) -> str:
    return EXTENSIONS[extension]["march"] if with_extension else BASE_MARCH
