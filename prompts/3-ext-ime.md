Target extensions: RISC-V Vector extension (VLEN = 256) and the SpacemiT integer matrix extension (IME) on the SpacemiT X60 core. The program is a machine-learning kernel such as matrix multiplication, convolution, or a fully connected layer.
* The IME instruction `vmadot vd, vs1, vs2` (signed) and its variants `vmadotu`, `vmadotsu`, `vmadotus` perform an 8-bit integer matrix multiply-accumulate: with SEW=8 the register `vs1` holds a 4x8 int8 tile A (row-major, 32 bytes) and `vs2` holds a 4x8 int8 tile B (row-major, 32 bytes); the even/odd register pair `vd`, `vd+1` holds a 4x4 int32 tile C (row-major, 64 bytes), and the instruction computes C += A * B^T.
* Operand layout requirements: `vd` must be an even register; A and B must be packed into contiguous 32-byte tiles, and B must be packed so that each 8-byte row is one column of the original matrix; the C tile is int32 and must be accumulated across the k dimension.
* The assembler does not accept the mnemonic. Emit it as a raw word: encoding = (0x71 << 25) | (vs2 << 20) | (vs1 << 15) | (funct3 << 12) | (vd << 7) | 0x2b, where funct3 selects the signedness variant (0 for `vmadotu`). Example: `vmadotu v16, v8, v9` is `.word 0xe294082b`.
* Because the registers are fixed in the encoding, load and store the operands inside the same inline assembly block, for example:
  asm volatile("vsetvli t0, zero, e8, m1, ta, ma\n vle8.v v8, (%1)\n vle8.v v9, (%2)\n"
               "vsetvli t0, zero, e32, m2, ta, ma\n vle32.v v16, (%0)\n"
               ".word 0xe294082b\n vse32.v v16, (%0)\n"
               :: "r"(c_tile), "r"(a_tile), "r"(b_tile) : "t0", "v8", "v9", "v16", "v17", "memory");
* Tile the computation into 4x8 by 8x4 blocks, rearrange the data into the packed layout, keep the C tile in registers across the k loop when possible, and handle the remaining rows, columns, and k elements with RVV intrinsics or scalar code.
* For convolutions, lower the input to a matrix form (im2col or direct packing) before applying the tiles; apply requantization and activation after the int32 accumulation, exactly as the baseline does.
