# RVV 1.0 Instruction Set

## 1. Configuration-Setting Instructions

### 1.1 Vector Configuration Instructions

#### 1.1.1 `vsetvli` / `vsetivli` / `vsetvl`

##### Function

`vsetvli`, `vsetivli`, and `vsetvl` configure the `vl` and `vtype` fields in the RVV control and status registers. After execution, the new `vl` value is written to the destination register `rd`. These instructions only set up the vector execution environment; they do not perform vector arithmetic, memory accesses, or reductions.

##### Instruction Formats

```asm
vsetvli  rd, rs1, e32, m1, ta, ma
vsetivli rd, uimm, e16, m2, ta, ma
vsetvl   rd, rs1, rs2
```

- `vsetvli`: AVL is taken from register `rs1`; `vtype` is specified directly by the assembly arguments.
- `vsetivli`: AVL is provided as the immediate `uimm`; `vtype` is specified directly by the assembly arguments.
- `vsetvl`: AVL is taken from register `rs1`; `vtype` is taken from register `rs2`.

Preferred notation: named configuration form such as `e32, m1, ta, ma`. Use the raw `vtypei` immediate only in encoding discussions.

##### Parameters

| Parameter | Meaning |
|---|---|
| `rd` | Destination register for the new `vl` |
| `rs1` | Source register for AVL (Application Vector Length) |
| `uimm` | Immediate AVL value |
| `rs2` | Source register for `vtype`, used only by `vsetvl` |
| `e{SEW}` | Standard element width, e.g. `e8`, `e16`, `e32`, `e64` |
| `m{LMUL}` | Register group multiplier, e.g. `m1`, `m2`, `m4`, `m8`, including fractional LMUL |
| `ta / tu` | Tail agnostic / tail undisturbed |
| `ma / mu` | Mask agnostic / mask undisturbed |

##### Semantics

These instructions serve three primary purposes:

1. Compute the effective `vl` based on the current AVL.
2. Set the `SEW`, `LMUL`, tail policy, and mask policy for subsequent vector instructions.
3. Provide a unified entry point for strip-mining loops, configuration switching and RVV context restoration.

##### Assembly Examples

```asm
vsetvli  t0, a0, e32, m1, ta, ma
vsetivli t1, 16, e16, m2, ta, ma
vsetvl   t2, a1, a2
```

- The first instruction sets the configuration to `e32, m1` using the AVL stored in `a0`.
- The second instruction uses the immediate `16` as AVL and sets the configuration to `e16, m2`.
- The third instruction restores or sets `vl/vtype` from registers.

##### Intrinsics

Common intrinsic forms:

```c
size_t __riscv_vsetvl_e{sew}m{lmul}(size_t avl);
```

Example:

```c
size_t vl1 = __riscv_vsetvl_e32m1(n);
size_t vl2 = __riscv_vsetvl_e64m4(64);
```

These intrinsics request `vl` for a given `SEW/LMUL` configuration and typically map to `vsetvli` or an equivalent configuration sequence.

##### Notes

1. Scope: vector configuration instructions only; excludes element writes, vector moves, and vector memory accesses.
2. `__riscv_vset_v_*` writes vector elements and is not part of the `vsetvli` / `vsetivli` / `vsetvl` family.
3. Preferred notation: named configuration form such as `e32, m1, ta, ma`; raw `vtypei` immediate is reserved for encoding discussions.

## 2. Vector Loads and Stores Instructions

### 2.1 Vector Unit-Stride Instructions

#### 2.1.1 `vle<eew>.v` / `vse<eew>.v`

##### Function

`vle<eew>.v` loads active elements from contiguous memory into a vector register group. `vse<eew>.v` stores active elements from a vector register group to contiguous memory. These are the basic unit-stride vector memory operations.

##### Instruction Formats

```asm
vle32.v vd, (rs1), v0.t
vse16.v vs3, (rs1)
```

- `vle<eew>.v`: unit-stride load
- `vse<eew>.v`: unit-stride store

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group for loads |
| `vs3` | Source vector register group for stores |
| `rs1` | Base address register |
| `v0.t` | Optional mask operand; masked-off elements are not accessed |
| `<eew>` | Memory element width encoded in the instruction mnemonic, such as `8`, `16`, `32`, or `64` |

##### Semantics

1. Element `i` accesses memory at `base + i * (EEW / 8)`.
2. Only active elements in the current `vl` participate in the operation.
3. Masked forms use `v0.t`; RVV masked memory instructions do not use arbitrary mask registers.

##### Assembly Examples

```asm
vle32.v v5, (a0), v0.t
vse16.v v3, (a1)
```

- `vle32.v v5, (a0), v0.t`: load 32-bit elements from contiguous memory starting at `a0`, under mask `v0.t`.
- `vse16.v v3, (a1)`: store 16-bit elements from `v3` to contiguous memory starting at `a1`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t __riscv_vle32_v_i32m1(const int32_t *base, size_t vl);
void __riscv_vse16_v_i16m1(int16_t *base, vint16m1_t value, size_t vl);
```

Example:

```c
vint32m1_t data = __riscv_vle32_v_i32m1(ptr32, vl);
__riscv_vse16_v_i16m1(ptr16, vec16, vl);
```

##### Notes

1. The mask operand, when present, is written as `v0.t`.
2. The intrinsic name encodes both the data type and the LMUL.
3. The mnemonic suffix `<eew>` names the memory element width used by the instruction.

#### 2.1.2 `vlm.v` / `vsm.v`

##### Function

`vlm.v` loads mask bits from memory into a mask register. `vsm.v` stores mask bits from a mask register to memory. These instructions transfer packed mask data rather than ordinary vector data elements.

##### Instruction Formats

```asm
vlm.v vd, (rs1)
vsm.v vs3, (rs1)
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register for loads |
| `vs3` | Source mask register for stores |
| `rs1` | Base address register |

##### Semantics

1. `vlm.v` and `vsm.v` operate on mask-register contents, not on ordinary integer or floating-point vectors.
2. The memory representation is packed by bits.
3. The effective number of active mask bits is determined by `vl`.

##### Assembly Examples

```asm
vlm.v v1, (a2)
vsm.v v0, (a3)
```

- `vlm.v v1, (a2)`: load packed mask bits from memory at `a2` into mask register `v1`.
- `vsm.v v0, (a3)`: store packed mask bits from `v0` to memory at `a3`.

##### Intrinsics

Common intrinsic forms:

```c
vbool8_t __riscv_vlm_v_b8(const uint8_t *base, size_t vl);
void __riscv_vsm_v_b8(uint8_t *base, vbool8_t value, size_t vl);
```

Example:

```c
vbool8_t mask = __riscv_vlm_v_b8(mask_ptr, vl);
__riscv_vsm_v_b8(mask_ptr, mask, vl);
```

##### Notes

1. These instructions do not take an explicit mask operand.
2. Intrinsic suffixes such as `b8`, `b16`, and `b32` correspond to mask types such as `vbool8_t`, `vbool16_t`, and `vbool32_t`.
3. `vlm.v` / `vsm.v` are used for transferring mask state, not general vector payloads.

### 2.2 Vector Strided Instructions

#### 2.2.1 `vlse<eew>.v` / `vsse<eew>.v`

##### Function

`vlse<eew>.v` loads active elements from memory using a byte stride. `vsse<eew>.v` stores active elements using a byte stride. These instructions are used when adjacent vector elements are separated by a fixed byte distance in memory.

##### Instruction Formats

```asm
vlse32.v vd, (rs1), rs2, v0.t
vsse16.v vs3, (rs1), rs2
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group for loads |
| `vs3` | Source vector register group for stores |
| `rs1` | Base address register |
| `rs2` | Byte stride between consecutive elements |
| `v0.t` | Optional mask operand |
| `<eew>` | Memory element width encoded in the instruction mnemonic |

##### Semantics

1. Element `i` accesses memory at `base + i * stride_bytes`.
2. The stride in `rs2` is measured in bytes, not in elements.
3. Masked forms use `v0.t`.

##### Assembly Examples

```asm
vlse32.v v4, (a0), a1, v0.t
vsse16.v v2, (a2), x5
vlse8.v  v8, (a3), t1
vsse64.v v10, (a4), s2, v0.t
```

- `vlse32.v v4, (a0), a1, v0.t`: load 32-bit elements from `a0` with byte stride `a1`, under mask `v0.t`.
- `vsse16.v v2, (a2), x5`: store 16-bit elements from `v2` using byte stride `x5`.
- `vlse8.v v8, (a3), t1`: load 8-bit elements from `a3` using byte stride `t1`.
- `vsse64.v v10, (a4), s2, v0.t`: store 64-bit elements from `v10` using byte stride `s2`, under mask `v0.t`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t __riscv_vlse32_v_i32m1(const int32_t *base, ptrdiff_t bstride, size_t vl);
void __riscv_vsse16_v_i16m1(int16_t *base, ptrdiff_t bstride, vint16m1_t value, size_t vl);
```

Example:

```c
vint32m1_t data = __riscv_vlse32_v_i32m1(ptr32, stride_bytes, vl);
__riscv_vsse16_v_i16m1(ptr16, stride_bytes, vec16, vl);
```

##### Notes

1. `bstride` is expressed in bytes.
2. Zero and non-unit strides are valid when the memory layout requires them.
3. The mask operand, when present, is `v0.t`.

### 2.3 Vector Indexed Instructions

#### 2.3.1 `vluxei<eew>.v` / `vloxei<eew>.v` / `vsuxei<eew>.v` / `vsoxei<eew>.v`

##### Function

These instructions perform vector indexed memory accesses. `vluxei<eew>.v` and `vsuxei<eew>.v` are unordered indexed load and store operations. `vloxei<eew>.v` and `vsoxei<eew>.v` are ordered indexed load and store operations.

##### Instruction Formats

```asm
vluxei32.v vd, (rs1), vs2, v0.t
vloxei16.v vd, (rs1), vs2
vsuxei64.v vs3, (rs1), vs2, v0.t
vsoxei8.v  vs3, (rs1), vs2
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group for loads |
| `vs3` | Source vector register group for stores |
| `rs1` | Base address register |
| `vs2` | Vector of byte offsets |
| `v0.t` | Optional mask operand |
| `<eew>` | Width of each index element in `vs2`, encoded in the mnemonic |

##### Semantics

1. Element `i` accesses memory at `base + bindex[i]`, where `bindex[i]` is the byte offset stored in `vs2[i]`.
2. The ordered forms preserve element access order; the unordered forms do not require ordered element accesses.
3. In indexed instructions, `<eew>` describes the width of the index elements, not the width of the loaded or stored payload data.

##### Assembly Examples

```asm
vluxei32.v v5, (a0), v3, v0.t
vloxei16.v v8, (a1), v4
vsuxei64.v v10, (a2), v6, v0.t
vsoxei8.v  v2, (a3), v7
```

- `vluxei32.v v5, (a0), v3, v0.t`: unordered indexed load with 32-bit index elements from `v3`, under mask `v0.t`.
- `vloxei16.v v8, (a1), v4`: ordered indexed load with 16-bit index elements from `v4`.
- `vsuxei64.v v10, (a2), v6, v0.t`: unordered indexed store with 64-bit index elements from `v6`, under mask `v0.t`.
- `vsoxei8.v v2, (a3), v7`: ordered indexed store with 8-bit index elements from `v7`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t __riscv_vluxei32_v_i32m1(const int32_t *base, vuint32m1_t bindex, size_t vl);
vint16m1_t __riscv_vloxei16_v_i16m1(const int16_t *base, vuint16m1_t bindex, size_t vl);
void __riscv_vsuxei64_v_i64m1(int64_t *base, vuint64m1_t bindex, vint64m1_t value, size_t vl);
void __riscv_vsoxei8_v_i8m1(int8_t *base, vuint8m1_t bindex, vint8m1_t value, size_t vl);
```

Example:

```c
vint32m1_t gathered = __riscv_vluxei32_v_i32m1(base32, index32, vl);
vint16m1_t ordered  = __riscv_vloxei16_v_i16m1(base16, index16, vl);
__riscv_vsuxei64_v_i64m1(base64, index64, value64, vl);
__riscv_vsoxei8_v_i8m1(base8, index8, value8, vl);
```

##### Notes

1. The index vector contains byte offsets.
2. The mask operand, when present, is `v0.t`.
3. Ordered and unordered forms are distinct instruction families and should not be treated as interchangeable in documentation or retrieval.

### 2.4 Unit-Stride Fault-Only-First Load Instructions

#### 2.4.1 `vle<eew>ff.v`

##### Function

`vle<eew>ff.v` is a unit-stride fault-only-first load instruction. It is used for vectorizing loops with data-dependent exit conditions, such as scanning until a terminator or until an inaccessible address is encountered.

##### Instruction Formats

```asm
vle8ff.v  vd, (rs1)
vle16ff.v vd, (rs1), v0.t
vle32ff.v vd, (rs1)
vle64ff.v vd, (rs1)
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `rs1` | Base address register |
| `v0.t` | Optional mask operand |
| `<eew>` | Memory element width encoded in the mnemonic |

##### Semantics

1. Element `0` behaves as the fault-checking element: if it raises a synchronous exception, the trap is taken and `vl` is not reduced.
2. If a later element would raise a synchronous exception, the trap is not taken; instead, `vl` is reduced to the number of elements successfully processed.
3. Implementations may also complete fewer than the requested `vl` elements and reduce `vl` accordingly.

##### Assembly Examples

```asm
vle32ff.v v5, (a0)
vle16ff.v v8, (a1), v0.t
vle64ff.v v10, (a2)
```

- `vle32ff.v v5, (a0)`: fault-only-first load of 32-bit elements from `a0`.
- `vle16ff.v v8, (a1), v0.t`: masked fault-only-first load of 16-bit elements from `a1`.
- `vle64ff.v v10, (a2)`: fault-only-first load of 64-bit elements from `a2`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t __riscv_vle32ff_v_i32m1(const int32_t *base, size_t *new_vl, size_t vl);
```

Example:

```c
size_t actual_vl = 0;
vint32m1_t data = __riscv_vle32ff_v_i32m1(ptr32, &actual_vl, vl);
```

##### Notes

1. The intrinsic reports the completed element count through `new_vl`.
2. Only unit-stride fault-only-first loads are defined here; there is no strided or indexed `ff` form in this chapter.
3. These instructions are intended for forward-progress style scans rather than ordinary bulk loads.

### 2.5 Vector Load/Store Segment Instructions

#### 2.5.1 `vlseg<nf>e<eew>.v` / `vsseg<nf>e<eew>.v`

##### Function

These instructions move segments containing `nf` contiguous fields between memory and consecutive vector register groups. They are commonly used for array-of-structures layouts, such as complex numbers, RGB data, or interleaved multi-channel samples.

##### Instruction Formats

```asm
vlseg2e32.v vd, (rs1)
vsseg3e16.v vs3, (rs1)
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | First destination vector register group for loads |
| `vs3` | First source vector register group for stores |
| `rs1` | Base address register |
| `v0.t` | Optional mask operand |
| `<nf>` | Number of fields per segment, from `2` to `8` |
| `<eew>` | Memory element width encoded in the mnemonic |

##### Semantics

1. Each segment contains `nf` contiguous fields in memory.
2. Load results are distributed into consecutive vector register groups starting at `vd`; store data is read from consecutive groups starting at `vs3`.
3. For `vlseg2e32.v`, field 0 is written to `vd`, and field 1 is written to `vd+1`.

##### Assembly Examples

```asm
vlseg2e32.v v2, (a0)
vsseg3e16.v v4, (a1)
```

- `vlseg2e32.v v2, (a0)`: load 2-field, 32-bit segments from `a0` into `v2` and `v3`.
- `vsseg3e16.v v4, (a1)`: store 3-field, 16-bit segments from `v4`, `v5`, and `v6`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1x2_t __riscv_vlseg2e32_v_i32m1x2(const int32_t *base, size_t vl);
void __riscv_vsseg3e16_v_i16m1x3(int16_t *base, vint16m1x3_t value, size_t vl);
```

Example:

```c
vint32m1x2_t pair = __riscv_vlseg2e32_v_i32m1x2(ptr32, vl);
__riscv_vsseg3e16_v_i16m1x3(ptr16, triple16, vl);
```

##### Notes

1. The tuple suffix `x<nf>` in the intrinsic type matches the segment field count.
2. `vd` and `vs3` name the first register group only; the remaining fields occupy consecutive groups.
3. These instructions are the natural segment form for packed AoS layouts.

#### 2.5.2 `vlseg<nf>e<eew>ff.v`

##### Function

`vlseg<nf>e<eew>ff.v` is the fault-only-first form of the unit-stride segment load instruction. It combines segment loading with fault-only-first behavior.

##### Instruction Formats

```asm
vlseg2e32ff.v vd, (rs1), v0.t
vlseg3e16ff.v vd, (rs1)
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | First destination vector register group |
| `rs1` | Base address register |
| `v0.t` | Optional mask operand |
| `<nf>` | Number of fields per segment |
| `<eew>` | Memory element width encoded in the mnemonic |

##### Semantics

1. A fault detected during the first segment takes a trap.
2. A fault detected during a later segment reduces `vl` instead of taking the trap.
3. The completed segment count is returned through the updated `vl` value.

##### Assembly Examples

```asm
vlseg2e32ff.v v4, (a0), v0.t
vlseg3e16ff.v v8, (a1)
```

- `vlseg2e32ff.v v4, (a0), v0.t`: masked fault-only-first load of 2-field, 32-bit segments.
- `vlseg3e16ff.v v8, (a1)`: fault-only-first load of 3-field, 16-bit segments.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1x2_t __riscv_vlseg2e32ff_v_i32m1x2(const int32_t *base, size_t *new_vl, size_t vl);
```

Example:

```c
size_t actual_vl = 0;
vint32m1x2_t pair = __riscv_vlseg2e32ff_v_i32m1x2(ptr32, &actual_vl, vl);
```

##### Notes

1. The intrinsic reports the completed segment count through `new_vl`.
2. This is a load-only family; there is no `vsseg...ff`.
3. The tuple suffix `x<nf>` still matches the segment field count.

#### 2.5.3 `vlsseg<nf>e<eew>.v` / `vssseg<nf>e<eew>.v`

##### Function

These instructions move segments separated by a fixed byte stride. Each segment still contains `nf` contiguous fields, but consecutive segments are spaced apart by the byte stride supplied in `rs2`.

##### Instruction Formats

```asm
vlsseg2e32.v vd, (rs1), rs2
vssseg3e16.v vs3, (rs1), rs2
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | First destination vector register group for loads |
| `vs3` | First source vector register group for stores |
| `rs1` | Base address register |
| `rs2` | Byte stride between consecutive segments |
| `v0.t` | Optional mask operand |
| `<nf>` | Number of fields per segment |
| `<eew>` | Memory element width encoded in the mnemonic |

##### Semantics

1. Segment `i` starts at `base + i * bstride`.
2. Fields inside one segment remain contiguous in memory.
3. Negative and zero strides are allowed.

##### Assembly Examples

```asm
vlsseg2e32.v v8, (a3), t1
vssseg3e16.v v10, (a4), t2
```

- `vlsseg2e32.v v8, (a3), t1`: load 2-field, 32-bit segments using byte stride `t1`.
- `vssseg3e16.v v10, (a4), t2`: store 3-field, 16-bit segments using byte stride `t2`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1x2_t __riscv_vlsseg2e32_v_i32m1x2(const int32_t *base, ptrdiff_t bstride, size_t vl);
void __riscv_vssseg3e16_v_i16m1x3(int16_t *base, ptrdiff_t bstride, vint16m1x3_t value, size_t vl);
```

Example:

```c
vint32m1x2_t pair = __riscv_vlsseg2e32_v_i32m1x2(ptr32, stride_bytes, vl);
__riscv_vssseg3e16_v_i16m1x3(ptr16, stride_bytes, triple16, vl);
```

##### Notes

1. `bstride` is measured in bytes.
2. The tuple suffix `x<nf>` matches the segment field count.
3. There is no fault-only-first `vlsseg` / `vssseg` form.

#### 2.5.4 `vluxseg<nf>ei<eew>.v` / `vloxseg<nf>ei<eew>.v` / `vsuxseg<nf>ei<eew>.v` / `vsoxseg<nf>ei<eew>.v`

##### Function

These instructions move segments whose starting addresses are computed from a scalar base plus per-element byte offsets in an index vector. Both ordered and unordered forms are provided.

##### Instruction Formats

```asm
vluxseg2ei32.v vd, (rs1), vs2, v0.t
vloxseg2ei16.v vd, (rs1), vs2
vsuxseg2ei32.v vs3, (rs1), vs2, v0.t
vsoxseg2ei16.v vs3, (rs1), vs2
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | First destination vector register group for loads |
| `vs3` | First source vector register group for stores |
| `rs1` | Base address register |
| `vs2` | Vector of byte offsets |
| `v0.t` | Optional mask operand |
| `<nf>` | Number of fields per segment |
| `<eew>` | Width of the index elements encoded in the mnemonic |

##### Semantics

1. Segment `i` starts at `base + bindex[i]`, where `bindex[i]` comes from `vs2`.
2. Fields within a segment remain contiguous in memory.
3. Ordered forms preserve segment access order; unordered forms do not require ordered segment accesses.

##### Assembly Examples

```asm
vluxseg2ei32.v v12, (a5), v4, v0.t
vloxseg2ei16.v v14, (a6), v6
vsuxseg2ei32.v v16, (a7), v8, v0.t
vsoxseg2ei16.v v18, (s0), v10
```

- `vluxseg2ei32.v v12, (a5), v4, v0.t`: unordered indexed load of 2-field segments with 32-bit index elements.
- `vloxseg2ei16.v v14, (a6), v6`: ordered indexed load of 2-field segments with 16-bit index elements.
- `vsuxseg2ei32.v v16, (a7), v8, v0.t`: unordered indexed store of 2-field segments with 32-bit index elements.
- `vsoxseg2ei16.v v18, (s0), v10`: ordered indexed store of 2-field segments with 16-bit index elements.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1x2_t __riscv_vluxseg2ei32_v_i32m1x2(const int32_t *base, vuint32m1_t bindex, size_t vl);
vint32m1x2_t __riscv_vloxseg2ei16_v_i32m1x2(const int32_t *base, vuint16mf2_t bindex, size_t vl);
void __riscv_vsuxseg2ei32_v_i32m1x2(int32_t *base, vuint32m1_t bindex, vint32m1x2_t value, size_t vl);
void __riscv_vsoxseg2ei16_v_i32m1x2(int32_t *base, vuint16mf2_t bindex, vint32m1x2_t value, size_t vl);
```

Example:

```c
vint32m1x2_t useg = __riscv_vluxseg2ei32_v_i32m1x2(base32, index32, vl);
vint32m1x2_t oseg = __riscv_vloxseg2ei16_v_i32m1x2(base32, index16, vl);
__riscv_vsuxseg2ei32_v_i32m1x2(base32, index32, useg, vl);
__riscv_vsoxseg2ei16_v_i32m1x2(base32, index16, useg, vl);
```

##### Notes

1. The index vector contains byte offsets.
2. In indexed segment instructions, `<eew>` describes the index element width, not the payload element width.
3. The index vector type in the intrinsic depends on the effective index EMUL; it is not always the same LMUL as the payload tuple.

### 2.6 Vector Load/Store Whole Register Instructions

#### 2.6.1 `vl<nf>re<eew>.v` / `vs<nf>r.v`

##### Function

These instructions load and store whole vector register groups without depending on the current `vtype` setting. They are intended for save/restore paths, compiler spills, interrupt handling, ABI-preserved vector state, and other cases where the current element interpretation of the register contents is not known or should not be changed.

##### Instruction Formats

```asm
vl2re32.v v2, (a0)
vs4r.v    v4, (a1)
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | First destination vector register group for loads |
| `vs3` | First source vector register group for stores |
| `rs1` | Base address register |
| `<nf>` | Number of whole vector registers transferred; valid forms are `1`, `2`, `4`, and `8` |
| `<eew>` | Encoded element width for the load form, such as `8`, `16`, `32`, or `64` |

##### Semantics

1. Whole-register load/store instructions transfer raw register contents rather than values interpreted through the current `SEW/LMUL`.
2. These instructions operate with an effective vector length `evl = NFIELDS * VLEN / EEW`, independent of the current `vl` and `vtype`.
3. The load-side encoded `EEW` selects the memory transfer granularity, but the in-register byte layout remains the same.

##### Assembly Examples

```asm
vl2re32.v v2, (a0)
vs4r.v    v4, (a1)
```

- `vl2re32.v v2, (a0)`: load the raw contents of `v2` and `v3` from memory at `a0`.
- `vs4r.v v4, (a1)`: store the raw contents of `v4` through `v7` to memory at `a1`.

##### Intrinsics

No direct named whole-register load/store intrinsic family is documented here. These instructions are primarily assembly-level operations and are commonly emitted by compiler save/restore code or written via inline assembly when needed.

##### Notes

1. Pseudoinstructions such as `vl2r.v` expand to the corresponding `vl2re8.v` form.
2. These instructions do not depend on the current `vtype`, which is the main reason they are used for state preservation.
3. Implementations may impose alignment requirements based on the encoded `EEW` and the implementation's minimum supported `SEW`.

## 3. Vector Arithmetic Instruction Formats

### 3.1 Binary Vector Arithmetic Formats

#### 3.1.1 `vop.vv` / `vop.vx` / `vop.vi` / `vfop.vv` / `vfop.vf`

##### Function

These templates describe the standard binary arithmetic forms used by integer and floating-point vector instructions. They cover vector-vector, vector-scalar, vector-immediate, and floating-point vector-scalar forms.

##### Instruction Formats

```asm
vop.vv   vd, vs2, vs1, vm
vop.vx   vd, vs2, rs1, vm
vop.vi   vd, vs2, imm, vm
vfop.vv  vd, vs2, vs1, vm
vfop.vf  vd, vs2, fs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for vector-vector forms |
| `rs1` | Integer scalar source register for integer vector-scalar forms |
| `fs1` | Floating-point scalar source register for floating-point vector-scalar forms |
| `imm` | Immediate operand for integer vector-immediate forms |
| `vm` | Mask control, written in assembly as `v0.t` or omitted |

##### Semantics

1. `vs2` is the first source operand in both the encoding and the arithmetic meaning of the operation.
2. Integer vector-scalar forms read the scalar source from a GPR; floating-point vector-scalar forms read the scalar source from an FPR in the standard RVV model.
3. In assembly syntax, masking is expressed by appending `, v0.t`; an unmasked instruction omits the mask operand.

##### Assembly Examples

```asm
vadd.vv  v8,  v9,  v10, v0.t
vxor.vi  v11, v12, 7
vfmul.vf v13, v14, fa0
vfsub.vv v15, v16, v17, v0.t
```

- `vadd.vv v8, v9, v10, v0.t`: masked integer vector-vector add.
- `vxor.vi v11, v12, 7`: unmasked integer vector-immediate XOR with immediate `7`.
- `vfmul.vf v13, v14, fa0`: unmasked floating-point vector-scalar multiply using scalar `fa0`.
- `vfsub.vv v15, v16, v17, v0.t`: masked floating-point vector-vector subtract.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vadd_vv_i32m1(a, b, vl);
vint32m1_t r2 = __riscv_vxor_vx_i32m1(a, 7, vl);
vfloat32m1_t r3 = __riscv_vfmul_vf_f32m1(fa, 2.0f, vl);
```

##### Notes

1. Direct `vv`, `vx`, and `vf` intrinsic forms are available.
2. No separate `.vi` intrinsic is provided here; `vi` remains an assembly encoding form.
3. The original `vm=0` / `vm=1` style should not be used in assembly examples; use `v0.t` or omit the mask operand.

### 3.2 Widening Vector Arithmetic Instructions

#### 3.2.1 `vwop.vv` / `vwop.vx` / `vwop.wv` / `vwop.wx`

##### Function

These templates describe widening arithmetic instructions whose destination register group is double width. Integer widening operations use the `vw*` prefix, and floating-point widening operations use the `vfw*` prefix.

##### Instruction Formats

```asm
vwop.vv  vd, vs2, vs1, vm
vwop.vx  vd, vs2, rs1, vm
vwop.wv  vd, vs2, vs1, vm
vwop.wx  vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with double-width elements |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for vector-vector forms |
| `rs1` | Scalar source register for vector-scalar forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. The destination has `EEW = 2 * SEW` and `EMUL = 2 * LMUL`.
2. `.vv` and `.vx` forms use two narrow sources and produce a double-width result.
3. `.wv` and `.wx` forms use a double-width `vs2` source and a narrow `vs1` or `rs1` source.

##### Assembly Examples

```asm
vwadd.vv  v16, v18, v20
vwaddu.wx v22, v24, a2
```

- `vwadd.vv v16, v18, v20`: signed widening add from two narrow vector sources to a double-width destination.
- `vwaddu.wx v22, v24, a2`: unsigned widening add with double-width `vs2` and narrow scalar `a2`.

##### Intrinsics

Common intrinsic forms:

```c
vuint64m2_t r4 = __riscv_vwaddu_vv_u64m2(ua, ua, vl);
vuint64m2_t r5 = __riscv_vwaddu_wx_u64m2(wideu, 3, vl);
```

##### Notes

1. The `.wv` and `.wx` suffixes indicate that `vs2` is already double width.
2. Widening instruction encodings follow the vector operand overlap constraints of RVV.
3. Concrete opcodes later in this document use the `vw*` or `vfw*` prefixes rather than the generic `vwop` placeholder.

### 3.3 Narrowing Vector Arithmetic Instructions

#### 3.3.1 `vnop.wv` / `vnop.wx`

##### Function

These templates describe narrowing arithmetic instructions that consume a double-width `vs2` source and produce a single-width destination. Integer narrowing operations use the `vn*` prefix, and floating-point narrowing operations use the `vfn*` prefix.

##### Instruction Formats

```asm
vnop.wv  vd, vs2, vs1, vm
vnop.wx  vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with the current `SEW/LMUL` width |
| `vs2` | Double-width source vector register group |
| `vs1` | Narrow vector source register group for `.wv` forms |
| `rs1` | Narrow scalar source register for `.wx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vs2` has `EEW = 2 * SEW` and provides the wide source operand.
2. `vd` and `vs1` use the current narrower `SEW/LMUL` interpretation.
3. The `w` in the suffix marks the double-width source operand rather than the destination.

##### Assembly Examples

```asm
vnsra.wx v12, v14, a3, v0.t
```

- `vnsra.wx v12, v14, a3, v0.t`: masked narrowing arithmetic right shift using wide source `v14` and scalar shift amount `a3`.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r6 = __riscv_vnsrl_wx_u32m1(wideu, 3, vl);
vint32m1_t r7 = __riscv_vnsra_wx_i32m1(wide, -1, vl);
```

##### Notes

1. Specific narrowing instruction families may also define immediate forms, such as `vnsrl.wi` and `vnsra.wi`.
2. The `vn*` prefix names a narrowing family; concrete instruction semantics are defined in later chapters.
3. Narrowing instructions follow the RVV operand overlap constraints and should be documented with the width relationship made explicit.

## 4. Vector Integer Arithmetic Instructions

### 4.1 Vector Single-Width Integer Add and Subtract

#### 4.1.1 `vadd.vv` / `vadd.vx` / `vadd.vi`

##### Function

These instructions perform single-width integer addition. Unless otherwise stated, integer arithmetic wraps on overflow in RVV integer arithmetic.

##### Instruction Formats

```asm
vadd.vv vd, vs2, vs1, vm
vadd.vx vd, vs2, rs1, vm
vadd.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed immediate operand for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vadd.vv` computes `vd[i] = vs2[i] + vs1[i]`.
2. `vadd.vx` computes `vd[i] = vs2[i] + x[rs1]`.
3. `vadd.vi` computes `vd[i] = vs2[i] + imm`.

##### Assembly Examples

```asm
vadd.vv v8,  v9,  v10, v0.t
vadd.vx v11, v12, a1
vadd.vi v13, v14, 10
```

- `vadd.vv v8, v9, v10, v0.t`: masked vector-vector integer add.
- `vadd.vx v11, v12, a1`: unmasked vector-scalar integer add using `a1`.
- `vadd.vi v13, v14, 10`: unmasked vector-immediate integer add using immediate `10`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vadd_vv_i32m1(a, b, vl);
```

##### Notes

1. Direct `vv` intrinsic forms are available.
2. `vadd.vi` is a real assembly form, but no direct `.vi` intrinsic name was relied on here.
3. The mask operand in assembly is `v0.t`, not a textual `vm=0` / `vm=1` flag.

#### 4.1.2 `vsub.vv` / `vsub.vx`

##### Function

These instructions perform single-width integer subtraction.

##### Instruction Formats

```asm
vsub.vv vd, vs2, vs1, vm
vsub.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Minuend vector source |
| `vs1` | Subtrahend vector source for `.vv` forms |
| `rs1` | Scalar subtrahend for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsub.vv` computes `vd[i] = vs2[i] - vs1[i]`.
2. `vsub.vx` computes `vd[i] = vs2[i] - x[rs1]`.
3. Overflow wraps in the integer domain.

##### Assembly Examples

```asm
vsub.vv v15, v16, v17, v0.t
vsub.vx v18, v19, a2
```

- `vsub.vv v15, v16, v17, v0.t`: masked vector-vector integer subtract.
- `vsub.vx v18, v19, a2`: unmasked vector-scalar integer subtract.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r2 = __riscv_vsub_vx_i32m1(a, 3, vl);
```

##### Notes

1. `vs2` is the minuend; `vs1` or `rs1` is the subtrahend.
2. Only `.vv` and `.vx` forms exist for `vsub`.
3. Masking uses `v0.t` when present.

#### 4.1.3 `vrsub.vx` / `vrsub.vi`

##### Function

These instructions perform reverse subtraction, where the scalar or immediate operand is the minuend and the vector operand is the subtrahend.

##### Instruction Formats

```asm
vrsub.vx vd, vs2, rs1, vm
vrsub.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Vector subtrahend |
| `rs1` | Scalar minuend for `.vx` forms |
| `imm` | Immediate minuend for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vrsub.vx` computes `vd[i] = x[rs1] - vs2[i]`.
2. `vrsub.vi` computes `vd[i] = imm - vs2[i]`.
3. The vector operand is the value being subtracted from the scalar or immediate source.

##### Assembly Examples

```asm
vrsub.vx v20, v21, a3
vrsub.vi v22, v23, 5
```

- `vrsub.vx v20, v21, a3`: reverse subtract with scalar minuend `a3`.
- `vrsub.vi v22, v23, 5`: reverse subtract with immediate minuend `5`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r3 = __riscv_vrsub_vx_i32m1(a, 5, vl);
```

##### Notes

1. `vrsub` is not the same operand order as `vsub`; the scalar or immediate source comes first semantically.
2. `vrsub.vi` is a real assembly form.
3. This family is commonly used for negation-style transforms with `x0` or small immediates.

### 4.2 Vector Widening Integer Add/Subtract

#### 4.2.1 `vwadd.vv` / `vwaddu.vv` / `vwadd.vx` / `vwaddu.vx` / `vwsub.vv` / `vwsubu.vv` / `vwsub.vx` / `vwsubu.vx`

##### Function

These instructions perform widening integer add or subtract from two narrow sources and produce a double-width destination.

##### Instruction Formats

```asm
vwadd.vv  vd, vs2, vs1, vm
vwaddu.vx vd, vs2, rs1, vm
vwsub.vv  vd, vs2, vs1, vm
vwsubu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with double-width elements |
| `vs2` | First narrow source vector register group |
| `vs1` | Second narrow source vector register group for `.vv` forms |
| `rs1` | Narrow scalar source for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. The destination has width `2 * SEW`.
2. Signed families (`vwadd`, `vwsub`) sign-extend the narrow sources before the operation.
3. Unsigned families (`vwaddu`, `vwsubu`) zero-extend the narrow sources before the operation.

##### Assembly Examples

```asm
vwadd.vv  v8,  v10, v12
vwaddu.vx v14, v16, a4
vwsubu.vv v18, v20, v22
```

- `vwadd.vv v8, v10, v12`: signed widening add from two narrow vector sources.
- `vwaddu.vx v14, v16, a4`: unsigned widening add from a narrow vector and a narrow scalar.
- `vwsubu.vv v18, v20, v22`: unsigned widening subtract from two narrow vector sources.

##### Intrinsics

Common intrinsic forms:

```c
vuint64m2_t r4 = __riscv_vwaddu_vv_u64m2(ua, ua, vl);
```

##### Notes

1. These forms take narrow sources and produce wide results directly.
2. The signedness marker `u` controls extension behavior before the arithmetic.
3. Concrete destination and source types must satisfy RVV widening operand constraints.

#### 4.2.2 `vwadd.wv` / `vwaddu.wv` / `vwadd.wx` / `vwaddu.wx` / `vwsub.wv` / `vwsubu.wv` / `vwsub.wx` / `vwsubu.wx`

##### Function

These instructions perform widening add or subtract where `vs2` is already double width and the second source remains narrow.

##### Instruction Formats

```asm
vwadd.wv  vd, vs2, vs1, vm
vwaddu.wx vd, vs2, rs1, vm
vwsub.wv  vd, vs2, vs1, vm
vwsubu.wx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with double-width elements |
| `vs2` | Double-width source vector register group |
| `vs1` | Narrow vector source for `.wv` forms |
| `rs1` | Narrow scalar source for `.wx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vs2` already uses the double-width interpretation.
2. `vs1` or `rs1` remains narrow and is extended according to the signed or unsigned opcode family.
3. The result remains double width.

##### Assembly Examples

```asm
vwadd.wv  v24, v26, v28
vwaddu.wx v2,  v4,  a5
vwsub.wv  v6,  v8,  v10
```

- `vwadd.wv v24, v26, v28`: signed widening add with wide `vs2` and narrow `vs1`.
- `vwaddu.wx v2, v4, a5`: unsigned widening add with wide `vs2` and narrow scalar `a5`.
- `vwsub.wv v6, v8, v10`: signed widening subtract with wide `vs2` and narrow `vs1`.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t r5 = __riscv_vwadd_wx_i64m2(wa, 7, vl);
```

##### Notes

1. The `w` in `.wv` and `.wx` marks the wide `vs2` source.
2. These forms are different from the narrow-source `.vv` and `.vx` widening forms.
3. Source and destination overlap constraints follow the RVV widening operand rules.

### 4.3 Vector Integer Extension

#### 4.3.1 `vzext.vf<nf>` / `vsext.vf<nf>`

##### Function

These instructions zero-extend or sign-extend smaller integer elements into the current `SEW` destination width.

##### Instruction Formats

```asm
vzext.vf2 vd, vs2, vm
vsext.vf4 vd, vs2, vm
vzext.vf8 vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with width `SEW` |
| `vs2` | Source vector register group with narrower element width |
| `vm` | Mask control, written as `v0.t` or omitted |
| `<nf>` | Source width factor: `vf2`, `vf4`, and `vf8` mean source `EEW = SEW/2`, `SEW/4`, and `SEW/8` respectively |

##### Semantics

1. `vzext` zero-extends the narrow source elements into `SEW`-wide destination elements.
2. `vsext` sign-extends the narrow source elements into `SEW`-wide destination elements.
3. The source EMUL is `(EEW / SEW) * LMUL`, so the source vector type is usually smaller than the destination LMUL type.

##### Assembly Examples

```asm
vzext.vf2 v12, v14
vsext.vf4 v16, v18, v0.t
```

- `vzext.vf2 v12, v14`: zero-extend `SEW/2` source elements into `SEW` destination elements.
- `vsext.vf4 v16, v18, v0.t`: masked sign-extension from `SEW/4` source elements into `SEW` destination elements.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r6 = __riscv_vzext_vf2_u32m1(u16, vl);   // u16 has type vuint16mf2_t
vint32m1_t  r7 = __riscv_vsext_vf4_i32m1(i8, vl);    // i8 has type vint8mf4_t
```

##### Notes

1. `<nf>` is not an arbitrary multiplier; it names how much narrower the source is than the destination.
2. The source vector type must satisfy the reduced EMUL implied by the source width.
3. If the implied source `EEW` or EMUL is illegal for the implementation, the encoding is reserved.

### 4.4 Vector Integer Add-with-Carry / Subtract-with-Borrow Instructions

#### 4.4.1 `vadc.vvm` / `vadc.vxm` / `vadc.vim` / `vsbc.vvm` / `vsbc.vxm`

##### Function

These instructions perform integer addition with carry-in or subtraction with borrow-in and write the arithmetic result to a vector destination.

##### Instruction Formats

```asm
vadc.vvm vd, vs2, vs1, v0
vadc.vxm vd, vs2, rs1, v0
vadc.vim vd, vs2, imm, v0
vsbc.vvm vd, vs2, vs1, v0
vsbc.vxm vd, vs2, rs1, v0
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group for the arithmetic result |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vvm` forms |
| `rs1` | Scalar source register for `.vxm` forms |
| `imm` | Immediate operand for `vadc.vim` |
| `v0` | Carry-in or borrow-in mask source, taken element-wise from mask register `v0` |

##### Semantics

1. `vadc` adds the carry-in bit from `v0` to the arithmetic sum.
2. `vsbc` subtracts the borrow-in bit from `v0` from the arithmetic difference.
3. These forms consume `v0` as a carry/borrow input operand; it is not written as `v0.t`.

##### Assembly Examples

```asm
vadc.vvm v20, v22, v24, v0
vadc.vxm v26, v28, a6,  v0
vadc.vim v2,  v4,  1,   v0
vsbc.vvm v6,  v8,  v10, v0
vsbc.vxm v12, v14, a7,  v0
```

- `vadc.vvm v20, v22, v24, v0`: vector-vector add with carry-in from `v0`.
- `vadc.vxm v26, v28, a6, v0`: vector-scalar add with carry-in from `v0`.
- `vadc.vim v2, v4, 1, v0`: vector-immediate add with carry-in from `v0`.
- `vsbc.vvm v6, v8, v10, v0`: vector-vector subtract with borrow-in from `v0`.
- `vsbc.vxm v12, v14, a7, v0`: vector-scalar subtract with borrow-in from `v0`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r8 = __riscv_vadc_vvm_i32m1(a, b, m32, vl);
vint32m1_t r9 = __riscv_vsbc_vxm_i32m1(a, 9, m32, vl);
```

##### Notes

1. The carry/borrow input is element-wise from mask register `v0`, not a single global bit.
2. These forms produce ordinary vector arithmetic results, not mask results.
3. In assembly, the trailing operand is `v0`, not `v0.t`.

#### 4.4.2 `vmadc.vvm` / `vmadc.vxm` / `vmadc.vim` / `vmsbc.vvm` / `vmsbc.vxm`

##### Function

These instructions compute carry-out or borrow-out results while also taking a carry-in or borrow-in from `v0`. The result is written as a mask value rather than an integer vector payload.

##### Instruction Formats

```asm
vmadc.vvm vd, vs2, vs1, v0
vmadc.vxm vd, vs2, rs1, v0
vmadc.vim vd, vs2, imm, v0
vmsbc.vvm vd, vs2, vs1, v0
vmsbc.vxm vd, vs2, rs1, v0
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vvm` forms |
| `rs1` | Scalar source register for `.vxm` forms |
| `imm` | Immediate operand for `vmadc.vim` |
| `v0` | Carry-in or borrow-in mask source |

##### Semantics

1. `vmadc` writes a mask bit indicating whether the addition produced a carry-out.
2. `vmsbc` writes a mask bit indicating whether the subtraction produced a borrow-out.
3. These forms use `v0` as carry-in or borrow-in and produce a mask result in `vd`.

##### Assembly Examples

```asm
vmadc.vvm v0, v16, v18, v0
vmadc.vxm v0, v20, a1,  v0
vmadc.vim v0, v22, 1,   v0
vmsbc.vvm v0, v24, v26, v0
vmsbc.vxm v0, v28, a2,  v0
```

- `vmadc.vvm v0, v16, v18, v0`: carry-out mask from vector-vector add with carry-in.
- `vmadc.vxm v0, v20, a1, v0`: carry-out mask from vector-scalar add with carry-in.
- `vmadc.vim v0, v22, 1, v0`: carry-out mask from vector-immediate add with carry-in.
- `vmsbc.vvm v0, v24, v26, v0`: borrow-out mask from vector-vector subtract with borrow-in.
- `vmsbc.vxm v0, v28, a2, v0`: borrow-out mask from vector-scalar subtract with borrow-in.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r10 = __riscv_vmadc_vvm_i32m1_b32(a, b, m32, vl);
```

##### Notes

1. The destination is a mask result, not an integer payload vector.
2. The trailing `v0` operand is the carry-in or borrow-in source.
3. These instructions are useful for multi-precision arithmetic where both the arithmetic result and the carry chain are needed.

#### 4.4.3 `vmadc.vv` / `vmadc.vx` / `vmadc.vi` / `vmsbc.vv` / `vmsbc.vx`

##### Function

These instructions compute carry-out or borrow-out masks without taking a carry-in or borrow-in operand.

##### Instruction Formats

```asm
vmadc.vv vd, vs2, vs1
vmadc.vx vd, vs2, rs1
vmadc.vi vd, vs2, imm
vmsbc.vv vd, vs2, vs1
vmsbc.vx vd, vs2, rs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Immediate operand for `vmadc.vi` |

##### Semantics

1. `vmadc` writes a carry-out mask for addition without a carry-in operand.
2. `vmsbc` writes a borrow-out mask for subtraction without a borrow-in operand.
3. These forms do not take an additional trailing `v0` operand.

##### Assembly Examples

```asm
vmadc.vv v0, v8,  v10
vmadc.vx v0, v12, a3
vmadc.vi v0, v14, 7
vmsbc.vv v0, v16, v18
vmsbc.vx v0, v20, a4
```

- `vmadc.vv v0, v8, v10`: carry-out mask from vector-vector add without carry-in.
- `vmadc.vx v0, v12, a3`: carry-out mask from vector-scalar add without carry-in.
- `vmadc.vi v0, v14, 7`: carry-out mask from vector-immediate add without carry-in.
- `vmsbc.vv v0, v16, v18`: borrow-out mask from vector-vector subtract without borrow-in.
- `vmsbc.vx v0, v20, a4`: borrow-out mask from vector-scalar subtract without borrow-in.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r11 = __riscv_vmsbc_vx_i32m1_b32(a, 11, vl);
```

##### Notes

1. These forms do not take an extra `v0.t` mask operand.
2. These forms are distinct from the `.vvm` / `.vxm` / `.vim` carry-in families.
3. The result is always a mask value, suitable for carry-chain or borrow-chain processing.

### 4.5 Vector Bitwise Logical Instructions

#### 4.5.1 `vand.vv` / `vand.vx` / `vand.vi`

##### Function

These instructions perform bitwise AND on integer vector elements.

##### Instruction Formats

```asm
vand.vv vd, vs2, vs1, vm
vand.vx vd, vs2, rs1, vm
vand.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Immediate operand for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vand.vv` computes `vd[i] = vs2[i] & vs1[i]`.
2. `vand.vx` computes `vd[i] = vs2[i] & x[rs1]`.
3. `vand.vi` computes `vd[i] = vs2[i] & imm`.

##### Assembly Examples

```asm
vand.vv v8,  v9,  v10, v0.t
vand.vx v11, v12, a1
vand.vi v13, v14, 15
```

- `vand.vv v8, v9, v10, v0.t`: masked vector-vector bitwise AND.
- `vand.vx v11, v12, a1`: unmasked vector-scalar bitwise AND.
- `vand.vi v13, v14, 15`: unmasked vector-immediate bitwise AND.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vand_vv_i32m1(a, b, vl);
```

##### Notes

1. Direct `vv` intrinsic forms are available.
2. `vand.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Use `v0.t` for masking in assembly examples instead of pseudo `vm=0/1` notation.

#### 4.5.2 `vor.vv` / `vor.vx` / `vor.vi`

##### Function

These instructions perform bitwise OR on integer vector elements.

##### Instruction Formats

```asm
vor.vv vd, vs2, vs1, vm
vor.vx vd, vs2, rs1, vm
vor.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Immediate operand for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vor.vv` computes `vd[i] = vs2[i] | vs1[i]`.
2. `vor.vx` computes `vd[i] = vs2[i] | x[rs1]`.
3. `vor.vi` computes `vd[i] = vs2[i] | imm`.

##### Assembly Examples

```asm
vor.vv v15, v16, v17
vor.vx v18, v19, a2
vor.vi v20, v21, 3, v0.t
```

- `vor.vv v15, v16, v17`: unmasked vector-vector bitwise OR.
- `vor.vx v18, v19, a2`: unmasked vector-scalar bitwise OR.
- `vor.vi v20, v21, 3, v0.t`: masked vector-immediate bitwise OR.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r2 = __riscv_vor_vx_i32m1(a, 3, vl);
```

##### Notes

1. Direct `vx` intrinsic forms are available.
2. `vor.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Bitwise logical operations apply to integer bit patterns and do not distinguish signed from unsigned at the instruction semantics level.

#### 4.5.3 `vxor.vv` / `vxor.vx` / `vxor.vi`

##### Function

These instructions perform bitwise XOR on integer vector elements.

##### Instruction Formats

```asm
vxor.vv vd, vs2, vs1, vm
vxor.vx vd, vs2, rs1, vm
vxor.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Immediate operand for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vxor.vv` computes `vd[i] = vs2[i] ^ vs1[i]`.
2. `vxor.vx` computes `vd[i] = vs2[i] ^ x[rs1]`.
3. `vxor.vi` computes `vd[i] = vs2[i] ^ imm`.

##### Assembly Examples

```asm
vxor.vv v22, v23, v24
vxor.vx v25, v26, a3
vxor.vi v27, v28, 7
```

- `vxor.vv v22, v23, v24`: unmasked vector-vector bitwise XOR.
- `vxor.vx v25, v26, a3`: unmasked vector-scalar bitwise XOR.
- `vxor.vi v27, v28, 7`: unmasked vector-immediate bitwise XOR.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r3 = __riscv_vxor_vx_i32m1(a, 7, vl);
```

##### Notes

1. Direct `vx` intrinsic forms are available.
2. `vxor.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. XOR is often used for bit flips, toggles, and mask manipulations.

### 4.6 Vector Single-Width Shift Instructions

#### 4.6.1 `vsll.vv` / `vsll.vx` / `vsll.vi`

##### Function

These instructions perform logical left shift on single-width integer vector elements.

##### Instruction Formats

```asm
vsll.vv vd, vs2, vs1, vm
vsll.vx vd, vs2, rs1, vm
vsll.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group containing the values to be shifted |
| `vs1` | Vector shift-count source for `.vv` forms |
| `rs1` | Scalar shift-count source for `.vx` forms |
| `uimm` | Unsigned immediate shift count for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsll.vv` computes `vd[i] = vs2[i] << shift[i]`.
2. `vsll.vx` and `vsll.vi` use a scalar or immediate shift count for every active element.
3. Only the low `lg2(SEW)` bits of the shift count are used.

##### Assembly Examples

```asm
vsll.vv v8,  v10, v12
vsll.vx v14, v16, a4
vsll.vi v18, v20, 3
```

- `vsll.vv v8, v10, v12`: vector-vector logical left shift.
- `vsll.vx v14, v16, a4`: vector-scalar logical left shift.
- `vsll.vi v18, v20, 3`: vector-immediate logical left shift by `3`.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r4 = __riscv_vsll_vx_u32m1(ua, 2, vl);
```

##### Notes

1. Direct `vx` intrinsic forms are available.
2. `vsll.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Shift counts are masked by the destination element width.

#### 4.6.2 `vsrl.vv` / `vsrl.vx` / `vsrl.vi`

##### Function

These instructions perform logical right shift on single-width integer vector elements.

##### Instruction Formats

```asm
vsrl.vv vd, vs2, vs1, vm
vsrl.vx vd, vs2, rs1, vm
vsrl.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group containing the values to be shifted |
| `vs1` | Vector shift-count source for `.vv` forms |
| `rs1` | Scalar shift-count source for `.vx` forms |
| `uimm` | Unsigned immediate shift count for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsrl.vv` computes a logical right shift using vector shift counts.
2. `vsrl.vx` and `vsrl.vi` compute logical right shift using a scalar or immediate count.
3. Only the low `lg2(SEW)` bits of the shift count are used.

##### Assembly Examples

```asm
vsrl.vv v22, v24, v26, v0.t
vsrl.vx v28, v30, a5
vsrl.vi v2,  v4,  4
```

- `vsrl.vv v22, v24, v26, v0.t`: masked vector-vector logical right shift.
- `vsrl.vx v28, v30, a5`: unmasked vector-scalar logical right shift.
- `vsrl.vi v2, v4, 4`: unmasked vector-immediate logical right shift.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r5 = __riscv_vsrl_vv_u32m1(ua, ua, vl);
```

##### Notes

1. Direct `vv` intrinsic forms are available.
2. `vsrl.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Logical right shift zero-fills from the left.

#### 4.6.3 `vsra.vv` / `vsra.vx` / `vsra.vi`

##### Function

These instructions perform arithmetic right shift on signed integer vector elements.

##### Instruction Formats

```asm
vsra.vv vd, vs2, vs1, vm
vsra.vx vd, vs2, rs1, vm
vsra.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group containing signed values to be shifted |
| `vs1` | Vector shift-count source for `.vv` forms |
| `rs1` | Scalar shift-count source for `.vx` forms |
| `uimm` | Unsigned immediate shift count for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsra.vv` computes arithmetic right shift using vector shift counts.
2. `vsra.vx` and `vsra.vi` compute arithmetic right shift using a scalar or immediate count.
3. Only the low `lg2(SEW)` bits of the shift count are used, and sign bits are propagated.

##### Assembly Examples

```asm
vsra.vv v6,  v8,  v10
vsra.vx v12, v14, a6, v0.t
vsra.vi v16, v18, 2
```

- `vsra.vv v6, v8, v10`: unmasked vector-vector arithmetic right shift.
- `vsra.vx v12, v14, a6, v0.t`: masked vector-scalar arithmetic right shift.
- `vsra.vi v16, v18, 2`: unmasked vector-immediate arithmetic right shift.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r6 = __riscv_vsra_vx_i32m1(a, 1, vl);
```

##### Notes

1. Arithmetic right shift preserves the sign for signed operands.
2. `vsra.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Shift counts are masked by the destination element width.

### 4.7 Vector Narrowing Integer Right Shift Instructions

#### 4.7.1 `vnsrl.wv` / `vnsrl.wx` / `vnsrl.wi`

##### Function

These instructions perform logical right shift on a double-width source and narrow the result to the current `SEW` destination width.

##### Instruction Formats

```asm
vnsrl.wv vd, vs2, vs1, vm
vnsrl.wx vd, vs2, rs1, vm
vnsrl.wi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with width `SEW` |
| `vs2` | Wide source vector register group with width `2 * SEW` |
| `vs1` | Narrow vector shift-count source for `.wv` forms |
| `rs1` | Scalar shift-count source for `.wx` forms |
| `uimm` | Unsigned immediate shift count for `.wi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vnsrl` shifts the wide source right logically and narrows the result to `SEW`.
2. `vs2` is the wide source operand; the destination is the current narrower width.
3. Only the low `lg2(2 * SEW)` bits of the shift count are used.

##### Assembly Examples

```asm
vnsrl.wv v20, v22, v24
vnsrl.wx v26, v28, a7
vnsrl.wi v2,  v4,  5, v0.t
```

- `vnsrl.wv v20, v22, v24`: unmasked narrowing logical right shift with vector shift counts.
- `vnsrl.wx v26, v28, a7`: unmasked narrowing logical right shift with scalar shift count.
- `vnsrl.wi v2, v4, 5, v0.t`: masked narrowing logical right shift with immediate count `5`.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r7 = __riscv_vnsrl_wx_u32m1(uwa, 5, vl);
```

##### Notes

1. Direct `wx` intrinsic forms are available.
2. `vnsrl.wi` is an assembly form. No separate `.wi` intrinsic is provided here.
3. The source is wide and the result is narrow; this is the defining width relation of the family.

#### 4.7.2 `vnsra.wv` / `vnsra.wx` / `vnsra.wi`

##### Function

These instructions perform arithmetic right shift on a double-width signed source and narrow the result to the current `SEW` destination width.

##### Instruction Formats

```asm
vnsra.wv vd, vs2, vs1, vm
vnsra.wx vd, vs2, rs1, vm
vnsra.wi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with width `SEW` |
| `vs2` | Wide signed source vector register group with width `2 * SEW` |
| `vs1` | Narrow vector shift-count source for `.wv` forms |
| `rs1` | Scalar shift-count source for `.wx` forms |
| `uimm` | Unsigned immediate shift count for `.wi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vnsra` shifts the wide signed source right arithmetically and narrows the result to `SEW`.
2. `vs2` is the wide source operand; the destination is the current narrower width.
3. Only the low `lg2(2 * SEW)` bits of the shift count are used, and sign bits are propagated before narrowing.

##### Assembly Examples

```asm
vnsra.wv v6,  v8,  v10
vnsra.wx v12, v14, s0
vnsra.wi v16, v18, 1
```

- `vnsra.wv v6, v8, v10`: unmasked narrowing arithmetic right shift with vector shift counts.
- `vnsra.wx v12, v14, s0`: unmasked narrowing arithmetic right shift with scalar shift count.
- `vnsra.wi v16, v18, 1`: unmasked narrowing arithmetic right shift with immediate count `1`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r8 = __riscv_vnsra_wx_i32m1(iwa, 1, vl);
```

##### Notes

1. Direct `wx` intrinsic forms are available.
2. `vnsra.wi` is an assembly form. No separate `.wi` intrinsic is provided here.
3. Arithmetic narrowing right shift is the signed counterpart to `vnsrl`.

### 4.8 Vector Integer Compare Instructions

#### 4.8.1 `vmseq.vv` / `vmseq.vx` / `vmseq.vi`

##### Function

These instructions compare integer operands for equality and write the result to a mask register.

##### Instruction Formats

```asm
vmseq.vv vd, vs2, vs1, vm
vmseq.vx vd, vs2, rs1, vm
vmseq.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed 5-bit immediate for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. The result is a mask value: destination bit `i` is `1` when the comparison is true, otherwise `0`.
2. `vmseq.vv`, `vmseq.vx`, and `vmseq.vi` compare for equality.
3. Compare instructions write a mask register rather than a full-width integer payload vector.

##### Assembly Examples

```asm
vmseq.vv v0, v8,  v10
vmseq.vx v0, v12, a1, v0.t
vmseq.vi v0, v14, 0
```

- `vmseq.vv v0, v8, v10`: unmasked vector-vector equality compare.
- `vmseq.vx v0, v12, a1, v0.t`: masked vector-scalar equality compare.
- `vmseq.vi v0, v14, 0`: unmasked vector-immediate equality compare with immediate `0`.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c1 = __riscv_vmseq_vv_i32m1_b32(a, b, vl);
```

##### Notes

1. The destination mask is always held in a single vector register.
2. `vmseq.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
3. Compare-immediate forms use the signed 5-bit immediate range `-16..15`.

#### 4.8.2 `vmsne.vv` / `vmsne.vx` / `vmsne.vi`

##### Function

These instructions compare integer operands for inequality and write the result to a mask register.

##### Instruction Formats

```asm
vmsne.vv vd, vs2, vs1, vm
vmsne.vx vd, vs2, rs1, vm
vmsne.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed 5-bit immediate for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. The result bit is `1` when the two operands are not equal.
2. `vmsne.vv`, `vmsne.vx`, and `vmsne.vi` produce mask results.
3. The destination mask register may be the same physical register as `v0`.

##### Assembly Examples

```asm
vmsne.vv v0, v16, v18
vmsne.vx v0, v20, a2
vmsne.vi v0, v22, 10, v0.t
```

- `vmsne.vv v0, v16, v18`: unmasked vector-vector inequality compare.
- `vmsne.vx v0, v20, a2`: unmasked vector-scalar inequality compare.
- `vmsne.vi v0, v22, 10, v0.t`: masked vector-immediate inequality compare.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c2 = __riscv_vmsne_vx_i32m1_b32(a, 10, vl);
```

##### Notes

1. `vmsne.vi` is an assembly form. No separate `.vi` intrinsic is provided here.
2. Compare immediates use the signed 5-bit immediate field.
3. As with other compare instructions, the result is a mask register.

#### 4.8.3 `vmslt.vv` / `vmsltu.vv` / `vmslt.vx` / `vmsltu.vx`

##### Function

These instructions compare integer operands for less-than and write the result to a mask register.

##### Instruction Formats

```asm
vmslt.vv  vd, vs2, vs1, vm
vmslt.vx  vd, vs2, rs1, vm
vmsltu.vv vd, vs2, vs1, vm
vmsltu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmslt*` compares `vs2` against `vs1` or `rs1` for strictly less-than.
2. Signed forms use signed comparison; unsigned forms use unsigned comparison.
3. The result is written as a mask value.

##### Assembly Examples

```asm
vmslt.vv  v0, v24, v26
vmsltu.vx v0, v28, a3
```

- `vmslt.vv v0, v24, v26`: signed vector-vector less-than compare.
- `vmsltu.vx v0, v28, a3`: unsigned vector-scalar less-than compare.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c3 = __riscv_vmslt_vv_i32m1_b32(a, b, vl);
```

##### Notes

1. Immediate forms of `vmslt{u}.vi` are not directly provided in native machine code.
2. The assembler can express some `< immediate` cases through `vmsle{u}.vi` with an adjusted immediate.
3. The signedness marker `u` selects unsigned comparison semantics.

#### 4.8.4 `vmsle.vv` / `vmsleu.vv` / `vmsle.vx` / `vmsleu.vx` / `vmsle.vi` / `vmsleu.vi`

##### Function

These instructions compare integer operands for less-than-or-equal and write the result to a mask register.

##### Instruction Formats

```asm
vmsle.vv  vd, vs2, vs1, vm
vmsle.vx  vd, vs2, rs1, vm
vmsle.vi  vd, vs2, imm, vm
vmsleu.vv vd, vs2, vs1, vm
vmsleu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed 5-bit immediate for `vmsle.vi`; unsigned immediate behavior for `vmsleu.vi` is encoded through the same sign-extended field |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmsle*` compares `vs2` against `vs1`, `rs1`, or the immediate for less-than-or-equal.
2. Signed and unsigned families differ only in the comparison interpretation.
3. The result is written as a mask value.

##### Assembly Examples

```asm
vmsle.vx  v0, v8,  a4
vmsle.vi  v0, v10, 0
vmsleu.vx v0, v12, a5, v0.t
```

- `vmsle.vx v0, v8, a4`: signed vector-scalar less-than-or-equal compare.
- `vmsle.vi v0, v10, 0`: signed vector-immediate less-than-or-equal compare.
- `vmsleu.vx v0, v12, a5, v0.t`: masked unsigned vector-scalar less-than-or-equal compare.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c4 = __riscv_vmsle_vx_i32m1_b32(a, 0, vl);
```

##### Notes

1. Direct `vx` intrinsic forms are available.
2. No separate `.vi` intrinsic is provided here for this family.
3. Compare-immediate forms use the signed 5-bit immediate field range.

#### 4.8.5 `vmsgt.vx` / `vmsgtu.vx` / `vmsgt.vi` / `vmsgtu.vi`

##### Function

These forms compare integer operands for greater-than against a scalar register or immediate and write the result to a mask register.

##### Instruction Formats

```asm
vmsgt.vx  vd, vs2, rs1, vm
vmsgt.vi  vd, vs2, imm, vm
vmsgtu.vx vd, vs2, rs1, vm
vmsgtu.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Source vector register group |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed 5-bit immediate for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmsgt*` compares whether `vs2` is greater than the scalar or immediate operand.
2. Signed and unsigned families differ only in the comparison interpretation.
3. These scalar and immediate greater-than forms are provided directly because they avoid extra mask logic for polarity reversal.

##### Assembly Examples

```asm
vmsgt.vx  v0, v14, a6
vmsgt.vi  v0, v16, 10
vmsgtu.vx v0, v18, a7
vmsgtu.vi v0, v20, 15
```

- `vmsgt.vx v0, v14, a6`: signed vector-scalar greater-than compare.
- `vmsgt.vi v0, v16, 10`: signed vector-immediate greater-than compare.
- `vmsgtu.vx v0, v18, a7`: unsigned vector-scalar greater-than compare.
- `vmsgtu.vi v0, v20, 15`: unsigned vector-immediate greater-than compare.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c5 = __riscv_vmsgt_vx_i32m1_b32(a, 5, vl);
```

##### Notes

1. Vector-vector greater-than is normally expressed through assembler pseudoinstructions that swap operands of `vmslt{u}.vv`.
2. No separate `.vi` intrinsic is provided here for this family.
3. The assembler enforces the signed 5-bit immediate field range for `.vi` forms.

#### 4.8.6 `vmsge.vx` / `vmsgeu.vx`

##### Function

These assembler forms express greater-than-or-equal comparison against a scalar register and write the result to a mask register.

##### Instruction Formats

```asm
vmsge.vx  vd, vs2, rs1, vm
vmsgeu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Source vector register group |
| `rs1` | Scalar source register |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmsge*` compares whether `vs2` is greater than or equal to the scalar operand.
2. In RVV 1.0, `vmsge{u}.vx` is not directly provided as native machine code.
3. This comparison can be synthesized through equivalent native comparisons.

##### Assembly Examples

```asm
vmsge.vx  v0, v22, s0
vmsgeu.vx v0, v24, s1
```

- `vmsge.vx v0, v22, s0`: signed vector-scalar greater-than-or-equal compare.
- `vmsgeu.vx v0, v24, s1`: unsigned vector-scalar greater-than-or-equal compare.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t c6 = __riscv_vmsge_vx_i32m1_b32(a, 5, vl);
```

##### Notes

1. Although assemblers may accept `vmsge{u}.vx`, the official RVV 1.0 spec treats these as synthesized forms, not native instructions.
2. Vector-vector `>=` comparisons are likewise usually expressed through operand-swapped `vmsle{u}.vv` forms.
3. This distinction matters if the document is used for low-level encoding lookup.

### 4.9 Vector Integer Min/Max Instructions

#### 4.9.1 `vmin.vv` / `vminu.vv` / `vmin.vx` / `vminu.vx`

##### Function

These instructions select the minimum of two integer operands element-wise.

##### Instruction Formats

```asm
vmin.vv  vd, vs2, vs1, vm
vmin.vx  vd, vs2, rs1, vm
vminu.vv vd, vs2, vs1, vm
vminu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmin*` selects the smaller value for each active element.
2. Signed forms use signed ordering; unsigned forms use unsigned ordering.
3. The result is written as an integer payload vector, not a mask.

##### Assembly Examples

```asm
vmin.vv  v8,  v9,  v10, v0.t
vminu.vx v11, v12, a1
```

- `vmin.vv v8, v9, v10, v0.t`: masked signed vector-vector minimum.
- `vminu.vx v11, v12, a1`: unmasked unsigned vector-scalar minimum.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vmin_vv_i32m1(a, b, vl);
```

##### Notes

1. `vmin` and `vminu` differ only in the comparison interpretation.
2. There is no immediate form in this family.
3. Min/max produce full-width element results, unlike compare instructions.

#### 4.9.2 `vmax.vv` / `vmaxu.vv` / `vmax.vx` / `vmaxu.vx`

##### Function

These instructions select the maximum of two integer operands element-wise.

##### Instruction Formats

```asm
vmax.vv  vd, vs2, vs1, vm
vmax.vx  vd, vs2, rs1, vm
vmaxu.vv vd, vs2, vs1, vm
vmaxu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmax*` selects the larger value for each active element.
2. Signed forms use signed ordering; unsigned forms use unsigned ordering.
3. The result is written as an integer payload vector.

##### Assembly Examples

```asm
vmax.vx  v13, v14, a2
vmaxu.vv v15, v16, v17
```

- `vmax.vx v13, v14, a2`: signed vector-scalar maximum.
- `vmaxu.vv v15, v16, v17`: unsigned vector-vector maximum.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r2 = __riscv_vmaxu_vx_u32m1(ua, 7, vl);
```

##### Notes

1. `vmax` and `vmaxu` differ only in signed versus unsigned ordering.
2. There is no immediate form in this family.
3. Min/max are often a better fit than compare-plus-merge when the result is a data vector rather than a mask.

### 4.10 Vector Single-Width Integer Multiply Instructions

#### 4.10.1 `vmul.vv` / `vmul.vx`

##### Function

These instructions perform single-width integer multiplication and return the low half of the `2 * SEW` product.

##### Instruction Formats

```asm
vmul.vv vd, vs2, vs1, vm
vmul.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmul` computes a `2 * SEW` product and writes the low `SEW` bits to the destination.
2. There is only one `vmul` opcode family for the low-half product.
3. The low half of a two's-complement product is the same bit pattern regardless of signed or unsigned interpretation, which is why there is no separate `vmulu`.

##### Assembly Examples

```asm
vmul.vv v18, v19, v20
vmul.vx v21, v22, a3, v0.t
```

- `vmul.vv v18, v19, v20`: unmasked vector-vector low-half multiply.
- `vmul.vx v21, v22, a3, v0.t`: masked vector-scalar low-half multiply.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r3 = __riscv_vmul_vv_i32m1(a, b, vl);
```

##### Notes

1. Do not document separate signed and unsigned low-half multiply opcodes here; RVV uses a single `vmul`.
2. The signedness distinction matters only for the high-half multiply families.
3. The result is a normal integer payload vector.

#### 4.10.2 `vmulh.vv` / `vmulh.vx` / `vmulhu.vv` / `vmulhu.vx` / `vmulhsu.vv` / `vmulhsu.vx`

##### Function

These instructions perform single-width integer multiplication and return the high half of the `2 * SEW` product.

##### Instruction Formats

```asm
vmulh.vv   vd, vs2, vs1, vm
vmulh.vx   vd, vs2, rs1, vm
vmulhu.vv  vd, vs2, vs1, vm
vmulhu.vx  vd, vs2, rs1, vm
vmulhsu.vv vd, vs2, vs1, vm
vmulhsu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmulh` returns the high half of a signed × signed product.
2. `vmulhu` returns the high half of an unsigned × unsigned product.
3. `vmulhsu` returns the high half of a signed(`vs2`) × unsigned(`vs1` or `rs1`) product.

##### Assembly Examples

```asm
vmulh.vv   v24, v25, v26
vmulh.vx   v27, v28, a4
vmulhu.vv  v8,  v10, v12
vmulhu.vx  v14, v16, a5
vmulhsu.vv v18, v20, v22
vmulhsu.vx v24, v26, a6
```

- `vmulh.vv v24, v25, v26`: signed high-half vector-vector multiply.
- `vmulhu.vx v14, v16, a5`: unsigned high-half vector-scalar multiply.
- `vmulhsu.vv v18, v20, v22`: signed(`vs2`) × unsigned(`vs1`) high-half vector-vector multiply.
- `vmulhsu.vx v24, v26, a6`: signed(`vs2`) × unsigned(`rs1`) high-half vector-scalar multiply.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r4 = __riscv_vmulh_vx_i32m1(a, 3, vl);
vuint32m1_t r5 = __riscv_vmulhu_vv_u32m1(ua, ua, vl);
vint32m1_t  r6 = __riscv_vmulhsu_vx_i32m1(a, 9u, vl);
```

##### Notes

1. `vmulhsu` uses signed `vs2` and unsigned second operand semantics.
2. The official RVV 1.0 spec does not provide a `vmulhus.vx` opcode for the reversed signedness order.
3. When the opposite signedness order is needed, software can materialize the scalar as a vector and use another available form.

### 4.11 Vector Integer Divide Instructions

#### 4.11.1 `vdiv.vv` / `vdiv.vx` / `vdivu.vv` / `vdivu.vx`

##### Function

These instructions perform element-wise integer division and return the quotient.

##### Instruction Formats

```asm
vdiv.vv  vd, vs2, vs1, vm
vdiv.vx  vd, vs2, rs1, vm
vdivu.vv vd, vs2, vs1, vm
vdivu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Dividend vector register group |
| `vs1` | Divisor vector register group for `.vv` forms |
| `rs1` | Scalar divisor register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vdiv` performs signed division and truncates the quotient toward zero.
2. `vdivu` performs unsigned division.
3. `vs2` is the dividend, while `vs1` or `rs1` is the divisor.
4. Division-by-zero and signed-overflow corner cases follow the base RISC-V integer division rules.

##### Assembly Examples

```asm
vdiv.vv  v8,  v10, v12, v0.t
vdiv.vx  v14, v16, a1
vdivu.vv v18, v20, v22
vdivu.vx v24, v26, a2
```

- `vdiv.vv v8, v10, v12, v0.t`: masked signed vector-vector division.
- `vdiv.vx v14, v16, a1`: signed vector-scalar division.
- `vdivu.vv v18, v20, v22`: unsigned vector-vector division.
- `vdivu.vx v24, v26, a2`: unsigned vector-scalar division.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r1 = __riscv_vdiv_vv_i32m1(a, b, vl);
vuint32m1_t r2 = __riscv_vdivu_vx_u32m1(ua, 3, vl);
```

##### Notes

1. RVV uses separate signed and unsigned quotient instruction families.
2. The divisor is always the second operand in the assembly syntax.
3. Quotient behavior matches scalar integer division semantics rather than floating-point division rules.

#### 4.11.2 `vrem.vv` / `vrem.vx` / `vremu.vv` / `vremu.vx`

##### Function

These instructions perform element-wise integer remainder operations and return the remainder.

##### Instruction Formats

```asm
vrem.vv  vd, vs2, vs1, vm
vrem.vx  vd, vs2, rs1, vm
vremu.vv vd, vs2, vs1, vm
vremu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Dividend vector register group |
| `vs1` | Divisor vector register group for `.vv` forms |
| `rs1` | Scalar divisor register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vrem` performs signed remainder and keeps the scalar RISC-V signed remainder behavior.
2. `vremu` performs unsigned remainder.
3. `vs2` is the dividend, while `vs1` or `rs1` is the divisor.
4. Division-by-zero and signed-overflow corner cases follow the base RISC-V integer remainder rules.

##### Assembly Examples

```asm
vrem.vv  v28, v30, v8
vrem.vx  v10, v12, a3, v0.t
vremu.vv v14, v16, v18
vremu.vx v20, v22, a4
```

- `vrem.vv v28, v30, v8`: signed vector-vector remainder.
- `vrem.vx v10, v12, a3, v0.t`: masked signed vector-scalar remainder.
- `vremu.vv v14, v16, v18`: unsigned vector-vector remainder.
- `vremu.vx v20, v22, a4`: unsigned vector-scalar remainder.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r3 = __riscv_vrem_vx_i32m1(a, 5, vl);
vuint32m1_t r4 = __riscv_vremu_vv_u32m1(ua, ua, vl);
```

##### Notes

1. The remainder family follows the same operand order as the quotient family.
2. Signed remainder behavior is defined by integer arithmetic rules, not by language-specific `%` edge cases outside the ISA model.
3. Keep quotient and remainder documentation aligned because their exceptional cases are specified together in the ISA.

### 4.12 Vector Widening Integer Multiply Instructions

#### 4.12.1 `vwmul.vv` / `vwmul.vx` / `vwmulu.vv` / `vwmulu.vx`

##### Function

These instructions perform element-wise integer multiplication and return the full product in a destination with doubled element width.

##### Instruction Formats

```asm
vwmul.vv  vd, vs2, vs1, vm
vwmul.vx  vd, vs2, rs1, vm
vwmulu.vv vd, vs2, vs1, vm
vwmulu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with `EEW = 2 * SEW` |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vwmul` computes a signed × signed product and widens the result to `2 * SEW`.
2. `vwmulu` computes an unsigned × unsigned product and widens the result to `2 * SEW`.
3. The destination register group uses doubled element width, so its effective register grouping also expands accordingly.

##### Assembly Examples

```asm
vwmul.vv  v8,  v10, v12
vwmul.vx  v14, v16, a5, v0.t
vwmulu.vv v18, v20, v22
vwmulu.vx v24, v26, a6
```

- `vwmul.vv v8, v10, v12`: signed widening vector-vector multiply.
- `vwmul.vx v14, v16, a5, v0.t`: masked signed widening vector-scalar multiply.
- `vwmulu.vv v18, v20, v22`: unsigned widening vector-vector multiply.
- `vwmulu.vx v24, v26, a6`: unsigned widening vector-scalar multiply.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t  r5 = __riscv_vwmul_vv_i64m2(a, b, vl);
vuint64m2_t r6 = __riscv_vwmulu_vx_u64m2(ua, 7, vl);
```

##### Notes

1. This family keeps the full widened product instead of truncating to the low `SEW` bits.
2. Widening multiply is commonly used before widening reductions, dot-product style code, or fixed-point accumulation.
3. Signedness is explicit in the opcode name: `vwmul` for signed and `vwmulu` for unsigned.

#### 4.12.2 `vwmulsu.vv` / `vwmulsu.vx`

##### Function

These instructions perform widening mixed-signedness multiplication, with a signed first source vector and an unsigned second operand.

##### Instruction Formats

```asm
vwmulsu.vv vd, vs2, vs1, vm
vwmulsu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with `EEW = 2 * SEW` |
| `vs2` | Signed source vector register group |
| `vs1` | Unsigned source vector register group for `.vv` forms |
| `rs1` | Unsigned scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vwmulsu` computes a signed(`vs2`) × unsigned(`vs1` or `rs1`) product.
2. The result is widened to `2 * SEW`.
3. The signedness order is fixed by the ISA and should not be reversed in documentation.

##### Assembly Examples

```asm
vwmulsu.vv v28, v30, v8
vwmulsu.vx v10, v12, a7
```

- `vwmulsu.vv v28, v30, v8`: widening signed-vector × unsigned-vector multiply.
- `vwmulsu.vx v10, v12, a7`: widening signed-vector × unsigned-scalar multiply.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t r7 = __riscv_vwmulsu_vx_i64m2(a, 9u, vl);
```

##### Notes

1. `vwmulsu` is the widening counterpart of the mixed-signedness high-half multiply pattern.
2. The official operand order is signed `vs2`, unsigned second operand.
3. There is no separate `vwmulus` opcode for the reversed signedness order in RVV 1.0.

### 4.13 Vector Single-Width Integer Multiply-Add Instructions

#### 4.13.1 `vmacc.vv` / `vmacc.vx` / `vmadd.vv` / `vmadd.vx`

##### Function

These instructions perform single-width integer multiply-add operations, but the role of `vd` differs between the `vmacc` and `vmadd` families.

##### Instruction Formats

```asm
vmacc.vv vd, vs1, vs2, vm
vmacc.vx vd, rs1, vs2, vm
vmadd.vv vd, vs1, vs2, vm
vmadd.vx vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also participates as a source |
| `vs1` | Vector source register group for `.vv` forms |
| `vs2` | Vector source register group |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmacc` overwrites the addend: `vd = vd + (vs1 * vs2)` for `.vv`, or `vd = vd + (rs1 * vs2)` for `.vx`.
2. `vmadd` overwrites one multiplicand: `vd = (vs1 * vd) + vs2` for `.vv`, or `vd = (rs1 * vd) + vs2` for `.vx`.
3. These are single-width operations, so the result is written back at the current `SEW`.

##### Assembly Examples

```asm
vmacc.vv v14, v16, v18
vmacc.vx v20, a1,  v22, v0.t
vmadd.vv v24, v26, v28
vmadd.vx v30, a2,  v8
```

- `vmacc.vv v14, v16, v18`: accumulate `v16 * v18` into the previous contents of `v14`.
- `vmacc.vx v20, a1, v22, v0.t`: masked scalar-vector multiply-accumulate.
- `vmadd.vv v24, v26, v28`: use the previous contents of `v24` as a multiplicand, then add `v28`.
- `vmadd.vx v30, a2, v8`: scalar-vector multiply-add with `vd` as one multiplicand.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r8 = __riscv_vmacc_vv_i32m1(a, b, a, vl);
vint32m1_t r9 = __riscv_vmadd_vx_i32m1(a, 3, b, vl);
```

##### Notes

1. `vmacc` and `vmadd` are easy to confuse because both read and write `vd`.
2. The distinction is whether `vd` acts as the accumulator (`vmacc`) or as one multiplicand (`vmadd`).
3. Keep this section separate from widening multiply-add instructions, which have different destination widths and register grouping constraints.

#### 4.13.2 `vnmsac.vv` / `vnmsac.vx` / `vnmsub.vv` / `vnmsub.vx`

##### Function

These instructions perform negated single-width integer multiply-add operations, with the same overwrite distinction used by `vmacc` and `vmadd`.

##### Instruction Formats

```asm
vnmsac.vv vd, vs1, vs2, vm
vnmsac.vx vd, rs1, vs2, vm
vnmsub.vv vd, vs1, vs2, vm
vnmsub.vx vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also participates as a source |
| `vs1` | Vector source register group for `.vv` forms |
| `vs2` | Vector source register group |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vnmsac` overwrites the addend: `vd = vd - (vs1 * vs2)` for `.vv`, or `vd = vd - (rs1 * vs2)` for `.vx`.
2. `vnmsub` overwrites one multiplicand: `vd = vs2 - (vs1 * vd)` for `.vv`, or `vd = vs2 - (rs1 * vd)` for `.vx`.
3. These are single-width integer operations executed at the current `SEW`.

##### Assembly Examples

```asm
vnmsac.vv v10, v12, v14
vnmsac.vx v16, a3,  v18
vnmsub.vv v20, v22, v24
vnmsub.vx v26, a4,  v28, v0.t
```

- `vnmsac.vv v10, v12, v14`: subtract `v12 * v14` from the previous contents of `v10`.
- `vnmsac.vx v16, a3, v18`: scalar-vector negated multiply-accumulate.
- `vnmsub.vv v20, v22, v24`: use the previous contents of `v20` as a multiplicand in the negated multiply-add form.
- `vnmsub.vx v26, a4, v28, v0.t`: masked scalar-vector negated multiply-add.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r10 = __riscv_vnmsac_vv_i32m1(a, b, a, vl);
vint32m1_t r11 = __riscv_vnmsub_vx_i32m1(a, 3, b, vl);
```

##### Notes

1. `vnmsac` and `vnmsub` mirror the operand-role distinction of `vmacc` and `vmadd`.
2. The negation applies to the product term, not to the final sum.
3. These instructions are useful when the algorithm naturally forms subtractive fused integer updates.

### 4.14 Vector Widening Integer Multiply-Add Instructions

#### 4.14.1 `vwmacc.vv` / `vwmacc.vx` / `vwmaccu.vv` / `vwmaccu.vx`

##### Function

These instructions perform widening integer multiply-accumulate operations. The product is formed from narrow source operands, widened to `2 * SEW`, and accumulated into the wide destination register group.

##### Instruction Formats

```asm
vwmacc.vv  vd, vs1, vs2, vm
vwmacc.vx  vd, rs1, vs2, vm
vwmaccu.vv vd, vs1, vs2, vm
vwmaccu.vx vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Wide destination vector register group with `EEW = 2 * SEW`; also acts as the accumulator |
| `vs1` | Narrow vector source register group for `.vv` forms |
| `vs2` | Narrow vector source register group |
| `rs1` | Narrow scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vwmacc` computes `vd = vd + widen(signed(vs1 or rs1) * signed(vs2))`.
2. `vwmaccu` computes `vd = vd + widen(unsigned(vs1 or rs1) * unsigned(vs2))`.
3. The product is formed at the narrow source width and accumulated into the already widened destination.

##### Assembly Examples

```asm
vwmacc.vv  v8,  v10, v12
vwmacc.vx  v14, a1,  v16, v0.t
vwmaccu.vv v18, v20, v22
vwmaccu.vx v24, a2,  v26
```

- `vwmacc.vv v8, v10, v12`: signed widening vector-vector multiply-accumulate.
- `vwmacc.vx v14, a1, v16, v0.t`: masked signed widening scalar-vector multiply-accumulate.
- `vwmaccu.vv v18, v20, v22`: unsigned widening vector-vector multiply-accumulate.
- `vwmaccu.vx v24, a2, v26`: unsigned widening scalar-vector multiply-accumulate.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t  r1 = __riscv_vwmacc_vv_i64m2(acc, a, b, vl);
vuint64m2_t r2 = __riscv_vwmaccu_vx_u64m2(uacc, 7, ua, vl);
```

##### Notes

1. This family accumulates into a wide destination, unlike `vmacc`, which stays at the current `SEW`.
2. Keep the source widths and destination width distinct when documenting or generating examples.
3. The signedness distinction applies to the multiplicands, not to the widening rule itself.

#### 4.14.2 `vwmaccsu.vv` / `vwmaccsu.vx`

##### Function

These instructions perform widening mixed-signedness multiply-accumulate operations with a signed first multiplicand and an unsigned second multiplicand.

##### Instruction Formats

```asm
vwmaccsu.vv vd, vs1, vs2, vm
vwmaccsu.vx vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Wide destination vector register group with `EEW = 2 * SEW`; also acts as the accumulator |
| `vs1` | Signed narrow vector source register group for `.vv` forms |
| `vs2` | Unsigned narrow vector source register group |
| `rs1` | Signed narrow scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vwmaccsu` computes `vd = vd + widen(signed(vs1 or rs1) * unsigned(vs2))`.
2. The destination remains a widened signed accumulator.
3. The signedness order follows the operand order in the instruction format and should not be swapped.

##### Assembly Examples

```asm
vwmaccsu.vv v28, v30, v8
vwmaccsu.vx v10, a3,  v12
```

- `vwmaccsu.vv v28, v30, v8`: widening signed-vector × unsigned-vector multiply-accumulate.
- `vwmaccsu.vx v10, a3, v12`: widening signed-scalar × unsigned-vector multiply-accumulate.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t r3 = __riscv_vwmaccsu_vv_i64m2(acc, a, ua, vl);
```

##### Notes

1. `vwmaccsu` is easy to confuse with `vwmulsu` because the source-order conventions differ between the two instruction families.
2. In this family, the first explicit multiplicand (`vs1` or `rs1`) is signed and `vs2` is unsigned.
3. The accumulation still happens in the widened destination register group.

#### 4.14.3 `vwmaccus.vx`

##### Function

This instruction performs a widening mixed-signedness scalar-vector multiply-accumulate with an unsigned scalar and a signed vector source.

##### Instruction Formats

```asm
vwmaccus.vx vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Wide destination vector register group with `EEW = 2 * SEW`; also acts as the accumulator |
| `rs1` | Unsigned narrow scalar source register |
| `vs2` | Signed narrow vector source register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vwmaccus.vx` computes `vd = vd + widen(unsigned(rs1) * signed(vs2))`.
2. The destination is a widened signed accumulator.
3. RVV 1.0 defines only the `.vx` form for `vwmaccus`.

##### Assembly Examples

```asm
vwmaccus.vx v14, a4, v16, v0.t
```

- `vwmaccus.vx v14, a4, v16, v0.t`: masked widening unsigned-scalar × signed-vector multiply-accumulate.

##### Intrinsics

Common intrinsic forms:

```c
vint64m2_t r4 = __riscv_vwmaccus_vx_i64m2(acc, 9u, a, vl);
```

##### Notes

1. `vwmaccus.vx` complements `vwmaccsu.vx` by reversing the signedness order of the multiplicands.
2. There is no `.vv` form for `vwmaccus` in RVV 1.0.
3. This distinction matters when mapping mixed-signedness kernels to instruction patterns.

### 4.15 Vector Integer Merge Instructions

#### 4.15.1 `vmerge.vvm` / `vmerge.vxm` / `vmerge.vim`

##### Function

These instructions select element values from two candidates under the control of the mask register `v0`.

##### Instruction Formats

```asm
vmerge.vvm vd, vs2, vs1, v0
vmerge.vxm vd, vs2, rs1, v0
vmerge.vim vd, vs2, imm, v0
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Value chosen when `v0.mask[i] = 0` |
| `vs1` | Vector value chosen when `v0.mask[i] = 1` in `.vvm` forms |
| `rs1` | Scalar value chosen when `v0.mask[i] = 1` in `.vxm` forms |
| `imm` | Signed 5-bit immediate chosen when `v0.mask[i] = 1` in `.vim` forms |
| `v0` | Mask source register controlling per-element selection |

##### Semantics

1. `vmerge` chooses the second explicit source when `v0.mask[i] = 1`, otherwise it keeps the value from `vs2`.
2. `vmerge.vvm` selects between two vector sources.
3. `vmerge.vxm` and `vmerge.vim` select between a vector source and a scalar or immediate broadcast.

##### Assembly Examples

```asm
vmerge.vvm v18, v20, v22, v0
vmerge.vxm v24, v26, a5,  v0
vmerge.vim v28, v30, 7,   v0
```

- `vmerge.vvm v18, v20, v22, v0`: choose `v22` where `v0` is true, otherwise `v20`.
- `vmerge.vxm v24, v26, a5, v0`: choose scalar `a5` where `v0` is true, otherwise `v26`.
- `vmerge.vim v28, v30, 7, v0`: choose immediate `7` where `v0` is true, otherwise `v30`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r5 = __riscv_vmerge_vvm_i32m1(a, b, mask, vl);
vint32m1_t r6 = __riscv_vmerge_vxm_i32m1(a, 11, mask, vl);
```

##### Notes

1. `vmerge` uses `v0` as a selector operand; this is different from appending `v0.t` as a masked-execution suffix to another instruction.
2. Assembly supports `vmerge.vim`. No separate `__riscv_vmerge_vim_*` intrinsic is provided here.
3. Floating-point scalar merge is covered by the separate `vfmerge.vfm` family, not by this integer merge section.

### 4.16 Vector Integer Move Instructions

#### 4.16.1 `vmv.v.v` / `vmv.v.x` / `vmv.v.i`

##### Function

These instructions copy a vector source or broadcast a scalar or immediate value across the destination vector register group.

##### Instruction Formats

```asm
vmv.v.v vd, vs1
vmv.v.x vd, rs1
vmv.v.i vd, imm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs1` | Source vector register group for `vmv.v.v` |
| `rs1` | Scalar source register for `vmv.v.x` |
| `imm` | Signed 5-bit immediate for `vmv.v.i`, in the range `[-16, 15]` |

##### Semantics

1. `vmv.v.v` copies the source vector into the destination at the current vector type.
2. `vmv.v.x` broadcasts the scalar value in `rs1` across the active destination elements.
3. `vmv.v.i` broadcasts the sign-extended immediate across the active destination elements.

##### Assembly Examples

```asm
vmv.v.v v8,  v10
vmv.v.x v12, a6
vmv.v.i v14, -1
```

- `vmv.v.v v8, v10`: vector copy.
- `vmv.v.x v12, a6`: scalar broadcast from `a6`.
- `vmv.v.i v14, -1`: immediate broadcast of `-1`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r8 = __riscv_vmv_v_v_i32m1(a, vl);
vint32m1_t r9 = __riscv_vmv_v_x_i32m1(13, vl);
```

##### Notes

1. Use `__riscv_vmv_v_v_*` and `__riscv_vmv_v_x_*`. No separate `__riscv_vmv_v_i_*` intrinsic is provided here.
2. In C/C++, constant broadcasts can therefore be expressed through the scalar-broadcast intrinsic with a compile-time constant, while assembly may use `vmv.v.i` directly.
3. Floating-point scalar broadcast belongs to the separate `vfmv.v.f` family.

## 5. Vector Fixed-Point Arithmetic Instructions

### 5.1 Vector Single-Width Saturating Add and Subtract

#### 5.1.1 `vsadd.vv` / `vsadd.vx` / `vsadd.vi` / `vsaddu.vv` / `vsaddu.vx` / `vsaddu.vi`

##### Function

These instructions perform single-width saturating addition for signed and unsigned integer elements.

##### Instruction Formats

```asm
vsadd.vv  vd, vs2, vs1, vm
vsadd.vx  vd, vs2, rs1, vm
vsadd.vi  vd, vs2, imm, vm
vsaddu.vv vd, vs2, vs1, vm
vsaddu.vx vd, vs2, rs1, vm
vsaddu.vi vd, vs2, imm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `imm` | Signed 5-bit immediate for `.vi` forms, in the range `[-16, 15]` |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsadd` performs signed saturating addition.
2. `vsaddu` performs unsigned saturating addition.
3. If an element result exceeds the destination range, it is replaced with the closest representable destination value and `vxsat` is set.

##### Assembly Examples

```asm
vsadd.vv  v8,  v10, v12
vsadd.vx  v14, v16, a1, v0.t
vsadd.vi  v18, v20, 7
vsaddu.vv v22, v24, v26
vsaddu.vx v28, v30, a2
vsaddu.vi v8,  v10, 15, v0.t
```

- `vsadd.vv v8, v10, v12`: signed saturating vector-vector add.
- `vsadd.vx v14, v16, a1, v0.t`: masked signed saturating vector-scalar add.
- `vsadd.vi v18, v20, 7`: signed saturating add with an immediate.
- `vsaddu.vv v22, v24, v26`: unsigned saturating vector-vector add.
- `vsaddu.vx v28, v30, a2`: unsigned saturating vector-scalar add.
- `vsaddu.vi v8, v10, 15, v0.t`: masked unsigned saturating add with an immediate.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r1 = __riscv_vsadd_vv_i32m1(a, b, vl32);
vint32m1_t  r2 = __riscv_vsadd_vx_i32m1(a, 7, vl32);
vuint32m1_t r3 = __riscv_vsaddu_vv_u32m1(ua, ub, vl32);
vuint32m1_t r4 = __riscv_vsaddu_vx_u32m1(ua, 9u, vl32);
```

##### Notes

1. Assembly supports `.vi` forms for both `vsadd` and `vsaddu`.
2. No separate `__riscv_vsadd_vi_*` or `__riscv_vsaddu_vi_*` intrinsic is provided here.
3. For C/C++, an immediate constant can be expressed through the corresponding `.vx` intrinsic with a compile-time constant scalar argument.

#### 5.1.2 `vssub.vv` / `vssub.vx` / `vssubu.vv` / `vssubu.vx`

##### Function

These instructions perform single-width saturating subtraction for signed and unsigned integer elements.

##### Instruction Formats

```asm
vssub.vv  vd, vs2, vs1, vm
vssub.vx  vd, vs2, rs1, vm
vssubu.vv vd, vs2, vs1, vm
vssubu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Minuend vector register group |
| `vs1` | Subtrahend vector register group for `.vv` forms |
| `rs1` | Scalar subtrahend register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vssub` performs signed saturating subtraction.
2. `vssubu` performs unsigned saturating subtraction.
3. If an element result exceeds the destination range, it is replaced with the closest representable destination value and `vxsat` is set.

##### Assembly Examples

```asm
vssub.vv  v12, v14, v16
vssub.vx  v18, v20, a3, v0.t
vssubu.vv v22, v24, v26
vssubu.vx v28, v30, a4
```

- `vssub.vv v12, v14, v16`: signed saturating vector-vector subtract.
- `vssub.vx v18, v20, a3, v0.t`: masked signed saturating vector-scalar subtract.
- `vssubu.vv v22, v24, v26`: unsigned saturating vector-vector subtract.
- `vssubu.vx v28, v30, a4`: unsigned saturating vector-scalar subtract.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r5 = __riscv_vssub_vv_i32m1(a, b, vl32);
vuint32m1_t r6 = __riscv_vssubu_vx_u32m1(ua, 3u, vl32);
```

##### Notes

1. Unlike the saturating add family, there are no `.vi` subtract forms in RVV 1.0.
2. Signed and unsigned subtraction saturate into their respective destination domains.
3. These instructions are often used together with `vssrl` or `vnclip` in fixed-point pipelines.

### 5.2 Vector Single-Width Averaging Add and Subtract

#### 5.2.1 `vaadd.vv` / `vaadd.vx` / `vaaddu.vv` / `vaaddu.vx`

##### Function

These instructions perform averaging addition by computing a full-precision sum, right shifting it by one bit, and rounding according to `vxrm`.

##### Instruction Formats

```asm
vaadd.vv  vd, vs2, vs1, vm
vaadd.vx  vd, vs2, rs1, vm
vaaddu.vv vd, vs2, vs1, vm
vaaddu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vaadd` computes `roundoff_signed(vs2 + second_operand, 1)`.
2. `vaaddu` computes `roundoff_unsigned(vs2 + second_operand, 1)`.
3. The rounding behavior is controlled by the `vxrm` CSR.
4. For `vaadd` and `vaaddu`, overflow does not occur in the final result.

##### Assembly Examples

```asm
vaadd.vv  v8,  v10, v12
vaadd.vx  v14, v16, a1, v0.t
vaaddu.vv v18, v20, v22
vaaddu.vx v24, v26, a2
```

- `vaadd.vv v8, v10, v12`: signed averaging vector-vector add.
- `vaadd.vx v14, v16, a1, v0.t`: masked signed averaging vector-scalar add.
- `vaaddu.vv v18, v20, v22`: unsigned averaging vector-vector add.
- `vaaddu.vx v24, v26, a2`: unsigned averaging vector-scalar add.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r7 = __riscv_vaadd_vv_i32m1(a, b, 0, vl32);
vuint32m1_t r8 = __riscv_vaaddu_vx_u32m1(ua, 5u, 1, vl32);
```

##### Notes

1. Fixed-point intrinsics that round take an explicit `unsigned int vxrm` parameter.
2. Standard `vxrm` encodings are `0=rnu`, `1=rne`, `2=rdn`, `3=rod`, following the RVV specification.
3. There are no immediate forms for the averaging add family in RVV 1.0.

#### 5.2.2 `vasub.vv` / `vasub.vx` / `vasubu.vv` / `vasubu.vx`

##### Function

These instructions perform averaging subtraction by computing a full-precision difference, right shifting it by one bit, and rounding according to `vxrm`.

##### Instruction Formats

```asm
vasub.vv  vd, vs2, vs1, vm
vasub.vx  vd, vs2, rs1, vm
vasubu.vv vd, vs2, vs1, vm
vasubu.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Minuend vector register group |
| `vs1` | Subtrahend vector register group for `.vv` forms |
| `rs1` | Scalar subtrahend register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vasub` computes `roundoff_signed(vs2 - second_operand, 1)`.
2. `vasubu` computes `roundoff_unsigned(vs2 - second_operand, 1)`.
3. The rounding behavior is controlled by the `vxrm` CSR.
4. For `vasub` and `vasubu`, overflow is ignored and the intermediate subtraction wraps around before rounding.

##### Assembly Examples

```asm
vasub.vv  v28, v30, v8
vasub.vx  v10, v12, a3, v0.t
vasubu.vv v14, v16, v18
vasubu.vx v20, v22, a4
```

- `vasub.vv v28, v30, v8`: signed averaging vector-vector subtract.
- `vasub.vx v10, v12, a3, v0.t`: masked signed averaging vector-scalar subtract.
- `vasubu.vv v14, v16, v18`: unsigned averaging vector-vector subtract.
- `vasubu.vx v20, v22, a4`: unsigned averaging vector-scalar subtract.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t  r9  = __riscv_vasub_vx_i32m1(a, 11, 2, vl32);
vuint32m1_t r10 = __riscv_vasubu_vv_u32m1(ua, ub, 3, vl32);
```

##### Notes

1. The `vxrm` parameter uses the same encodings as in the averaging add family.
2. The RVV specification notes a corner case for `vasub` overflow under `rnu` and `rne`.
3. There are no immediate forms for the averaging subtract family in RVV 1.0.

### 5.3 Vector Single-Width Fractional Multiply with Rounding and Saturation

#### 5.3.1 `vsmul.vv` / `vsmul.vx`

##### Function

These instructions perform signed fractional multiplication with rounding and saturation.

##### Instruction Formats

```asm
vsmul.vv vd, vs2, vs1, vm
vsmul.vx vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First signed source vector register group |
| `vs1` | Second signed source vector register group for `.vv` forms |
| `rs1` | Signed scalar source register for `.vx` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vsmul` forms a `2 * SEW` signed product.
2. The product is shifted right by `SEW - 1` bits and rounded according to `vxrm`.
3. The rounded result is saturated to fit into the destination `SEW`, and `vxsat` is set if saturation occurs.

##### Assembly Examples

```asm
vsmul.vv v24, v26, v28
vsmul.vx v30, v8,  a5, v0.t
```

- `vsmul.vv v24, v26, v28`: signed fractional vector-vector multiply.
- `vsmul.vx v30, v8, a5, v0.t`: masked signed fractional vector-scalar multiply.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r11 = __riscv_vsmul_vv_i32m1(a, b, 0, vl32);
vint32m1_t r12 = __riscv_vsmul_vx_i32m1(a, 13, 1, vl32);
```

##### Notes

1. RVV 1.0 provides only the signed fractional multiply family.
2. The operation is designed to retain one extra bit of useful precision for most products by shifting by `SEW - 1` rather than by `SEW`.
3. The unsigned cases are instead partially covered by high-half multiply instructions when truncation is sufficient.

### 5.4 Vector Single-Width Scaling Shift Instructions

#### 5.4.1 `vssrl.vv` / `vssrl.vx` / `vssrl.vi`

##### Function

These instructions perform logical right shifts with fixed-point rounding.

##### Instruction Formats

```asm
vssrl.vv vd, vs2, vs1, vm
vssrl.vx vd, vs2, rs1, vm
vssrl.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group to be shifted |
| `vs1` | Vector shift-amount register group for `.vv` forms |
| `rs1` | Scalar shift-amount register for `.vx` forms |
| `uimm` | Zero-extended 5-bit immediate shift amount for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vssrl` computes `roundoff_unsigned(vs2, shift_amount)`.
2. The rounding behavior is controlled by `vxrm`.
3. Only the low `lg2(SEW)` bits of each shift amount are used.

##### Assembly Examples

```asm
vssrl.vv v10, v12, v14
vssrl.vx v16, v18, a6
vssrl.vi v20, v22, 3, v0.t
```

- `vssrl.vv v10, v12, v14`: logical scaling right shift with vector shift amounts.
- `vssrl.vx v16, v18, a6`: logical scaling right shift with a scalar shift amount.
- `vssrl.vi v20, v22, 3, v0.t`: masked logical scaling right shift with an immediate shift amount.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r13 = __riscv_vssrl_vv_u32m1(ua, ub, 2, vl32);
vuint32m1_t r14 = __riscv_vssrl_vx_u32m1(ua, 3, 3, vl32);
```

##### Notes

1. Assembly supports the `.vi` form. No separate `__riscv_vssrl_vi_*` intrinsic is provided here.
2. Vector shift amounts are represented with unsigned vector types.
3. The `vxrm` encodings follow the standard RVV fixed-point rounding modes.

#### 5.4.2 `vssra.vv` / `vssra.vx` / `vssra.vi`

##### Function

These instructions perform arithmetic right shifts with fixed-point rounding.

##### Instruction Formats

```asm
vssra.vv vd, vs2, vs1, vm
vssra.vx vd, vs2, rs1, vm
vssra.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Signed source vector register group to be shifted |
| `vs1` | Vector shift-amount register group for `.vv` forms |
| `rs1` | Scalar shift-amount register for `.vx` forms |
| `uimm` | Zero-extended 5-bit immediate shift amount for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vssra` computes `roundoff_signed(vs2, shift_amount)`.
2. The rounding behavior is controlled by `vxrm`.
3. Only the low `lg2(SEW)` bits of each shift amount are used.

##### Assembly Examples

```asm
vssra.vv v24, v26, v28
vssra.vx v30, v8,  a7
vssra.vi v10, v12, 2, v0.t
```

- `vssra.vv v24, v26, v28`: arithmetic scaling right shift with vector shift amounts.
- `vssra.vx v30, v8, a7`: arithmetic scaling right shift with a scalar shift amount.
- `vssra.vi v10, v12, 2, v0.t`: masked arithmetic scaling right shift with an immediate shift amount.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r15 = __riscv_vssra_vv_i32m1(a, ub, 0, vl32);
vint32m1_t r16 = __riscv_vssra_vx_i32m1(a, 4, 1, vl32);
```

##### Notes

1. Assembly supports the `.vi` form. No separate `__riscv_vssra_vi_*` intrinsic is provided here.
2. The vector shift-amount operand is represented with an unsigned vector type even though the shifted data is signed.
3. `vssra` keeps sign extension semantics and applies rounding to the discarded bits.

### 5.5 Vector Narrowing Fixed-Point Clip Instructions

#### 5.5.1 `vnclip.wv` / `vnclip.wx` / `vnclip.wi` / `vnclipu.wv` / `vnclipu.wx` / `vnclipu.wi`

##### Function

These instructions pack a widened fixed-point value into a narrower destination by applying scaling, rounding, and saturation.

##### Instruction Formats

```asm
vnclip.wv  vd, vs2, vs1, vm
vnclip.wx  vd, vs2, rs1, vm
vnclip.wi  vd, vs2, uimm, vm
vnclipu.wv vd, vs2, vs1, vm
vnclipu.wx vd, vs2, rs1, vm
vnclipu.wi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Narrow destination vector register group with element width `SEW` |
| `vs2` | Wide source vector register group with element width `2 * SEW` |
| `vs1` | Vector shift-amount register group for `.wv` forms |
| `rs1` | Scalar shift-amount register for `.wx` forms |
| `uimm` | Zero-extended 5-bit immediate shift amount for `.wi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vnclip` computes `clip(roundoff_signed(vs2, shift_amount))`.
2. `vnclipu` computes `clip(roundoff_unsigned(vs2, shift_amount))`.
3. Rounding is controlled by `vxrm`, and saturation sets `vxsat` if any destination element overflows the target format.
4. Only the low `lg2(2 * SEW)` bits of each shift amount are used.

##### Assembly Examples

```asm
vnclip.wv  v8,  v10, v12
vnclip.wx  v14, v16, a1, v0.t
vnclip.wi  v18, v20, 3
vnclipu.wv v22, v24, v26
vnclipu.wx v28, v30, a2
vnclipu.wi v8,  v10, 4, v0.t
```

- `vnclip.wv v8, v10, v12`: signed narrowing clip with vector shift amounts.
- `vnclip.wx v14, v16, a1, v0.t`: masked signed narrowing clip with a scalar shift amount.
- `vnclip.wi v18, v20, 3`: signed narrowing clip with an immediate shift amount.
- `vnclipu.wv v22, v24, v26`: unsigned narrowing clip with vector shift amounts.
- `vnclipu.wx v28, v30, a2`: unsigned narrowing clip with a scalar shift amount.
- `vnclipu.wi v8, v10, 4, v0.t`: masked unsigned narrowing clip with an immediate shift amount.

##### Intrinsics

Common intrinsic forms:

```c
vint16m1_t  r17 = __riscv_vnclip_wv_i16m1(wa, sh16, 2, vl16);
vint16m1_t  r18 = __riscv_vnclip_wx_i16m1(wa, 3, 3, vl16);
vuint16m1_t r19 = __riscv_vnclipu_wv_u16m1(wua, sh16, 0, vl16);
vuint16m1_t r20 = __riscv_vnclipu_wx_u16m1(wua, 4, 1, vl16);
```

##### Notes

1. A narrowing clip from `i32m2` to `i16m1` is expressed with the destination type in the intrinsic suffix, while the source argument remains widened.
2. The vector shift-amount operand used by `vnclip*.wv` intrinsics is an unsigned vector with the destination element width.
3. Assembly supports `.wi` forms. No separate `__riscv_vnclip_wi_*` or `__riscv_vnclipu_wi_*` intrinsic is provided here.

## 6. Vector Floating-Point Instructions

### 6.1 Vector Single-Width Floating-Point Add/Subtract Instructions

#### 6.1.1 `vfadd.vv` / `vfadd.vf`

##### Function

These instructions perform single-width floating-point addition using IEEE-754-compatible element semantics.

##### Instruction Formats

```asm
vfadd.vv vd, vs2, vs1, vm
vfadd.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfadd.vv` computes element-wise vector-vector floating-point addition.
2. `vfadd.vf` adds a scalar floating-point register value to each active vector element.
3. Active-element exceptions contribute to the scalar `fflags` register.

##### Assembly Examples

```asm
vfadd.vv v8,  v10, v12
vfadd.vf v14, v16, fa0, v0.t
```

- `vfadd.vv v8, v10, v12`: vector-vector floating-point add.
- `vfadd.vf v14, v16, fa0, v0.t`: masked vector-scalar floating-point add.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r1 = __riscv_vfadd_vv_f32m1(a, b, vl);
vfloat32m1_t r2 = __riscv_vfadd_vf_f32m1(a, 1.5f, vl);
```

##### Notes

1. The scalar operand for `.vf` forms comes from an `f` register in assembly, not from an integer register.
2. On common RV64 `F+D+V` systems, `f32` and `f64` forms are the main baseline cases.
3. `f16` vector floating-point forms require the relevant half-precision vector support extension.

#### 6.1.2 `vfsub.vv` / `vfsub.vf` / `vfrsub.vf`

##### Function

These instructions perform single-width floating-point subtraction, including a reverse-subtract scalar-vector form.

##### Instruction Formats

```asm
vfsub.vv  vd, vs2, vs1, vm
vfsub.vf  vd, vs2, rs1, vm
vfrsub.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Minuend vector register group for `vfsub`, or subtrahend vector register group for `vfrsub` |
| `vs1` | Vector subtrahend register group for `.vv` forms |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfsub.vv` computes `vd[i] = vs2[i] - vs1[i]`.
2. `vfsub.vf` computes `vd[i] = vs2[i] - f[rs1]`.
3. `vfrsub.vf` computes `vd[i] = f[rs1] - vs2[i]`.
4. Active-element exceptions contribute to the scalar `fflags` register.

##### Assembly Examples

```asm
vfsub.vv  v18, v20, v22
vfsub.vf  v24, v26, fa1
vfrsub.vf v28, v30, fa2, v0.t
```

- `vfsub.vv v18, v20, v22`: vector-vector floating-point subtract.
- `vfsub.vf v24, v26, fa1`: vector-scalar floating-point subtract.
- `vfrsub.vf v28, v30, fa2, v0.t`: masked scalar-vector reverse subtract.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r3 = __riscv_vfsub_vv_f32m1(a, b, vl);
vfloat32m1_t r4 = __riscv_vfsub_vf_f32m1(a, 2.0f, vl);
vfloat32m1_t r5 = __riscv_vfrsub_vf_f32m1(a, 3.0f, vl);
```

##### Notes

1. `vfrsub.vf` is not just an alias of `vfsub.vf`; the scalar and vector operands are reversed semantically.
2. `vfrsub` still takes the vector argument first and the scalar second, even though the mathematical operation is scalar minus vector.
3. Use care when generating examples or retrieval snippets so the reversed operand order is preserved.

### 6.2 Vector Widening Floating-Point Add/Subtract Instructions

#### 6.2.1 `vfwadd.vv` / `vfwadd.vf`

##### Function

These instructions perform widening floating-point addition from narrow operands and produce a result at `2 * SEW`.

##### Instruction Formats

```asm
vfwadd.vv vd, vs2, vs1, vm
vfwadd.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with element width `2 * SEW` |
| `vs2` | Narrow source vector register group with element width `SEW` |
| `vs1` | Narrow source vector register group for `.vv` forms |
| `rs1` | Narrow scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwadd` widens both source operands to the destination precision before adding.
2. The destination element width is `2 * SEW`.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfwadd.vv v8,  v10, v12
vfwadd.vf v14, v16, fa3, v0.t
```

- `vfwadd.vv v8, v10, v12`: widening vector-vector floating-point add.
- `vfwadd.vf v14, v16, fa3, v0.t`: masked widening vector-scalar floating-point add.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m2_t r6 = __riscv_vfwadd_vv_f64m2(a, b, vl);
vfloat64m2_t r7 = __riscv_vfwadd_vf_f64m2(a, 4.0f, vl);
```

##### Notes

1. The intrinsic suffix follows the destination type, not the narrow source type.
2. A common deployment pattern is `f32 + f32 -> f64` on systems with `F`, `D`, and `V`.
3. `f16 -> f32` widening requires vector half-precision support.

#### 6.2.2 `vfwsub.vv` / `vfwsub.vf`

##### Function

These instructions perform widening floating-point subtraction from narrow operands and produce a result at `2 * SEW`.

##### Instruction Formats

```asm
vfwsub.vv vd, vs2, vs1, vm
vfwsub.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with element width `2 * SEW` |
| `vs2` | Narrow minuend vector register group with element width `SEW` |
| `vs1` | Narrow subtrahend vector register group for `.vv` forms |
| `rs1` | Narrow scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwsub` widens operands to the destination precision before subtraction.
2. The destination element width is `2 * SEW`.
3. The operation is `vs2 - second_operand` after widening.

##### Assembly Examples

```asm
vfwsub.vv v18, v20, v22
vfwsub.vf v24, v26, fa4
```

- `vfwsub.vv v18, v20, v22`: widening vector-vector floating-point subtract.
- `vfwsub.vf v24, v26, fa4`: widening vector-scalar floating-point subtract.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m2_t r8 = __riscv_vfwsub_vv_f64m2(a, b, vl);
vfloat64m2_t r9 = __riscv_vfwsub_vf_f64m2(a, 5.0f, vl);
```

##### Notes

1. The operand ordering matches the non-widening `vfsub` family after widening.
2. The intrinsic suffix still follows the widened destination type.
3. This family is useful when subtraction accuracy benefits from an explicitly widened destination.

#### 6.2.3 `vfwadd.wv` / `vfwadd.wf`

##### Function

These instructions add a narrow floating-point operand to an already wide floating-point operand and produce a wide result.

##### Instruction Formats

```asm
vfwadd.wv vd, vs2, vs1, vm
vfwadd.wf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with element width `2 * SEW` |
| `vs2` | Wide source vector register group with element width `2 * SEW` |
| `vs1` | Narrow source vector register group with element width `SEW` for `.wv` forms |
| `rs1` | Narrow scalar floating-point register for `.wf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwadd.wv` computes `wide(vs2) + widen(vs1)`, where `vs2` is already at the destination width.
2. `vfwadd.wf` computes `wide(vs2) + widen(f[rs1])`.
3. The destination remains at the wide precision.

##### Assembly Examples

```asm
vfwadd.wv v8,  v10, v12
vfwadd.wf v14, v16, fa5, v0.t
```

- `vfwadd.wv v8, v10, v12`: wide-vector plus narrow-vector add.
- `vfwadd.wf v14, v16, fa5, v0.t`: masked wide-vector plus narrow-scalar add.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m2_t r10 = __riscv_vfwadd_wv_f64m2(wa, a, vl);
vfloat64m2_t r11 = __riscv_vfwadd_wf_f64m2(wa, 6.0f, vl);
```

##### Notes

1. The `.wv` and `.wf` forms differ from `vfwadd.vv` and `vfwadd.vf` because `vs2` is already wide.
2. The first argument is the wide vector source and also matches the destination type.
3. This distinction is important for retrieval because `vfwadd.vv` and `vfwadd.wv` solve different precision-structure patterns.

#### 6.2.4 `vfwsub.wv` / `vfwsub.wf`

##### Function

These instructions subtract a narrow floating-point operand from an already wide floating-point operand and produce a wide result.

##### Instruction Formats

```asm
vfwsub.wv vd, vs2, vs1, vm
vfwsub.wf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with element width `2 * SEW` |
| `vs2` | Wide minuend vector register group with element width `2 * SEW` |
| `vs1` | Narrow subtrahend vector register group with element width `SEW` for `.wv` forms |
| `rs1` | Narrow scalar floating-point register for `.wf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwsub.wv` computes `vs2 - widen(vs1)`, with `vs2` already at the wide precision.
2. `vfwsub.wf` computes `vs2 - widen(f[rs1])`.
3. The destination remains at the wide precision.

##### Assembly Examples

```asm
vfwsub.wv v18, v20, v22
vfwsub.wf v24, v26, fa6
```

- `vfwsub.wv v18, v20, v22`: wide-vector minus narrow-vector subtract.
- `vfwsub.wf v24, v26, fa6`: wide-vector minus narrow-scalar subtract.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m2_t r12 = __riscv_vfwsub_wv_f64m2(wa, a, vl);
vfloat64m2_t r13 = __riscv_vfwsub_wf_f64m2(wa, 7.0f, vl);
```

##### Notes

1. The `.wv` and `.wf` forms keep `vs2` at the wide precision and widen only the second operand.
2. The intrinsic suffix again follows the wide destination type.
3. This family is the subtract counterpart of `vfwadd.wv` and `vfwadd.wf`.

### 6.3 Vector Single-Width Floating-Point Multiply/Divide Instructions

#### 6.3.1 `vfmul.vv` / `vfmul.vf`

##### Function

These instructions perform single-width floating-point multiplication.

##### Instruction Formats

```asm
vfmul.vv vd, vs2, vs1, vm
vfmul.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | First source vector register group |
| `vs1` | Second source vector register group for `.vv` forms |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmul.vv` computes element-wise vector-vector floating-point products.
2. `vfmul.vf` multiplies each active vector element by a scalar floating-point register value.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfmul.vv v8,  v10, v12
vfmul.vf v14, v16, fa0, v0.t
```

- `vfmul.vv v8, v10, v12`: vector-vector floating-point multiply.
- `vfmul.vf v14, v16, fa0, v0.t`: masked vector-scalar floating-point multiply.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r1 = __riscv_vfmul_vv_f32m1(a, b, vl);
vfloat32m1_t r2 = __riscv_vfmul_vf_f32m1(a, 1.25f, vl);
```

##### Notes

1. The scalar operand for `.vf` forms comes from an `f` register in assembly.
2. Multiply follows the same operand layout conventions as the add and subtract families.
3. IEEE-754 exception behavior is aggregated into the scalar floating-point status flags for active elements.

#### 6.3.2 `vfdiv.vv` / `vfdiv.vf` / `vfrdiv.vf`

##### Function

These instructions perform single-width floating-point division, including a reverse-divide scalar-vector form.

##### Instruction Formats

```asm
vfdiv.vv  vd, vs2, vs1, vm
vfdiv.vf  vd, vs2, rs1, vm
vfrdiv.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Dividend vector register group for `vfdiv`, or divisor vector register group for `vfrdiv` |
| `vs1` | Vector divisor register group for `.vv` forms |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfdiv.vv` computes `vd[i] = vs2[i] / vs1[i]`.
2. `vfdiv.vf` computes `vd[i] = vs2[i] / f[rs1]`.
3. `vfrdiv.vf` computes `vd[i] = f[rs1] / vs2[i]`.
4. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfdiv.vv  v18, v20, v22
vfdiv.vf  v24, v26, fa1
vfrdiv.vf v28, v30, fa2, v0.t
```

- `vfdiv.vv v18, v20, v22`: vector-vector floating-point divide.
- `vfdiv.vf v24, v26, fa1`: vector-scalar floating-point divide.
- `vfrdiv.vf v28, v30, fa2, v0.t`: masked scalar-vector reverse divide.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r3 = __riscv_vfdiv_vv_f32m1(a, b, vl);
vfloat32m1_t r4 = __riscv_vfdiv_vf_f32m1(a, 2.5f, vl);
vfloat32m1_t r5 = __riscv_vfrdiv_vf_f32m1(a, 3.5f, vl);
```

##### Notes

1. `vfrdiv.vf` reverses the mathematical operand order relative to `vfdiv.vf`.
2. `vfrdiv` still takes the vector argument first and the scalar second.
3. The reverse-divide behavior should be stated explicitly to avoid semantic inversion.

### 6.4 Vector Widening Floating-Point Multiply

#### 6.4.1 `vfwmul.vv` / `vfwmul.vf`

##### Function

These instructions perform widening floating-point multiplication from narrow operands and produce a result at `2 * SEW`.

##### Instruction Formats

```asm
vfwmul.vv vd, vs2, vs1, vm
vfwmul.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group with element width `2 * SEW` |
| `vs2` | Narrow source vector register group with element width `SEW` |
| `vs1` | Narrow source vector register group for `.vv` forms |
| `rs1` | Narrow scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwmul` widens both source operands to the destination precision before multiplication.
2. The result is written at element width `2 * SEW`.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfwmul.vv v8,  v10, v12
vfwmul.vf v14, v16, fa3
```

- `vfwmul.vv v8, v10, v12`: widening vector-vector floating-point multiply.
- `vfwmul.vf v14, v16, fa3`: widening vector-scalar floating-point multiply.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m2_t r6 = __riscv_vfwmul_vv_f64m2(a, b, vl);
vfloat64m2_t r7 = __riscv_vfwmul_vf_f64m2(a, 4.5f, vl);
```

##### Notes

1. The intrinsic suffix follows the widened destination type.
2. A common baseline case is `f32 * f32 -> f64` on systems with `F`, `D`, and `V`.
3. `f16 -> f32` widening multiply requires vector half-precision support.

### 6.5 Vector Single-Width Floating-Point Fused Multiply-Add Instructions

#### 6.5.1 `vfmacc.vv` / `vfmacc.vf` / `vfnmacc.vv` / `vfnmacc.vf`

##### Function

These instructions perform single-width floating-point fused multiply-add operations that overwrite the addend.

##### Instruction Formats

```asm
vfmacc.vv  vd, vs1, vs2, vm
vfmacc.vf  vd, rs1, vs2, vm
vfnmacc.vv vd, vs1, vs2, vm
vfnmacc.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also acts as the addend |
| `vs1` | Vector multiplicand register group for `.vv` forms |
| `vs2` | Second vector multiplicand register group |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmacc` computes `vd[i] = (multiplicand1 * multiplicand2) + vd[i]`.
2. `vfnmacc` computes `vd[i] = -(multiplicand1 * multiplicand2) - vd[i]`.
3. These are fused floating-point operations and follow the usual IEEE-754 fused multiply-add behavior.

##### Assembly Examples

```asm
vfmacc.vv  v8,  v10, v12
vfmacc.vf  v14, fa0, v16, v0.t
vfnmacc.vv v18, v20, v22
vfnmacc.vf v24, fa1, v26
```

- `vfmacc.vv v8, v10, v12`: vector-vector fused multiply-accumulate.
- `vfmacc.vf v14, fa0, v16, v0.t`: masked scalar-vector fused multiply-accumulate.
- `vfnmacc.vv v18, v20, v22`: vector-vector negated fused multiply-accumulate.
- `vfnmacc.vf v24, fa1, v26`: scalar-vector negated fused multiply-accumulate.

##### Intrinsics

```c
vfloat32m1_t r1 = __riscv_vfmacc_vv_f32m1(a, b, a, vl);
vfloat32m1_t r2 = __riscv_vfmacc_vf_f32m1(a, 1.0f, b, vl);
vfloat32m1_t r3 = __riscv_vfnmacc_vv_f32m1(a, b, a, vl);
vfloat32m1_t r4 = __riscv_vfnmacc_vf_f32m1(a, 2.0f, b, vl);
```

##### Notes

1. This family overwrites the addend, so `vd` is conceptually the accumulator input.
2. The `n` in `vfnmacc` negates the product term and also changes the sign of the accumulated result as defined by the ISA.
3. `vfmacc` and `vfmadd` do not overwrite the same logical operand.

#### 6.5.2 `vfmsac.vv` / `vfmsac.vf` / `vfnmsac.vv` / `vfnmsac.vf`

##### Function

These instructions perform single-width floating-point fused multiply-add operations that overwrite the addend, with subtraction variants.

##### Instruction Formats

```asm
vfmsac.vv  vd, vs1, vs2, vm
vfmsac.vf  vd, rs1, vs2, vm
vfnmsac.vv vd, vs1, vs2, vm
vfnmsac.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also acts as the addend |
| `vs1` | Vector multiplicand register group for `.vv` forms |
| `vs2` | Second vector multiplicand register group |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmsac` computes `vd[i] = (multiplicand1 * multiplicand2) - vd[i]`.
2. `vfnmsac` computes `vd[i] = -(multiplicand1 * multiplicand2) + vd[i]`.
3. These are fused floating-point operations and follow the usual IEEE-754 fused multiply-add behavior.

##### Assembly Examples

```asm
vfmsac.vv  v28, v30, v8
vfmsac.vf  v10, fa2, v12, v0.t
vfnmsac.vv v14, v16, v18
vfnmsac.vf v20, fa3, v22
```

- `vfmsac.vv v28, v30, v8`: vector-vector fused multiply-subtract-accumulator.
- `vfmsac.vf v10, fa2, v12, v0.t`: masked scalar-vector fused multiply-subtract-accumulator.
- `vfnmsac.vv v14, v16, v18`: vector-vector negated fused multiply-subtract-accumulator.
- `vfnmsac.vf v20, fa3, v22`: scalar-vector negated fused multiply-subtract-accumulator.

##### Intrinsics

```c
vfloat32m1_t r5 = __riscv_vfmsac_vv_f32m1(a, b, a, vl);
vfloat32m1_t r6 = __riscv_vfmsac_vf_f32m1(a, 3.0f, b, vl);
vfloat32m1_t r7 = __riscv_vfnmsac_vv_f32m1(a, b, a, vl);
vfloat32m1_t r8 = __riscv_vfnmsac_vf_f32m1(a, 4.0f, b, vl);
```

##### Notes

1. `sac` reads as “subtract accumulator”.
2. This family still overwrites the addend even though the sign pattern differs from `vfmacc`.
3. It is easy to confuse `vfmsac` with `vfmsub`; only the latter overwrites a multiplicand.

#### 6.5.3 `vfmadd.vv` / `vfmadd.vf` / `vfnmadd.vv` / `vfnmadd.vf`

##### Function

These instructions perform single-width floating-point fused multiply-add operations that overwrite the first multiplicand.

##### Instruction Formats

```asm
vfmadd.vv  vd, vs1, vs2, vm
vfmadd.vf  vd, rs1, vs2, vm
vfnmadd.vv vd, vs1, vs2, vm
vfnmadd.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also acts as the first multiplicand |
| `vs1` | Vector multiplicand register group for `.vv` forms |
| `vs2` | Vector addend or subtrahend register group |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmadd` computes `vd[i] = (multiplicand1 * vd[i]) + vs2[i]`.
2. `vfnmadd` computes `vd[i] = -(multiplicand1 * vd[i]) - vs2[i]`.
3. These are fused floating-point operations and follow the usual IEEE-754 fused multiply-add behavior.

##### Assembly Examples

```asm
vfmadd.vv  v24, v26, v28
vfmadd.vf  v30, fa4, v8, v0.t
vfnmadd.vv v10, v12, v14
vfnmadd.vf v16, fa5, v18
```

- `vfmadd.vv v24, v26, v28`: vector-vector fused multiply-add with `vd` as a multiplicand.
- `vfmadd.vf v30, fa4, v8, v0.t`: masked scalar-vector fused multiply-add with `vd` as a multiplicand.
- `vfnmadd.vv v10, v12, v14`: vector-vector negated fused multiply-add with `vd` as a multiplicand.
- `vfnmadd.vf v16, fa5, v18`: scalar-vector negated fused multiply-add with `vd` as a multiplicand.

##### Intrinsics

```c
vfloat32m1_t r9  = __riscv_vfmadd_vv_f32m1(a, b, a, vl);
vfloat32m1_t r10 = __riscv_vfmadd_vf_f32m1(a, 5.0f, b, vl);
vfloat32m1_t r11 = __riscv_vfnmadd_vv_f32m1(a, b, a, vl);
vfloat32m1_t r12 = __riscv_vfnmadd_vf_f32m1(a, 6.0f, b, vl);
```

##### Notes

1. This family overwrites one multiplicand rather than the addend.
2. `vd` participates in the product term, which is the main distinction from `vfmacc`.
3. The overwrite role should be stated explicitly because the opcode names are visually similar.

#### 6.5.4 `vfmsub.vv` / `vfmsub.vf` / `vfnmsub.vv` / `vfnmsub.vf`

##### Function

These instructions perform single-width floating-point fused multiply-add operations that overwrite the first multiplicand, with subtraction variants.

##### Instruction Formats

```asm
vfmsub.vv  vd, vs1, vs2, vm
vfmsub.vf  vd, rs1, vs2, vm
vfnmsub.vv vd, vs1, vs2, vm
vfnmsub.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; also acts as the first multiplicand |
| `vs1` | Vector multiplicand register group for `.vv` forms |
| `vs2` | Vector addend or subtrahend register group |
| `rs1` | Scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmsub` computes `vd[i] = (multiplicand1 * vd[i]) - vs2[i]`.
2. `vfnmsub` computes `vd[i] = -(multiplicand1 * vd[i]) + vs2[i]`.
3. These are fused floating-point operations and follow the usual IEEE-754 fused multiply-add behavior.

##### Assembly Examples

```asm
vfmsub.vv  v20, v22, v24
vfmsub.vf  v26, fa6, v28, v0.t
vfnmsub.vv v30, v8,  v10
vfnmsub.vf v12, fa7, v14
```

- `vfmsub.vv v20, v22, v24`: vector-vector fused multiply-subtract with `vd` as a multiplicand.
- `vfmsub.vf v26, fa6, v28, v0.t`: masked scalar-vector fused multiply-subtract with `vd` as a multiplicand.
- `vfnmsub.vv v30, v8, v10`: vector-vector negated fused multiply-subtract with `vd` as a multiplicand.
- `vfnmsub.vf v12, fa7, v14`: scalar-vector negated fused multiply-subtract with `vd` as a multiplicand.

##### Intrinsics

```c
vfloat32m1_t r13 = __riscv_vfmsub_vv_f32m1(a, b, a, vl);
vfloat32m1_t r14 = __riscv_vfmsub_vf_f32m1(a, 7.0f, b, vl);
vfloat32m1_t r15 = __riscv_vfnmsub_vv_f32m1(a, b, a, vl);
vfloat32m1_t r16 = __riscv_vfnmsub_vf_f32m1(a, 8.0f, b, vl);
```

##### Notes

1. This family overwrites one multiplicand rather than the addend.
2. `vfmsub` and `vfnmsub` differ from `vfmsac` and `vfnmsac` in operand role, not just in sign pattern.
3. Correctly identifying the overwrite role is essential when mapping scalar FMA expressions to RVV forms.

### 6.6 Vector Widening Floating-Point Fused Multiply-Add Instructions

#### 6.6.1 `vfwmacc.vv` / `vfwmacc.vf` / `vfwnmacc.vv` / `vfwnmacc.vf`

##### Function

These instructions perform widening floating-point fused multiply-add operations that overwrite the wide addend.

##### Instruction Formats

```asm
vfwmacc.vv  vd, vs1, vs2, vm
vfwmacc.vf  vd, rs1, vs2, vm
vfwnmacc.vv vd, vs1, vs2, vm
vfwnmacc.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Wide destination vector register group; also acts as the addend |
| `vs1` | Narrow vector multiplicand register group for `.vv` forms |
| `vs2` | Narrow vector multiplicand register group |
| `rs1` | Narrow scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwmacc` computes `vd[i] = widen(multiplicand1 * multiplicand2) + vd[i]`.
2. `vfwnmacc` computes `vd[i] = -widen(multiplicand1 * multiplicand2) - vd[i]`.
3. The multiplier inputs are narrow, while the addend and destination are wide.

##### Assembly Examples

```asm
vfwmacc.vv  v8,  v10, v12
vfwmacc.vf  v14, fa0, v16, v0.t
vfwnmacc.vv v18, v20, v22
vfwnmacc.vf v24, fa1, v26
```

- `vfwmacc.vv v8, v10, v12`: widening vector-vector fused multiply-accumulate.
- `vfwmacc.vf v14, fa0, v16, v0.t`: masked widening scalar-vector fused multiply-accumulate.
- `vfwnmacc.vv v18, v20, v22`: widening negated vector-vector fused multiply-accumulate.
- `vfwnmacc.vf v24, fa1, v26`: widening negated scalar-vector fused multiply-accumulate.

##### Intrinsics

```c
vfloat64m2_t r17 = __riscv_vfwmacc_vv_f64m2(wa, a, b, vl);
vfloat64m2_t r18 = __riscv_vfwmacc_vf_f64m2(wa, 1.5f, a, vl);
vfloat64m2_t r19 = __riscv_vfwnmacc_vv_f64m2(wa, a, b, vl);
vfloat64m2_t r20 = __riscv_vfwnmacc_vf_f64m2(wa, 2.5f, a, vl);
```

##### Notes

1. The destination and addend are wide, while the multiplicands remain narrow.
2. This family overwrites the wide addend.
3. The intrinsic suffix follows the widened destination type.

#### 6.6.2 `vfwmsac.vv` / `vfwmsac.vf` / `vfwnmsac.vv` / `vfwnmsac.vf`

##### Function

These instructions perform widening floating-point fused multiply-add operations that overwrite the wide addend, with subtraction variants.

##### Instruction Formats

```asm
vfwmsac.vv  vd, vs1, vs2, vm
vfwmsac.vf  vd, rs1, vs2, vm
vfwnmsac.vv vd, vs1, vs2, vm
vfwnmsac.vf vd, rs1, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Wide destination vector register group; also acts as the addend |
| `vs1` | Narrow vector multiplicand register group for `.vv` forms |
| `vs2` | Narrow vector multiplicand register group |
| `rs1` | Narrow scalar floating-point register for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwmsac` computes `vd[i] = widen(multiplicand1 * multiplicand2) - vd[i]`.
2. `vfwnmsac` computes `vd[i] = -widen(multiplicand1 * multiplicand2) + vd[i]`.
3. The multiplier inputs are narrow, while the addend and destination are wide.

##### Assembly Examples

```asm
vfwmsac.vv  v28, v30, v8
vfwmsac.vf  v10, fa2, v12, v0.t
vfwnmsac.vv v14, v16, v18
vfwnmsac.vf v20, fa3, v22
```

- `vfwmsac.vv v28, v30, v8`: widening vector-vector fused multiply-subtract-accumulator.
- `vfwmsac.vf v10, fa2, v12, v0.t`: masked widening scalar-vector fused multiply-subtract-accumulator.
- `vfwnmsac.vv v14, v16, v18`: widening negated vector-vector fused multiply-subtract-accumulator.
- `vfwnmsac.vf v20, fa3, v22`: widening negated scalar-vector fused multiply-subtract-accumulator.

##### Intrinsics

```c
vfloat64m2_t r21 = __riscv_vfwmsac_vv_f64m2(wa, a, b, vl);
vfloat64m2_t r22 = __riscv_vfwmsac_vf_f64m2(wa, 3.5f, a, vl);
vfloat64m2_t r23 = __riscv_vfwnmsac_vv_f64m2(wa, a, b, vl);
vfloat64m2_t r24 = __riscv_vfwnmsac_vf_f64m2(wa, 4.5f, a, vl);
```

##### Notes

1. This family overwrites the wide addend rather than a multiplicand.
2. `vfwmsac` and `vfwnmsac` are the widening subtract counterparts of `vfwmacc` and `vfwnmacc`.
3. Wide-accumulator and single-width FMA families should be documented separately because their precision structure is different.

### 6.7 Vector Floating-Point Square-Root Instruction

#### 6.7.1 `vfsqrt.v`

##### Function

This instruction computes the square root of each active floating-point vector element.

##### Instruction Formats

```asm
vfsqrt.v vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfsqrt.v` is a unary vector-vector floating-point instruction.
2. Each active element computes the IEEE-754 square root of the corresponding source element.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfsqrt.v v8,  v10
vfsqrt.v v12, v14, v0.t
```

- `vfsqrt.v v8, v10`: element-wise floating-point square root.
- `vfsqrt.v v12, v14, v0.t`: masked floating-point square root.

##### Intrinsics

```c
vfloat32m1_t r1 = __riscv_vfsqrt_v_f32m1(a, vl);
```

##### Notes

1. `vfsqrt.v` is unary; there is no `.vf` or `.vv` binary form in this family.
2. Like other standard vector floating-point arithmetic operations, it uses the dynamic rounding mode in `frm`.
3. Inactive elements do not contribute floating-point exceptions.

### 6.8 Vector Floating-Point Reciprocal Square-Root Estimate Instruction

#### 6.8.1 `vfrsqrt7.v`

##### Function

This instruction computes an estimate of the reciprocal square root for each active floating-point vector element.

##### Instruction Formats

```asm
vfrsqrt7.v vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfrsqrt7.v` is a unary vector-vector floating-point instruction.
2. For positive finite inputs, it returns an estimate of `1/sqrt(x)` accurate to 7 bits.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfrsqrt7.v v16, v18
vfrsqrt7.v v20, v22, v0.t
```

- `vfrsqrt7.v v16, v18`: element-wise reciprocal square-root estimate.
- `vfrsqrt7.v v20, v22, v0.t`: masked reciprocal square-root estimate.

##### Intrinsics

```c
vfloat32m1_t r2 = __riscv_vfrsqrt7_v_f32m1(a, vl);
```

##### Notes

1. `vfrsqrt7.v` returns an estimate, not a fully refined reciprocal square root.
2. The RVV specification defines special-case behavior for negative values, signed zero, infinity, and NaNs.
3. The output value is independent of the dynamic rounding mode.

### 6.9 Vector Floating-Point Reciprocal Estimate Instruction

#### 6.9.1 `vfrec7.v`

##### Function

This instruction computes an estimate of the reciprocal for each active floating-point vector element.

##### Instruction Formats

```asm
vfrec7.v vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfrec7.v` is a unary vector-vector floating-point instruction.
2. It returns an estimate of `1/x` accurate to 7 bits.
3. The RVV specification defines special-case behavior for zero, infinity, subnormal inputs, and NaNs.

##### Assembly Examples

```asm
vfrec7.v v8,  v10
vfrec7.v v12, v14, v0.t
```

- `vfrec7.v v8, v10`: element-wise reciprocal estimate.
- `vfrec7.v v12, v14, v0.t`: masked reciprocal estimate.

##### Intrinsics

```c
vfloat32m1_t r1 = __riscv_vfrec7_v_f32m1(a, vl);
```

##### Notes

1. `vfrec7.v` returns an estimate, not a fully refined reciprocal.
2. The output value depends on the dynamic rounding mode when overflow is raised.
3. For non-exceptional cases, the estimate is produced by a specification-defined lookup scheme.

### 6.10 Vector Floating-Point MIN/MAX Instructions

#### 6.10.1 `vfmin.vv` / `vfmin.vf`

##### Function

These instructions compute the element-wise floating-point minimum of two operands.

##### Instruction Formats

```asm
vfmin.vv vd, vs2, vs1, vm
vfmin.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | First vector source operand |
| `vs1` | Second vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmin` performs the `minimumNumber` operation on active elements.
2. The instruction follows the same behavior as the corresponding scalar floating-point minimum instruction.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfmin.vv v16, v18, v20
vfmin.vf v22, v24, fa0, v0.t
```

- `vfmin.vv v16, v18, v20`: element-wise floating-point minimum between two vectors.
- `vfmin.vf v22, v24, fa0, v0.t`: masked floating-point minimum between a vector and a scalar.

##### Intrinsics

```c
vfloat32m1_t r2 = __riscv_vfmin_vv_f32m1(a, b, vl);
vfloat32m1_t r3 = __riscv_vfmin_vf_f32m1(a, 1.5f, vl);
```

##### Notes

1. `vfmin` follows the scalar `minimumNumber` semantics rather than a purely bitwise comparison rule.
2. The `.vf` form still takes the vector operand first and the scalar operand second.
3. Inactive elements do not contribute floating-point exceptions.

#### 6.10.2 `vfmax.vv` / `vfmax.vf`

##### Function

These instructions compute the element-wise floating-point maximum of two operands.

##### Instruction Formats

```asm
vfmax.vv vd, vs2, vs1, vm
vfmax.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | First vector source operand |
| `vs1` | Second vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfmax` performs the `maximumNumber` operation on active elements.
2. The instruction follows the same behavior as the corresponding scalar floating-point maximum instruction.
3. Active-element exceptions contribute to `fflags`.

##### Assembly Examples

```asm
vfmax.vv v8,  v10, v12
vfmax.vf v14, v16, fa1
```

- `vfmax.vv v8, v10, v12`: element-wise floating-point maximum between two vectors.
- `vfmax.vf v14, v16, fa1`: floating-point maximum between a vector and a scalar.

##### Intrinsics

```c
vfloat32m1_t r4 = __riscv_vfmax_vv_f32m1(a, b, vl);
vfloat32m1_t r5 = __riscv_vfmax_vf_f32m1(a, 2.5f, vl);
```

##### Notes

1. `vfmax` follows the scalar `maximumNumber` semantics rather than a purely bitwise comparison rule.
2. The operand order matches the assembly syntax `vd, vs2, vs1/rs1`.
3. Inactive elements do not contribute floating-point exceptions.

### 6.11 Vector Floating-Point Sign-Injection Instructions

#### 6.11.1 `vfsgnj.vv` / `vfsgnj.vf`

##### Function

These instructions copy the magnitude bits from `vs2` and inject the sign bit from the second operand.

##### Instruction Formats

```asm
vfsgnj.vv vd, vs2, vs1, vm
vfsgnj.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source operand that provides all non-sign bits |
| `vs1` | Vector source operand that provides the sign bit for `.vv` forms |
| `rs1` | Scalar floating-point source operand that provides the sign bit for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfsgnj` copies all bits except the sign bit from `vs2`.
2. The result sign bit is copied from `vs1` or `rs1`.
3. This family is the vector form of the scalar floating-point sign-injection instructions.

##### Assembly Examples

```asm
vfsgnj.vv v8,  v10, v12
vfsgnj.vf v14, v16, fa0, v0.t
```

- `vfsgnj.vv v8, v10, v12`: inject sign bits from a vector source.
- `vfsgnj.vf v14, v16, fa0, v0.t`: masked sign injection from a scalar source.

##### Intrinsics

```c
vfloat32m1_t r1 = __riscv_vfsgnj_vv_f32m1(a, b, vl);
vfloat32m1_t r2 = __riscv_vfsgnj_vf_f32m1(a, 1.0f, vl);
```

##### Notes

1. The magnitude comes from `vs2`; only the sign bit comes from the second operand.
2. `vfsgnj` is useful for constructing sign-controlled copies without changing exponent or significand bits.
3. The `.vf` form uses a scalar floating-point register as the sign source.

#### 6.11.2 `vfsgnjn.vv` / `vfsgnjn.vf`

##### Function

These instructions copy the magnitude bits from `vs2` and inject the inverted sign bit from the second operand.

##### Instruction Formats

```asm
vfsgnjn.vv vd, vs2, vs1, vm
vfsgnjn.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source operand that provides all non-sign bits |
| `vs1` | Vector source operand whose sign bit is inverted for `.vv` forms |
| `rs1` | Scalar floating-point source operand whose sign bit is inverted for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfsgnjn` copies all bits except the sign bit from `vs2`.
2. The result sign bit is the inverse of the sign bit taken from `vs1` or `rs1`.
3. This family is the vector form of the scalar floating-point sign-injection-negate instructions.

##### Assembly Examples

```asm
vfsgnjn.vv v18, v20, v22
vfsgnjn.vf v24, v26, fa1
```

- `vfsgnjn.vv v18, v20, v22`: inject inverted sign bits from a vector source.
- `vfsgnjn.vf v24, v26, fa1`: inject an inverted scalar sign bit into each active vector element.

##### Intrinsics

```c
vfloat32m1_t r3 = __riscv_vfsgnjn_vv_f32m1(a, b, vl);
vfloat32m1_t r4 = __riscv_vfsgnjn_vf_f32m1(a, -1.0f, vl);
```

##### Notes

1. `vfsgnjn` differs from `vfsgnj` only in the treatment of the injected sign bit.
2. Setting both source operands to the same vector yields the `vfneg.v` pseudoinstruction.
3. The magnitude still comes entirely from `vs2`.

#### 6.11.3 `vfsgnjx.vv` / `vfsgnjx.vf`

##### Function

These instructions copy the magnitude bits from `vs2` and compute the result sign bit by XORing the operand signs.

##### Instruction Formats

```asm
vfsgnjx.vv vd, vs2, vs1, vm
vfsgnjx.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source operand that provides all non-sign bits |
| `vs1` | Vector source operand that contributes a sign bit for `.vv` forms |
| `rs1` | Scalar floating-point source operand that contributes a sign bit for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfsgnjx` copies all bits except the sign bit from `vs2`.
2. The result sign bit is the XOR of the sign bit from `vs2` and the sign bit from `vs1` or `rs1`.
3. This family is the vector form of the scalar floating-point sign-injection-XOR instructions.

##### Assembly Examples

```asm
vfsgnjx.vv v28, v30, v8
vfsgnjx.vf v10, v12, fa2, v0.t
```

- `vfsgnjx.vv v28, v30, v8`: inject a sign bit computed by XORing two vector signs.
- `vfsgnjx.vf v10, v12, fa2, v0.t`: masked sign injection with scalar-sign XOR.

##### Intrinsics

```c
vfloat32m1_t r5 = __riscv_vfsgnjx_vv_f32m1(a, b, vl);
vfloat32m1_t r6 = __riscv_vfsgnjx_vf_f32m1(a, 2.0f, vl);
```

##### Notes

1. `vfsgnjx` is commonly used for sign toggling and absolute-value style transformations.
2. Setting both vector source operands to the same value yields the `vfabs.v` pseudoinstruction.
3. Only the sign bit is recomputed; the remaining bits still come from `vs2`.

### 6.12 Vector Floating-Point Compare Instructions

#### 6.12.1 `vmfeq.vv` / `vmfeq.vf`

##### Function

These instructions compare floating-point operands for equality and write the result to a mask register.

##### Instruction Formats

```asm
vmfeq.vv vd, vs2, vs1, vm
vmfeq.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First floating-point vector source operand |
| `vs1` | Second floating-point vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmfeq` compares active elements for floating-point equality.
2. The result is written to a mask register, so the destination layout follows the standard mask-register layout.
3. `vmfeq` raises invalid operation only on signaling NaN inputs.

##### Assembly Examples

```asm
vmfeq.vv v0, v8,  v10
vmfeq.vf v0, v12, fa0, v0.t
```

- `vmfeq.vv v0, v8, v10`: element-wise floating-point equality compare.
- `vmfeq.vf v0, v12, fa0, v0.t`: masked vector-scalar floating-point equality compare.

##### Intrinsics

```c
vbool32_t m1 = __riscv_vmfeq_vv_f32m1_b32(a, b, vl);
vbool32_t m2 = __riscv_vmfeq_vf_f32m1_b32(a, 1.0f, vl);
```

##### Notes

1. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.
2. The destination mask register may be `v0`.
3. Inactive elements do not contribute floating-point exceptions.

#### 6.12.2 `vmfne.vv` / `vmfne.vf`

##### Function

These instructions compare floating-point operands for inequality and write the result to a mask register.

##### Instruction Formats

```asm
vmfne.vv vd, vs2, vs1, vm
vmfne.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First floating-point vector source operand |
| `vs1` | Second floating-point vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmfne` compares active elements for floating-point inequality.
2. When either operand is NaN, `vmfne` writes `1` to the destination mask element.
3. `vmfne` raises invalid operation only on signaling NaN inputs.

##### Assembly Examples

```asm
vmfne.vv v0, v14, v16
vmfne.vf v0, v18, fa1
```

- `vmfne.vv v0, v14, v16`: element-wise floating-point inequality compare.
- `vmfne.vf v0, v18, fa1`: vector-scalar floating-point inequality compare.

##### Intrinsics

```c
vbool32_t m3 = __riscv_vmfne_vv_f32m1_b32(a, b, vl);
vbool32_t m4 = __riscv_vmfne_vf_f32m1_b32(a, 2.0f, vl);
```

##### Notes

1. `vmfne` is the only floating-point compare in this family that writes `1` when either operand is NaN.
2. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.
3. Inactive elements do not contribute floating-point exceptions.

#### 6.12.3 `vmflt.vv` / `vmflt.vf`

##### Function

These instructions compare whether the first operand is less than the second operand and write the result to a mask register.

##### Instruction Formats

```asm
vmflt.vv vd, vs2, vs1, vm
vmflt.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First floating-point vector source operand |
| `vs1` | Second floating-point vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmflt` compares active elements for the ordered less-than relation.
2. When either operand is NaN, the destination mask element is written as `0`.
3. `vmflt` raises invalid operation on both signaling and quiet NaN inputs.

##### Assembly Examples

```asm
vmflt.vv v0, v20, v22
vmflt.vf v0, v24, fa2, v0.t
```

- `vmflt.vv v0, v20, v22`: element-wise floating-point less-than compare.
- `vmflt.vf v0, v24, fa2, v0.t`: masked vector-scalar floating-point less-than compare.

##### Intrinsics

```c
vbool32_t m5 = __riscv_vmflt_vv_f32m1_b32(a, b, vl);
vbool32_t m6 = __riscv_vmflt_vf_f32m1_b32(a, 3.0f, vl);
```

##### Notes

1. `vmflt` is an ordered compare.
2. Greater-than vector-vector comparisons are represented by reversing operands to `vmflt`.
3. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.

#### 6.12.4 `vmfle.vv` / `vmfle.vf`

##### Function

These instructions compare whether the first operand is less than or equal to the second operand and write the result to a mask register.

##### Instruction Formats

```asm
vmfle.vv vd, vs2, vs1, vm
vmfle.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First floating-point vector source operand |
| `vs1` | Second floating-point vector source operand for `.vv` forms |
| `rs1` | Scalar floating-point source operand for `.vf` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmfle` compares active elements for the ordered less-than-or-equal relation.
2. When either operand is NaN, the destination mask element is written as `0`.
3. `vmfle` raises invalid operation on both signaling and quiet NaN inputs.

##### Assembly Examples

```asm
vmfle.vv v0, v8,  v10
vmfle.vf v0, v12, fa3
```

- `vmfle.vv v0, v8, v10`: element-wise floating-point less-than-or-equal compare.
- `vmfle.vf v0, v12, fa3`: vector-scalar floating-point less-than-or-equal compare.

##### Intrinsics

```c
vbool32_t m7 = __riscv_vmfle_vv_f32m1_b32(a, b, vl);
vbool32_t m8 = __riscv_vmfle_vf_f32m1_b32(a, 4.0f, vl);
```

##### Notes

1. `vmfle` is an ordered compare.
2. Greater-than-or-equal vector-vector comparisons are represented by reversing operands to `vmfle`.
3. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.

#### 6.12.5 `vmfgt.vf`

##### Function

This instruction compares whether each active vector element is greater than a scalar floating-point operand and writes the result to a mask register.

##### Instruction Formats

```asm
vmfgt.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Floating-point vector source operand |
| `rs1` | Scalar floating-point source operand |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmfgt.vf` compares active elements for the ordered greater-than relation.
2. When either operand is NaN, the destination mask element is written as `0`.
3. `vmfgt.vf` raises invalid operation on both signaling and quiet NaN inputs.

##### Assembly Examples

```asm
vmfgt.vf v0, v14, fa4, v0.t
```

- `vmfgt.vf v0, v14, fa4, v0.t`: masked vector-scalar floating-point greater-than compare.

##### Intrinsics

```c
vbool32_t m9 = __riscv_vmfgt_vf_f32m1_b32(a, 5.0f, vl);
```

##### Notes

1. Only the `.vf` form is defined here.
2. Greater-than vector-vector comparisons are represented by reversing operands to `vmflt.vv`.
3. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.

#### 6.12.6 `vmfge.vf`

##### Function

This instruction compares whether each active vector element is greater than or equal to a scalar floating-point operand and writes the result to a mask register.

##### Instruction Formats

```asm
vmfge.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Floating-point vector source operand |
| `rs1` | Scalar floating-point source operand |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vmfge.vf` compares active elements for the ordered greater-than-or-equal relation.
2. When either operand is NaN, the destination mask element is written as `0`.
3. `vmfge.vf` raises invalid operation on both signaling and quiet NaN inputs.

##### Assembly Examples

```asm
vmfge.vf v0, v16, fa5
```

- `vmfge.vf v0, v16, fa5`: vector-scalar floating-point greater-than-or-equal compare.

##### Intrinsics

```c
vbool32_t m10 = __riscv_vmfge_vf_f32m1_b32(a, 6.0f, vl);
```

##### Notes

1. Only the `.vf` form is defined here.
2. Greater-than-or-equal vector-vector comparisons are represented by reversing operands to `vmfle.vv`.
3. Compare instructions write mask registers and therefore operate under a tail-agnostic policy.

### 6.13 Vector Floating-Point Classify Instruction

#### 6.13.1 `vfclass.v`

##### Function

This instruction classifies each active floating-point vector element and writes the classification bits to an integer vector register.

##### Instruction Formats

```asm
vfclass.v vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination integer vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfclass.v` is a unary vector-vector instruction.
2. The 10-bit floating-point class mask is placed in the least-significant bits of each destination element.
3. The upper `SEW-10` bits of each destination element are filled with zeros.

##### Assembly Examples

```asm
vfclass.v v18, v20
vfclass.v v22, v24, v0.t
```

- `vfclass.v v18, v20`: classify each active floating-point element.
- `vfclass.v v22, v24, v0.t`: masked floating-point classification.

##### Intrinsics

```c
vuint32m1_t c1 = __riscv_vfclass_v_u32m1(a, vl);
```

##### Notes

1. `vfclass.v` follows the same classification scheme as the scalar floating-point classify instruction.
2. The instruction is defined only for `SEW >= 16`, so the 10-bit result always fits in the destination element.
3. The destination is an integer vector, not a mask register.

### 6.14 Vector Floating-Point Merge Instruction

#### 6.14.1 `vfmerge.vfm`

##### Function

This instruction merges a vector operand with a scalar floating-point operand under control of the mask in `v0`.

##### Instruction Formats

```asm
vfmerge.vfm vd, vs2, rs1, v0
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Vector source operand copied when the mask bit is `0` |
| `rs1` | Scalar floating-point source operand copied when the mask bit is `1` |
| `v0` | Implicit mask register used by the instruction |

##### Semantics

1. At elements where the mask bit is `0`, `vs2[i]` is copied to `vd[i]`.
2. At elements where the mask bit is `1`, the scalar floating-point value from `rs1` is copied to `vd[i]`.
3. `vfmerge.vfm` is encoded as a masked instruction with `vm=0`.

##### Assembly Examples

```asm
vfmerge.vfm v8, v10, fa0, v0
```

- `vfmerge.vfm v8, v10, fa0, v0`: merge `v10` with scalar `fa0` under the control of `v0`.

##### Intrinsics

```c
vfloat32m1_t r1 = __riscv_vfmerge_vfm_f32m1(a, 1.5f, mask, vl);
```

##### Notes

1. The intrinsic parameter order is `vector, scalar, mask, vl`.
2. `vfmerge.vfm` operates on body elements from `vstart` to `vl` under the mask in `v0`.
3. This instruction is distinct from `vfmv.v.f`, which broadcasts the scalar to all active elements without masking.

### 6.15 Vector Floating-Point Move Instruction

#### 6.15.1 `vfmv.v.f`

##### Function

This instruction broadcasts a scalar floating-point value to all active elements of a destination vector register group.

##### Instruction Formats

```asm
vfmv.v.f vd, rs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `rs1` | Scalar floating-point source operand |

##### Semantics

1. `vfmv.v.f` copies the scalar floating-point value in `rs1` to all active elements of `vd`.
2. The instruction is encoded as an unmasked instruction with `vm=1`.
3. The `vs2` field must be encoded as `v0`; other encodings are reserved.

##### Assembly Examples

```asm
vfmv.v.f v12, fa1
```

- `vfmv.v.f v12, fa1`: broadcast scalar `fa1` to all active elements of `v12`.

##### Intrinsics

```c
vfloat32m1_t r2 = __riscv_vfmv_v_f_f32m1(2.5f, vl);
```

##### Notes

1. `vfmv.v.f` is a broadcast operation, not a merge.
2. This section covers only the vector broadcast form `vfmv.v.f`.
3. The destination value is uniform across all active elements.

### 6.16 Single-Width Floating-Point/Integer Type-Convert Instructions

#### 6.16.1 `vfcvt.xu.f.v` / `vfcvt.x.f.v`

##### Function

These instructions convert floating-point vector elements to same-width unsigned or signed integer vector elements.

##### Instruction Formats

```asm
vfcvt.xu.f.v vd, vs2, vm
vfcvt.x.f.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination integer vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfcvt.xu.f.v` converts active floating-point elements to same-width unsigned integers.
2. `vfcvt.x.f.v` converts active floating-point elements to same-width signed integers.
3. These conversions follow the same exceptional-condition rules as the scalar floating-point conversion instructions and use the dynamic rounding mode in `frm`.

##### Assembly Examples

```asm
vfcvt.xu.f.v v8,  v10
vfcvt.x.f.v  v12, v14, v0.t
```

- `vfcvt.xu.f.v v8, v10`: convert floating-point elements to unsigned integers.
- `vfcvt.x.f.v v12, v14, v0.t`: masked conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint32m1_t r1 = __riscv_vfcvt_xu_f_v_u32m1(a, vl);
vint32m1_t  r2 = __riscv_vfcvt_x_f_v_i32m1(a, vl);
```

##### Notes

1. The source and destination have the same element width.
2. These are not truncating conversions unless the active `frm` mode happens to be round-towards-zero.
3. Active-element exceptions contribute to `fflags`.

#### 6.16.2 `vfcvt.rtz.xu.f.v` / `vfcvt.rtz.x.f.v`

##### Function

These instructions convert floating-point vector elements to same-width unsigned or signed integer vector elements using round-towards-zero semantics.

##### Instruction Formats

```asm
vfcvt.rtz.xu.f.v vd, vs2, vm
vfcvt.rtz.x.f.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination integer vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfcvt.rtz.xu.f.v` converts active floating-point elements to same-width unsigned integers using round-towards-zero.
2. `vfcvt.rtz.x.f.v` converts active floating-point elements to same-width signed integers using round-towards-zero.
3. These instructions follow the same scalar exceptional-condition rules as the corresponding scalar truncating conversion instructions.

##### Assembly Examples

```asm
vfcvt.rtz.xu.f.v v16, v18
vfcvt.rtz.x.f.v  v20, v22, v0.t
```

- `vfcvt.rtz.xu.f.v v16, v18`: truncating conversion from floating-point to unsigned integers.
- `vfcvt.rtz.x.f.v v20, v22, v0.t`: masked truncating conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint32m1_t r3 = __riscv_vfcvt_rtz_xu_f_v_u32m1(a, vl);
vint32m1_t  r4 = __riscv_vfcvt_rtz_x_f_v_i32m1(a, vl);
```

##### Notes

1. The `rtz` variants do not use the dynamic rounding mode in `frm`.
2. The source and destination have the same element width.
3. Active-element exceptions contribute to `fflags`.

#### 6.16.3 `vfcvt.f.xu.v` / `vfcvt.f.x.v`

##### Function

These instructions convert same-width unsigned or signed integer vector elements to floating-point vector elements.

##### Instruction Formats

```asm
vfcvt.f.xu.v vd, vs2, vm
vfcvt.f.x.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group |
| `vs2` | Source integer vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfcvt.f.xu.v` converts active unsigned integer elements to same-width floating-point elements.
2. `vfcvt.f.x.v` converts active signed integer elements to same-width floating-point elements.
3. These conversions use the dynamic rounding mode in `frm` and may round when the source value is not exactly representable in the destination floating-point format.

##### Assembly Examples

```asm
vfcvt.f.xu.v v24, v26
vfcvt.f.x.v  v28, v30, v0.t
```

- `vfcvt.f.xu.v v24, v26`: convert unsigned integers to floating-point elements.
- `vfcvt.f.x.v v28, v30, v0.t`: masked conversion from signed integers to floating-point elements.

##### Intrinsics

```c
vfloat32m1_t r5 = __riscv_vfcvt_f_xu_v_f32m1(ua, vl);
vfloat32m1_t r6 = __riscv_vfcvt_f_x_v_f32m1(sa, vl);
```

##### Notes

1. Same-width integer-to-floating-point conversion is not guaranteed to be exact for all source values.
2. The source and destination have the same element width.
3. Active-element exceptions contribute to `fflags`.

### 6.17 Widening Floating-Point/Integer Type-Convert Instructions

#### 6.17.1 `vfwcvt.xu.f.v` / `vfwcvt.x.f.v`

##### Function

These instructions convert floating-point vector elements to double-width unsigned or signed integer vector elements.

##### Instruction Formats

```asm
vfwcvt.xu.f.v vd, vs2, vm
vfwcvt.x.f.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination double-width integer vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwcvt.xu.f.v` converts active floating-point elements to double-width unsigned integers.
2. `vfwcvt.x.f.v` converts active floating-point elements to double-width signed integers.
3. These conversions follow the same scalar exceptional-condition rules as scalar conversions and use the dynamic rounding mode in `frm`.

##### Assembly Examples

```asm
vfwcvt.xu.f.v v8,  v10
vfwcvt.x.f.v  v12, v14, v0.t
```

- `vfwcvt.xu.f.v v8, v10`: widening conversion from floating-point to unsigned integers.
- `vfwcvt.x.f.v v12, v14, v0.t`: masked widening conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint64m2_t r1 = __riscv_vfwcvt_xu_f_v_u64m2(a, vl);
vint64m2_t  r2 = __riscv_vfwcvt_x_f_v_i64m2(a, vl);
```

##### Notes

1. The destination element width is twice the source element width.
2. These instructions follow the same overlap constraints as other widening vector instructions.
3. Active-element exceptions contribute to `fflags`.

#### 6.17.2 `vfwcvt.rtz.xu.f.v` / `vfwcvt.rtz.x.f.v`

##### Function

These instructions convert floating-point vector elements to double-width unsigned or signed integer vector elements using round-towards-zero semantics.

##### Instruction Formats

```asm
vfwcvt.rtz.xu.f.v vd, vs2, vm
vfwcvt.rtz.x.f.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination double-width integer vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwcvt.rtz.xu.f.v` converts active floating-point elements to double-width unsigned integers using round-towards-zero.
2. `vfwcvt.rtz.x.f.v` converts active floating-point elements to double-width signed integers using round-towards-zero.
3. These instructions follow the same scalar exceptional-condition rules as the corresponding scalar truncating conversion instructions.

##### Assembly Examples

```asm
vfwcvt.rtz.xu.f.v v16, v18
vfwcvt.rtz.x.f.v  v20, v22, v0.t
```

- `vfwcvt.rtz.xu.f.v v16, v18`: widening truncating conversion from floating-point to unsigned integers.
- `vfwcvt.rtz.x.f.v v20, v22, v0.t`: masked widening truncating conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint64m2_t r3 = __riscv_vfwcvt_rtz_xu_f_v_u64m2(a, vl);
vint64m2_t  r4 = __riscv_vfwcvt_rtz_x_f_v_i64m2(a, vl);
```

##### Notes

1. The `rtz` variants do not use the dynamic rounding mode in `frm`.
2. The destination element width is twice the source element width.
3. Active-element exceptions contribute to `fflags`.

#### 6.17.3 `vfwcvt.f.xu.v` / `vfwcvt.f.x.v`

##### Function

These instructions convert integer vector elements to double-width floating-point vector elements.

##### Instruction Formats

```asm
vfwcvt.f.xu.v vd, vs2, vm
vfwcvt.f.x.v  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination double-width floating-point vector register group |
| `vs2` | Source integer vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwcvt.f.xu.v` converts active unsigned integer elements to double-width floating-point elements.
2. `vfwcvt.f.x.v` converts active signed integer elements to double-width floating-point elements.
3. A double-width IEEE floating-point value can always represent a single-width integer exactly.

##### Assembly Examples

```asm
vfwcvt.f.xu.v v24, v26
vfwcvt.f.x.v  v8,  v10, v0.t
```

- `vfwcvt.f.xu.v v24, v26`: widening conversion from unsigned integers to floating-point elements.
- `vfwcvt.f.x.v v8, v10, v0.t`: masked widening conversion from signed integers to floating-point elements.

##### Intrinsics

```c
vfloat64m2_t r5 = __riscv_vfwcvt_f_xu_v_f64m2(ua, vl);
vfloat64m2_t r6 = __riscv_vfwcvt_f_x_v_f64m2(sa, vl);
```

##### Notes

1. The intrinsic suffix follows the widened destination type.
2. The destination element width is twice the source element width.
3. These instructions follow the same overlap constraints as other widening vector instructions.

#### 6.17.4 `vfwcvt.f.f.v`

##### Function

This instruction converts single-width floating-point vector elements to double-width floating-point vector elements.

##### Instruction Formats

```asm
vfwcvt.f.f.v vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination double-width floating-point vector register group |
| `vs2` | Source floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwcvt.f.f.v` converts active single-width floating-point elements to double-width floating-point elements.
2. A double-width IEEE floating-point value can always represent a single-width IEEE floating-point value exactly.
3. Any widening conversion not directly provided can be implemented as multiple doubling steps with equivalent results and no additional exception flags.

##### Assembly Examples

```asm
vfwcvt.f.f.v v12, v14
```

- `vfwcvt.f.f.v v12, v14`: widening conversion from single-width to double-width floating-point elements.

##### Intrinsics

```c
vfloat64m2_t r7 = __riscv_vfwcvt_f_f_v_f64m2(a, vl);
```

##### Notes

1. This widening floating-point conversion is exact.
2. The destination element width is twice the source element width.
3. These instructions follow the same overlap constraints as other widening vector instructions.

### 6.18 Narrowing Floating-Point/Integer Type-Convert Instructions

#### 6.18.1 `vfncvt.xu.f.w` / `vfncvt.x.f.w`

##### Function

These instructions convert double-width floating-point vector elements to single-width unsigned or signed integer vector elements.

##### Instruction Formats

```asm
vfncvt.xu.f.w vd, vs2, vm
vfncvt.x.f.w  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination single-width integer vector register group |
| `vs2` | Source double-width floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfncvt.xu.f.w` converts active double-width floating-point elements to single-width unsigned integers.
2. `vfncvt.x.f.w` converts active double-width floating-point elements to single-width signed integers.
3. These conversions follow the same scalar exceptional-condition rules as the corresponding scalar conversion instructions and use the dynamic rounding mode in `frm`.

##### Assembly Examples

```asm
vfncvt.xu.f.w v8,  v10
vfncvt.x.f.w  v12, v14, v0.t
```

- `vfncvt.xu.f.w v8, v10`: narrowing conversion from floating-point to unsigned integers.
- `vfncvt.x.f.w v12, v14, v0.t`: masked narrowing conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint32m1_t r1 = __riscv_vfncvt_xu_f_w_u32m1(a, vl);
vint32m1_t  r2 = __riscv_vfncvt_x_f_w_i32m1(a, vl);
```

##### Notes

1. The source element width is twice the destination element width.
2. These instructions follow the same overlap constraints as other narrowing vector instructions.
3. Active-element exceptions contribute to `fflags`.

#### 6.18.2 `vfncvt.rtz.xu.f.w` / `vfncvt.rtz.x.f.w`

##### Function

These instructions convert double-width floating-point vector elements to single-width unsigned or signed integer vector elements using round-towards-zero semantics.

##### Instruction Formats

```asm
vfncvt.rtz.xu.f.w vd, vs2, vm
vfncvt.rtz.x.f.w  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination single-width integer vector register group |
| `vs2` | Source double-width floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfncvt.rtz.xu.f.w` converts active double-width floating-point elements to single-width unsigned integers using round-towards-zero.
2. `vfncvt.rtz.x.f.w` converts active double-width floating-point elements to single-width signed integers using round-towards-zero.
3. These instructions follow the same scalar exceptional-condition rules as the corresponding scalar truncating conversion instructions.

##### Assembly Examples

```asm
vfncvt.rtz.xu.f.w v16, v18
vfncvt.rtz.x.f.w  v20, v22, v0.t
```

- `vfncvt.rtz.xu.f.w v16, v18`: narrowing truncating conversion from floating-point to unsigned integers.
- `vfncvt.rtz.x.f.w v20, v22, v0.t`: masked narrowing truncating conversion from floating-point to signed integers.

##### Intrinsics

```c
vuint32m1_t r3 = __riscv_vfncvt_rtz_xu_f_w_u32m1(a, vl);
vint32m1_t  r4 = __riscv_vfncvt_rtz_x_f_w_i32m1(a, vl);
```

##### Notes

1. The `rtz` variants do not use the dynamic rounding mode in `frm`.
2. The source element width is twice the destination element width.
3. Active-element exceptions contribute to `fflags`.

#### 6.18.3 `vfncvt.f.xu.w` / `vfncvt.f.x.w`

##### Function

These instructions convert double-width unsigned or signed integer vector elements to single-width floating-point vector elements.

##### Instruction Formats

```asm
vfncvt.f.xu.w vd, vs2, vm
vfncvt.f.x.w  vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination single-width floating-point vector register group |
| `vs2` | Source double-width integer vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfncvt.f.xu.w` converts active double-width unsigned integer elements to single-width floating-point elements.
2. `vfncvt.f.x.w` converts active double-width signed integer elements to single-width floating-point elements.
3. These conversions use the dynamic rounding mode in `frm` and may round when the source value is not exactly representable in the destination floating-point format.

##### Assembly Examples

```asm
vfncvt.f.xu.w v24, v26
vfncvt.f.x.w  v28, v30, v0.t
```

- `vfncvt.f.xu.w v24, v26`: narrowing conversion from unsigned integers to floating-point elements.
- `vfncvt.f.x.w v28, v30, v0.t`: masked narrowing conversion from signed integers to floating-point elements.

##### Intrinsics

```c
vfloat32m1_t r5 = __riscv_vfncvt_f_xu_w_f32m1(ua, vl);
vfloat32m1_t r6 = __riscv_vfncvt_f_x_w_f32m1(sa, vl);
```

##### Notes

1. The source element width is twice the destination element width.
2. These instructions follow the same overlap constraints as other narrowing vector instructions.
3. Active-element exceptions contribute to `fflags`.

#### 6.18.4 `vfncvt.f.f.w` / `vfncvt.rod.f.f.w`

##### Function

These instructions convert double-width floating-point vector elements to single-width floating-point vector elements.

##### Instruction Formats

```asm
vfncvt.f.f.w     vd, vs2, vm
vfncvt.rod.f.f.w vd, vs2, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination single-width floating-point vector register group |
| `vs2` | Source double-width floating-point vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfncvt.f.f.w` converts active double-width floating-point elements to single-width floating-point elements using the dynamic rounding mode in `frm`.
2. `vfncvt.rod.f.f.w` converts active double-width floating-point elements to single-width floating-point elements using round-towards-odd.
3. For multi-step halving conversions, all but the final halving step should use `vfncvt.rod.f.f.w` to preserve equivalent final rounding and exception behavior.

##### Assembly Examples

```asm
vfncvt.f.f.w     v8,  v10
vfncvt.rod.f.f.w v12, v14, v0.t
```

- `vfncvt.f.f.w v8, v10`: narrowing conversion from double-width to single-width floating-point elements.
- `vfncvt.rod.f.f.w v12, v14, v0.t`: masked round-towards-odd narrowing conversion.

##### Intrinsics

```c
vfloat32m1_t r7 = __riscv_vfncvt_f_f_w_f32m1(a, vl);
vfloat32m1_t r8 = __riscv_vfncvt_rod_f_f_w_f32m1(a, vl);
```

##### Notes

1. `vfncvt.rod.f.f.w` is intended for intermediate halving steps in longer narrowing conversion sequences.
2. For `vfncvt.rod.f.f.w`, a finite value that exceeds the destination range is converted to the destination format's largest finite value with the same sign.
3. These instructions follow the same overlap constraints as other narrowing vector instructions.

## 7. Vector Reduction Operations

### 7.1 Vector Single-Width Integer Reduction Instructions

#### 7.1.1 `vredsum.vs`

##### Function

`vredsum.vs` performs a single-width integer sum reduction. The reduction result is written to element `0` of the destination vector register group.

##### Instruction Formats

```asm
vredsum.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source vector register group to be reduced |
| `vs1` | Source vector register group whose element `0` provides the initial accumulator |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. Active elements of `vs2` are reduced with integer addition.
2. `vs1[0]` provides the initial accumulator value.
3. The final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vmv.v.i v8, 0
vredsum.vs v4, v16, v8
vredsum.vs v6, v18, v8, v0.t
```

- `vredsum.vs v4, v16, v8`: reduce all active elements of `v16` with `v8[0]` as the seed.
- `vredsum.vs v6, v18, v8, v0.t`: masked integer sum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vredsum_vs_i32m1_i32m1(a, seed, vl);
vuint16m1_t r2 = __riscv_vredsum_vs_u16m1_u16m1(a, seed, vl);
```

##### Notes

1. Signed and unsigned forms share the same instruction mnemonic; the interpretation follows the intrinsic type or surrounding use.
2. Only element `0` of the destination holds the reduction result; other destination elements follow the standard reduction-instruction rules.

#### 7.1.2 `vredmax.vs` / `vredmaxu.vs`

##### Function

These instructions perform single-width integer maximum reduction. `vredmax.vs` treats elements as signed integers, and `vredmaxu.vs` treats elements as unsigned integers.

##### Instruction Formats

```asm
vredmax.vs  vd, vs2, vs1, vm
vredmaxu.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source vector register group to be reduced |
| `vs1` | Source vector register group whose element `0` provides the initial comparison value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vredmax.vs` reduces active elements of `vs2` with signed maximum.
2. `vredmaxu.vs` reduces active elements of `vs2` with unsigned maximum.
3. `vs1[0]` is included as the initial value, and the final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vmv.v.i v8, 0
vredmax.vs  v4, v16, v8
vredmaxu.vs v6, v18, v8, v0.t
```

- `vredmax.vs v4, v16, v8`: signed integer maximum reduction.
- `vredmaxu.vs v6, v18, v8, v0.t`: masked unsigned integer maximum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vredmax_vs_i32m1_i32m1(a, seed, vl);
vuint32m1_t r2 = __riscv_vredmaxu_vs_u32m1_u32m1(a, seed, vl);
```

##### Notes

1. Use the signed form for two's-complement signed comparisons.
2. Use the unsigned form when the element bit pattern should be ordered as an unsigned integer.

#### 7.1.3 `vredmin.vs` / `vredminu.vs`

##### Function

These instructions perform single-width integer minimum reduction. `vredmin.vs` treats elements as signed integers, and `vredminu.vs` treats elements as unsigned integers.

##### Instruction Formats

```asm
vredmin.vs  vd, vs2, vs1, vm
vredminu.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source vector register group to be reduced |
| `vs1` | Source vector register group whose element `0` provides the initial comparison value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vredmin.vs` reduces active elements of `vs2` with signed minimum.
2. `vredminu.vs` reduces active elements of `vs2` with unsigned minimum.
3. `vs1[0]` is included as the initial value, and the final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e16, m2
vmv.v.i v8, -1
vredmin.vs  v4, v16, v8
vredminu.vs v6, v18, v8, v0.t
```

- `vredmin.vs v4, v16, v8`: signed integer minimum reduction.
- `vredminu.vs v6, v18, v8, v0.t`: masked unsigned integer minimum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vredmin_vs_i32m1_i32m1(a, seed, vl);
vuint16m1_t r2 = __riscv_vredminu_vs_u16m1_u16m1(a, seed, vl);
```

##### Notes

1. The seed value in `vs1[0]` should be chosen consistently with signed or unsigned ordering.
2. Only element `0` of the destination holds the reduction result.

#### 7.1.4 `vredand.vs`

##### Function

`vredand.vs` performs a single-width integer bitwise AND reduction.

##### Instruction Formats

```asm
vredand.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source vector register group to be reduced |
| `vs1` | Source vector register group whose element `0` provides the initial value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. Active elements of `vs2` are reduced with bitwise AND.
2. `vs1[0]` provides the initial value.
3. The final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vmv.v.i v8, -1
vredand.vs v4, v16, v8
vredand.vs v6, v18, v8, v0.t
```

- `vredand.vs v4, v16, v8`: bitwise AND reduction using an all-ones seed.
- `vredand.vs v6, v18, v8, v0.t`: masked bitwise AND reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vredand_vs_i32m1_i32m1(a, seed, vl);
vuint16m1_t r2 = __riscv_vredand_vs_u16m1_u16m1(a, seed, vl);
```

##### Notes

1. This is a bitwise reduction; it does not interpret the source elements as Boolean values.
2. Signed and unsigned intrinsic variants map to the same instruction mnemonic.

#### 7.1.5 `vredor.vs` / `vredxor.vs`

##### Function

These instructions perform single-width integer bitwise OR and XOR reductions.

##### Instruction Formats

```asm
vredor.vs  vd, vs2, vs1, vm
vredxor.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source vector register group to be reduced |
| `vs1` | Source vector register group whose element `0` provides the initial value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vredor.vs` reduces active elements of `vs2` with bitwise OR.
2. `vredxor.vs` reduces active elements of `vs2` with bitwise XOR.
3. `vs1[0]` provides the initial value, and the final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vmv.v.i v8, 0
vredor.vs  v4, v16, v8
vredxor.vs v6, v18, v8, v0.t
```

- `vredor.vs v4, v16, v8`: bitwise OR reduction.
- `vredxor.vs v6, v18, v8, v0.t`: masked bitwise XOR reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vredor_vs_i32m1_i32m1(a, seed, vl);
vuint16m1_t r2 = __riscv_vredxor_vs_u16m1_u16m1(a, seed, vl);
```

##### Notes

1. Both signed and unsigned intrinsic variants map to the same instruction mnemonics.
2. Choose the seed value according to the intended bitwise identity or application logic.

### 7.2 Vector Widening Integer Reduction Instructions

#### 7.2.1 `vwredsum.vs` / `vwredsumu.vs`

##### Function

These instructions perform widening integer sum reduction. `vwredsum.vs` sign-extends source elements before accumulation, and `vwredsumu.vs` zero-extends source elements before accumulation.

##### Instruction Formats

```asm
vwredsum.vs  vd, vs2, vs1, vm
vwredsumu.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination wide integer vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source integer vector register group to be reduced |
| `vs1` | Wide integer source vector register group whose element `0` provides the initial accumulator |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. Active elements of `vs2` are extended to the wider accumulator width.
2. `vwredsum.vs` uses signed extension; `vwredsumu.vs` uses unsigned extension.
3. `vs1[0]` provides the initial wide accumulator value, and the final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e16, m2
vmv.v.i v8, 0
vwredsum.vs  v4, v16, v8
vwredsumu.vs v6, v18, v8, v0.t
```

- `vwredsum.vs v4, v16, v8`: signed widening integer sum reduction.
- `vwredsumu.vs v6, v18, v8, v0.t`: masked unsigned widening integer sum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vwredsum_vs_i16m1_i32m1(a, seed, vl);
vuint32m1_t r2 = __riscv_vwredsumu_vs_u16m1_u32m1(a, seed, vl);
```

##### Notes

1. The source element width is narrower than the accumulator/result width.
2. The intrinsic suffix includes both the narrow source type and the wide accumulator/result type.

### 7.3 Vector Single-Width Floating-Point Reduction Instructions

#### 7.3.1 `vfredosum.vs` / `vfredusum.vs`

##### Function

These instructions perform single-width floating-point sum reduction. `vfredosum.vs` is ordered, while `vfredusum.vs` is unordered.

##### Instruction Formats

```asm
vfredosum.vs vd, vs2, vs1, vm
vfredusum.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source floating-point vector register group to be reduced |
| `vs1` | Source floating-point vector register group whose element `0` provides the initial accumulator |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfredosum.vs` reduces active elements in element order.
2. `vfredusum.vs` may reduce active elements using an implementation-defined order.
3. Floating-point exceptions from active elements contribute to the scalar `fflags` register.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vfmv.v.f v8, fa0
vfredosum.vs v4, v16, v8
vfredusum.vs v6, v18, v8, v0.t
```

- `vfredosum.vs v4, v16, v8`: ordered floating-point sum reduction.
- `vfredusum.vs v6, v18, v8, v0.t`: masked unordered floating-point sum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r1 = __riscv_vfredosum_vs_f32m1_f32m1(a, seed, vl);
vfloat64m1_t r2 = __riscv_vfredusum_vs_f64m1_f64m1(a, seed, vl);
```

##### Notes

1. Ordered reduction is the form to use when reproducible element-order accumulation is required.
2. Unordered reduction may allow more implementation freedom and therefore different rounding behavior.

#### 7.3.2 `vfredmax.vs`

##### Function

`vfredmax.vs` performs a single-width floating-point maximum reduction.

##### Instruction Formats

```asm
vfredmax.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source floating-point vector register group to be reduced |
| `vs1` | Source floating-point vector register group whose element `0` provides the initial comparison value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. Active elements of `vs2` are reduced with floating-point maximum semantics.
2. `vs1[0]` is included as the initial value.
3. The final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vfmv.v.f v8, fa0
vfredmax.vs v4, v16, v8
vfredmax.vs v6, v18, v8, v0.t
```

- `vfredmax.vs v4, v16, v8`: floating-point maximum reduction.
- `vfredmax.vs v6, v18, v8, v0.t`: masked floating-point maximum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r1 = __riscv_vfredmax_vs_f32m1_f32m1(a, seed, vl);
vfloat64m1_t r2 = __riscv_vfredmax_vs_f64m1_f64m1(a, seed, vl);
```

##### Notes

1. Floating-point exception behavior follows the standard floating-point reduction rules.
2. NaN handling follows the floating-point maximum operation semantics defined for the instruction.

#### 7.3.3 `vfredmin.vs`

##### Function

`vfredmin.vs` performs a single-width floating-point minimum reduction.

##### Instruction Formats

```asm
vfredmin.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination floating-point vector register group; the reduction result is written to `vd[0]` |
| `vs2` | Source floating-point vector register group to be reduced |
| `vs1` | Source floating-point vector register group whose element `0` provides the initial comparison value |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. Active elements of `vs2` are reduced with floating-point minimum semantics.
2. `vs1[0]` is included as the initial value.
3. The final result is written to `vd[0]`.

##### Assembly Examples

```asm
vsetvli t0, a0, e32, m4
vfmv.v.f v8, fa0
vfredmin.vs v4, v16, v8
vfredmin.vs v6, v18, v8, v0.t
```

- `vfredmin.vs v4, v16, v8`: floating-point minimum reduction.
- `vfredmin.vs v6, v18, v8, v0.t`: masked floating-point minimum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vfloat32m1_t r1 = __riscv_vfredmin_vs_f32m1_f32m1(a, seed, vl);
vfloat64m1_t r2 = __riscv_vfredmin_vs_f64m1_f64m1(a, seed, vl);
```

##### Notes

1. Floating-point exception behavior follows the standard floating-point reduction rules.
2. NaN handling follows the floating-point minimum operation semantics defined for the instruction.

### 7.4 Vector Widening Floating-Point Reduction Instructions

#### 7.4.1 `vfwredosum.vs` / `vfwredusum.vs`

##### Function

These instructions reduce a floating-point vector into a wider floating-point scalar accumulator stored in element `0` of the destination vector register group.

##### Instruction Formats

```asm
vfwredosum.vs vd, vs2, vs1, vm
vfwredusum.vs vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination wide floating-point vector register group; the final reduction result is written to element `0` |
| `vs2` | Source floating-point vector register group to be reduced |
| `vs1` | Wide floating-point scalar seed stored in element `0` of a vector register group |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vfwredosum.vs` performs an ordered widening floating-point sum reduction from element `0` upward.
2. `vfwredusum.vs` performs an unordered widening floating-point sum reduction and may use an implementation-defined reduction tree.
3. The accumulator and final result use the widened floating-point format represented by `vd` and `vs1`.

##### Assembly Examples

```asm
vfwredosum.vs v8,  v10, v12
vfwredusum.vs v14, v16, v18, v0.t
```

- `vfwredosum.vs v8, v10, v12`: ordered widening floating-point sum reduction.
- `vfwredusum.vs v14, v16, v18, v0.t`: masked unordered widening floating-point sum reduction.

##### Intrinsics

Common intrinsic forms:

```c
vfloat64m1_t r1 = __riscv_vfwredosum_vs_f32m1_f64m1(a, seed, vl);
vfloat64m1_t r2 = __riscv_vfwredusum_vs_f32m1_f64m1(a, seed, vl);
```

##### Notes

1. The source vector uses the narrower floating-point format, while the accumulator uses the wider format.
2. The intrinsic suffix for the accumulator/result is the scalar reduction form, not a widened LMUL form.
3. Only element `0` of the destination holds the reduction result; other destination elements follow the standard reduction-instruction rules.

## 8. Vector Mask Instructions

### 8.1 Vector Mask-Register Logical Instructions

#### 8.1.1 `vmand.mm` / `vmnand.mm` / `vmandn.mm`

##### Function

These instructions perform bitwise logical operations on mask registers.

##### Instruction Formats

```asm
vmand.mm  vd, vs2, vs1
vmnand.mm vd, vs2, vs1
vmandn.mm vd, vs2, vs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source mask register |
| `vs1` | Second source mask register |

##### Semantics

1. `vmand.mm` computes `vd[i] = vs2[i] & vs1[i]`.
2. `vmnand.mm` computes `vd[i] = ~(vs2[i] & vs1[i])`.
3. `vmandn.mm` computes `vd[i] = vs2[i] & ~vs1[i]`.

##### Assembly Examples

```asm
vmand.mm  v0,  v2,  v4
vmnand.mm v6,  v8,  v10
vmandn.mm v12, v14, v16
```

- `vmand.mm v0, v2, v4`: bitwise AND on mask registers.
- `vmnand.mm v6, v8, v10`: bitwise NAND on mask registers.
- `vmandn.mm v12, v14, v16`: bitwise AND-NOT on mask registers.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r1 = __riscv_vmand_mm_b32(a, b, vl);
vbool32_t r2 = __riscv_vmnand_mm_b32(a, b, vl);
vbool32_t r3 = __riscv_vmandn_mm_b32(a, b, vl);
```

##### Notes

1. These instructions operate on mask bits, not integer vector elements.
2. Mask logical instructions are unmasked instructions.
3. The result mask type is determined by the operand mask type.

#### 8.1.2 `vmor.mm` / `vmnor.mm` / `vmorn.mm`

##### Function

These instructions perform bitwise OR-family operations on mask registers.

##### Instruction Formats

```asm
vmor.mm  vd, vs2, vs1
vmnor.mm vd, vs2, vs1
vmorn.mm vd, vs2, vs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source mask register |
| `vs1` | Second source mask register |

##### Semantics

1. `vmor.mm` computes `vd[i] = vs2[i] | vs1[i]`.
2. `vmnor.mm` computes `vd[i] = ~(vs2[i] | vs1[i])`.
3. `vmorn.mm` computes `vd[i] = vs2[i] | ~vs1[i]`.

##### Assembly Examples

```asm
vmor.mm  v18, v20, v22
vmnor.mm v24, v26, v28
vmorn.mm v30, v0,  v2
```

- `vmor.mm v18, v20, v22`: bitwise OR on mask registers.
- `vmnor.mm v24, v26, v28`: bitwise NOR on mask registers.
- `vmorn.mm v30, v0, v2`: bitwise OR-NOT on mask registers.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r4 = __riscv_vmor_mm_b32(a, b, vl);
vbool32_t r5 = __riscv_vmnor_mm_b32(a, b, vl);
vbool32_t r6 = __riscv_vmorn_mm_b32(a, b, vl);
```

##### Notes

1. `vmorn.mm` keeps the first operand in positive form and inverts only the second operand.
2. These instructions operate on mask bits, not integer vector elements.
3. The result mask type is determined by the operand mask type.

#### 8.1.3 `vmxor.mm` / `vmxnor.mm`

##### Function

These instructions perform bitwise XOR-family operations on mask registers.

##### Instruction Formats

```asm
vmxor.mm  vd, vs2, vs1
vmxnor.mm vd, vs2, vs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | First source mask register |
| `vs1` | Second source mask register |

##### Semantics

1. `vmxor.mm` computes `vd[i] = vs2[i] ^ vs1[i]`.
2. `vmxnor.mm` computes `vd[i] = ~(vs2[i] ^ vs1[i])`.
3. These instructions operate bitwise on mask-register elements.

##### Assembly Examples

```asm
vmxor.mm  v4,  v6,  v8
vmxnor.mm v10, v12, v14
```

- `vmxor.mm v4, v6, v8`: bitwise XOR on mask registers.
- `vmxnor.mm v10, v12, v14`: bitwise XNOR on mask registers.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r7 = __riscv_vmxor_mm_b32(a, b, vl);
vbool32_t r8 = __riscv_vmxnor_mm_b32(a, b, vl);
```

##### Notes

1. `vmxor.mm` is useful for mask toggling and difference detection.
2. `vmxnor.mm` is useful for mask equivalence tests.
3. The result mask type is determined by the operand mask type.

#### 8.1.4 `vmmv.m`

##### Function

This instruction copies one mask register to another.

##### Instruction Formats

```asm
vmmv.m vd, vs
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs` | Source mask register |

##### Semantics

1. `vmmv.m` copies each active mask bit from `vs` to `vd`.
2. The pseudoinstruction expands to `vmand.mm vd, vs, vs`.
3. It is a mask-register move, not an integer-vector move.

##### Assembly Examples

```asm
vmmv.m v0, v2
```

- `vmmv.m v0, v2`: copy mask register `v2` to `v0`.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r1 = __riscv_vmmv_m_b32(a, vl);
```

##### Notes

1. `vmmv.m` is a pseudoinstruction.
2. The source and destination mask types must match.
3. It is commonly used to preserve intermediate mask results across later mask operations.

#### 8.1.5 `vmclr.m`

##### Function

This instruction clears all bits of a mask register.

##### Instruction Formats

```asm
vmclr.m vd
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |

##### Semantics

1. `vmclr.m` sets every mask bit in `vd` to `0`.
2. The pseudoinstruction expands to `vmxor.mm vd, vd, vd`.
3. It produces an all-zero mask value.

##### Assembly Examples

```asm
vmclr.m v4
```

- `vmclr.m v4`: clear all bits in mask register `v4`.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r2 = __riscv_vmclr_m_b32(vl);
```

##### Notes

1. `vmclr.m` is a pseudoinstruction.
2. It does not require a source mask operand.
3. It is commonly used to initialize a mask register before building a new condition mask.

#### 8.1.6 `vmset.m`

##### Function

This instruction sets all bits of a mask register.

##### Instruction Formats

```asm
vmset.m vd
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |

##### Semantics

1. `vmset.m` sets every mask bit in `vd` to `1`.
2. The pseudoinstruction expands to `vmxnor.mm vd, vd, vd`.
3. It produces an all-one mask value.

##### Assembly Examples

```asm
vmset.m v6
```

- `vmset.m v6`: set all bits in mask register `v6`.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r3 = __riscv_vmset_m_b32(vl);
```

##### Notes

1. `vmset.m` is a pseudoinstruction.
2. It does not require a source mask operand.
3. It is commonly used as a starting point for later mask refinement.

#### 8.1.7 `vmnot.m`

##### Function

This instruction inverts all bits of a mask register.

##### Instruction Formats

```asm
vmnot.m vd, vs
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs` | Source mask register |

##### Semantics

1. `vmnot.m` computes the bitwise inversion of each mask bit in `vs`.
2. The pseudoinstruction expands to `vmnand.mm vd, vs, vs`.
3. It produces the logical complement of the source mask.

##### Assembly Examples

```asm
vmnot.m v8, v10
```

- `vmnot.m v8, v10`: invert all bits from mask register `v10` into `v8`.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r4 = __riscv_vmnot_m_b32(a, vl);
```

##### Notes

1. `vmnot.m` is a pseudoinstruction.
2. The source and destination mask types must match.
3. It is commonly used to build the complement of an already-computed condition mask.

### 8.2 Vector Count Population in Mask Instruction

#### 8.2.1 `vcpop.m`

##### Function

This instruction counts the number of active mask elements in a source mask register that have the value `1` and writes the result to a scalar integer register.

##### Instruction Formats

```asm
vcpop.m rd, vs2, vm
vcpop.m rd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `rd` | Destination scalar integer register |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements are counted |

##### Semantics

1. `vcpop.m` counts active source mask elements whose value is `1`.
2. When masked, only elements where both `vs2[i]` and `v0[i]` are `1` contribute to the count.
3. The result is written to a scalar `x` register.

##### Assembly Examples

```asm
vcpop.m a0, v2
vcpop.m a1, v4, v0.t
```

- `vcpop.m a0, v2`: count all active `1` bits in mask register `v2`.
- `vcpop.m a1, v4, v0.t`: count active `1` bits in `v4` under the additional mask `v0`.

##### Intrinsics

Common intrinsic forms:

```c
size_t c = __riscv_vcpop_m_b32(a, vl);
```

##### Notes

1. `vcpop.m` writes `rd` even when `vl = 0`; in that case the value written is `0`.
2. The instruction raises an illegal-instruction exception if `vstart` is non-zero.
3. Older software may use the historical assembler alias `vpopc.m`.

### 8.3 Find-First-Set and Set-Before-First Mask Instructions

#### 8.3.1 `vfirst.m`

##### Function

This instruction finds the lowest-numbered active source mask element whose value is `1` and writes its index to a scalar integer register.

##### Instruction Formats

```asm
vfirst.m rd, vs2, vm
vfirst.m rd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `rd` | Destination scalar integer register |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements are examined |

##### Semantics

1. `vfirst.m` scans active source mask elements from low index to high index.
2. It writes the index of the first active element whose value is `1`.
3. If no active element has the value `1`, it writes `-1` to the destination scalar register.

##### Assembly Examples

```asm
vfirst.m a2, v6
vfirst.m a3, v8, v0.t
```

- `vfirst.m a2, v6`: find the first active set bit in `v6`.
- `vfirst.m a3, v8, v0.t`: find the first active set bit in `v8` under the additional mask `v0`.

##### Intrinsics

Common intrinsic forms:

```c
long idx = __riscv_vfirst_m_b32(a, vl);
```

##### Notes

1. `vfirst.m` writes `rd` even when `vl = 0`; in that case the value written is `-1`.
2. Any negative result indicates that no matching active element was found.
3. The instruction raises an illegal-instruction exception if `vstart` is non-zero.

#### 8.3.2 `vmsbf.m`

##### Function

This instruction writes `1` to all active mask elements before the first active source element whose value is `1`, then writes `0` to that element and all later active elements.

##### Instruction Formats

```asm
vmsbf.m vd, vs2, vm
vmsbf.m vd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements are considered |

##### Semantics

1. `vmsbf.m` sets all active destination mask elements before the first active source `1` bit.
2. The first active source `1` bit and all following active elements are written as `0`.
3. If there is no set bit in the active elements of the source mask register, all active destination elements are written as `1`.

##### Assembly Examples

```asm
vmsbf.m v10, v12
vmsbf.m v14, v16, v0.t
```

- `vmsbf.m v10, v12`: set mask bits before the first active set bit in `v12`.
- `vmsbf.m v14, v16, v0.t`: masked set-before-first operation.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t m = __riscv_vmsbf_m_b32(a, vl);
```

##### Notes

1. Tail elements in the destination mask register follow a tail-agnostic policy.
2. The destination register cannot overlap the source register and, when masked, cannot overlap `v0`.
3. The instruction raises an illegal-instruction exception if `vstart` is non-zero.

### 8.4 Set-Including-First Mask Bit Instruction

#### 8.4.1 `vmsif.m`

##### Function

This instruction writes `1` to all active mask elements up to and including the first active source element whose value is `1`, then writes `0` to all later active elements.

##### Instruction Formats

```asm
vmsif.m vd, vs2, vm
vmsif.m vd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements are considered |

##### Semantics

1. `vmsif.m` behaves like `vmsbf.m`, but it also sets the first active source `1` bit.
2. All active destination elements after that first active source `1` bit are written as `0`.
3. If there is no set bit in the active elements of the source mask register, all active destination elements are written as `1`.

##### Assembly Examples

```asm
vmsif.m v2, v4
vmsif.m v6, v8, v0.t
```

- `vmsif.m v2, v4`: set mask bits up to and including the first active set bit in `v4`.
- `vmsif.m v6, v8, v0.t`: masked set-including-first operation.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r1 = __riscv_vmsif_m_b32(a, vl);
```

##### Notes

1. Tail elements in the destination mask register follow a tail-agnostic policy.
2. The destination register cannot overlap the source register and, when masked, cannot overlap `v0`.
3. The instruction raises an illegal-instruction exception if `vstart` is non-zero.

### 8.5 Set-Only-First Mask Bit Instruction

#### 8.5.1 `vmsof.m`

##### Function

This instruction writes `1` only to the first active source mask element whose value is `1` and writes `0` to all other active destination elements.

##### Instruction Formats

```asm
vmsof.m vd, vs2, vm
vmsof.m vd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination mask register |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements are considered |

##### Semantics

1. `vmsof.m` identifies the first active source element whose value is `1`.
2. That destination mask element is written as `1`, and all other active destination elements are written as `0`.
3. If there is no set bit in the active elements of the source mask register, all active destination elements are written as `0`.

##### Assembly Examples

```asm
vmsof.m v10, v12
vmsof.m v14, v16, v0.t
```

- `vmsof.m v10, v12`: isolate the first active set bit in `v12`.
- `vmsof.m v14, v16, v0.t`: masked set-only-first operation.

##### Intrinsics

Common intrinsic forms:

```c
vbool32_t r2 = __riscv_vmsof_m_b32(a, vl);
```

##### Notes

1. Tail elements in the destination mask register follow a tail-agnostic policy.
2. The destination register cannot overlap the source register and, when masked, cannot overlap `v0`.
3. The instruction raises an illegal-instruction exception if `vstart` is non-zero.

### 8.6 Vector Iota Instruction

#### 8.6.1 `viota.m`

##### Function

This instruction computes a prefix sum of active mask bits and writes the result to an integer vector register group.

##### Instruction Formats

```asm
viota.m vd, vs2, vm
viota.m vd, vs2, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination integer vector register group |
| `vs2` | Source mask register |
| `vm` | Optional mask control; when present, only masked-in active elements contribute to the prefix sum |

##### Semantics

1. `viota.m` writes to each destination element the number of active source mask elements with value `1` whose index is less than the destination element index.
2. When masked, only elements enabled by `v0` contribute to the sum.
3. The result is zero-extended to fill the destination element when `SEW` is wider than the count; if the count overflows `SEW`, the least-significant `SEW` bits are retained.

##### Assembly Examples

```asm
viota.m v8,  v10
viota.m v12, v14, v0.t
```

- `viota.m v8, v10`: compute an unmasked mask-prefix sum from `v10`.
- `viota.m v12, v14, v0.t`: compute a masked mask-prefix sum from `v14` under `v0`.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r1 = __riscv_viota_m_u32m1(a, vl);
```

##### Notes

1. `viota.m` is commonly paired with scatter operations to implement compress-style indexing.
2. The destination register group cannot overlap the source register and, when masked, cannot overlap `v0`.
3. The instruction raises an illegal-instruction exception if `vstart` is non-zero.

### 8.7 Vector Element Index Instruction

#### 8.7.1 `vid.v`

##### Function

This instruction writes each active element index, from `0` to `vl-1`, to the destination vector register group.

##### Instruction Formats

```asm
vid.v vd, vm
vid.v vd, v0.t
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination integer vector register group |
| `vm` | Optional mask control; when present, only masked-in active elements are written |

##### Semantics

1. `vid.v` writes each active destination element with its own element index.
2. Masking does not change the index value written to active elements; it only controls whether the destination element is updated.
3. The result is zero-extended to fill the destination element when `SEW` is wider than the index value; if the index value overflows `SEW`, the least-significant `SEW` bits are retained.

##### Assembly Examples

```asm
vid.v v16
vid.v v18, v0.t
```

- `vid.v v16`: write unmasked element indices to `v16`.
- `vid.v v18, v0.t`: write element indices under the mask in `v0`.

##### Intrinsics

Common intrinsic forms:

```c
vuint32m1_t r2 = __riscv_vid_v_u32m1(vl);
```

##### Notes

1. The `vs2` field of the encoding must be `v0`; other encodings are reserved.
2. `vid.v` can be implemented using the same datapath as `viota.m` with an implicit all-ones source mask.
3. The destination is an integer vector register group, not a mask register.

## 9. Vector Permutation Instructions

### 9.1 Integer Scalar Move Instructions

#### 9.1.1 `vmv.x.s` / `vmv.s.x`

##### Function

These instructions transfer a single integer value between a scalar `x` register and element `0` of a vector register.

##### Instruction Formats

```asm
vmv.x.s rd, vs2
vmv.s.x vd, rs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `rd` | Destination scalar integer register for `vmv.x.s` |
| `vs2` | Source vector register for `vmv.x.s` |
| `vd` | Destination vector register for `vmv.s.x` |
| `rs1` | Source scalar integer register for `vmv.s.x` |

##### Semantics

1. `vmv.x.s` copies the `SEW`-wide value in `vs2[0]` to the scalar integer register `rd`.
2. If `SEW > XLEN`, `vmv.x.s` transfers only the least-significant `XLEN` bits; if `SEW < XLEN`, the value is sign-extended to `XLEN` bits.
3. `vmv.s.x` copies the scalar integer register `rs1` to element `0` of `vd`; if `SEW < XLEN`, the least-significant `SEW` bits are copied, and if `SEW > XLEN`, the value is sign-extended to `SEW` bits.

##### Assembly Examples

```asm
vmv.x.s a0, v8
vmv.s.x v10, a1
```

- `vmv.x.s a0, v8`: move element `0` of `v8` into scalar register `a0`.
- `vmv.s.x v10, a1`: move scalar register `a1` into element `0` of `v10`.

##### Intrinsics

Common intrinsic forms:

```c
int32_t r1 = __riscv_vmv_x_s_i32m1_i32(a);
vint32m1_t r2 = __riscv_vmv_s_x_i32m1(x, vl);
```

##### Notes

1. These instructions ignore LMUL and vector register group structure and operate only on element `0`.
2. `vmv.x.s` performs its move even if `vstart >= vl` or `vl = 0`.
3. `vmv.s.x` performs no update when `vstart >= vl`; when `vl = 0`, no destination elements are updated.

### 9.2 Floating-Point Scalar Move Instructions

#### 9.2.1 `vfmv.f.s` / `vfmv.s.f`

##### Function

These instructions transfer a single floating-point value between a scalar `f` register and element `0` of a vector register.

##### Instruction Formats

```asm
vfmv.f.s rd, vs2
vfmv.s.f vd, rs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `rd` | Destination scalar floating-point register for `vfmv.f.s` |
| `vs2` | Source vector register for `vfmv.f.s` |
| `vd` | Destination vector register for `vfmv.s.f` |
| `rs1` | Source scalar floating-point register for `vfmv.s.f` |

##### Semantics

1. `vfmv.f.s` copies element `0` of `vs2` to the scalar floating-point register `rd`.
2. When `FLEN > SEW`, `vfmv.f.s` writes the result to `rd` in NaN-boxed form.
3. `vfmv.s.f` copies the low `SEW` bits of the scalar floating-point register `rs1` to element `0` of `vd`.

##### Assembly Examples

```asm
vfmv.f.s fa0, v8
vfmv.s.f v10, fa1
```

- `vfmv.f.s fa0, v8`: move element `0` of `v8` into scalar floating-point register `fa0`.
- `vfmv.s.f v10, fa1`: move scalar floating-point register `fa1` into element `0` of `v10`.

##### Intrinsics

Common intrinsic forms:

```c
float r1 = __riscv_vfmv_f_s_f32m1_f32(a);
vfloat32m1_t r2 = __riscv_vfmv_s_f_f32m1(x, vl);
```

##### Notes

1. These instructions ignore LMUL and vector register group structure and operate only on element `0`.
2. `vfmv.f.s` performs its move even if `vstart >= vl` or `vl = 0`.
3. `vfmv.s.f` performs no update when `vstart >= vl`; when `vl = 0`, no destination elements are updated.

### 9.3 Vector Slide Instructions

#### 9.3.1 `vslideup.vx` / `vslideup.vi`

##### Function

These instructions slide vector elements toward higher indices by a specified offset.

##### Instruction Formats

```asm
vslideup.vx vd, vs2, rs1, vm
vslideup.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group |
| `rs1` | Scalar integer register supplying the slide offset for `.vx` forms |
| `uimm` | Immediate slide offset for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. For active masked-in elements with index `i >= OFFSET`, `vslideup` writes `vd[i] = vs2[i - OFFSET]`.
2. Destination elements with index less than `OFFSET` are left undisturbed.
3. The offset is interpreted as an unsigned value; if it is greater than or equal to `vl`, no destination elements are updated.

##### Assembly Examples

```asm
vslideup.vx v8,  v10, a0
vslideup.vi v12, v14, 3
```

- `vslideup.vx v8, v10, a0`: slide `v10` upward by the runtime offset in `a0`.
- `vslideup.vi v12, v14, 3`: slide `v14` upward by the immediate offset `3`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vslideup_vx_i32m1(d, s, 2, vl);
```

##### Notes

1. The C interface commonly uses the `vx` form with a constant offset; no separate `__riscv_vslideup_vi_*` intrinsic is provided here.
2. `vslideup` is not a general permutation; leading destination elements remain undisturbed.
3. The source and destination register groups must not overlap.

#### 9.3.2 `vslidedown.vx` / `vslidedown.vi`

##### Function

These instructions slide vector elements toward lower indices by a specified offset.

##### Instruction Formats

```asm
vslidedown.vx vd, vs2, rs1, vm
vslidedown.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group |
| `rs1` | Scalar integer register supplying the slide offset for `.vx` forms |
| `uimm` | Immediate slide offset for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. For active masked-in elements with index `i`, `vslidedown` writes `vd[i] = vs2[i + OFFSET]` when `i + OFFSET` is within `VLMAX`.
2. If `i + OFFSET` is greater than or equal to `VLMAX`, the destination element is written as `0`.
3. The offset is interpreted as an unsigned value.

##### Assembly Examples

```asm
vslidedown.vx v16, v18, a1
vslidedown.vi v20, v22, 2
```

- `vslidedown.vx v16, v18, a1`: slide `v18` downward by the runtime offset in `a1`.
- `vslidedown.vi v20, v22, 2`: slide `v22` downward by the immediate offset `2`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r2 = __riscv_vslidedown_vx_i32m1(s, 3, vl);
```

##### Notes

1. The C interface commonly uses the `vx` form with a constant offset; no separate `__riscv_vslidedown_vi_*` intrinsic is provided here.
2. Out-of-range source indices produce zero-filled destination elements.
3. `vslidedown` may read source elements with index greater than or equal to `vl` but less than `VLMAX`.

#### 9.3.3 `vslide1up.vx` / `vfslide1up.vf`

##### Function

These instructions insert a scalar at the beginning of a vector and shift the remaining elements toward higher indices by one position.

##### Instruction Formats

```asm
vslide1up.vx  vd, vs2, rs1, vm
vfslide1up.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group |
| `rs1` | Scalar integer register for `vslide1up.vx`, or scalar floating-point register for `vfslide1up.vf` |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. For active masked-in element `0`, the scalar value from `rs1` is written to `vd[0]`.
2. For active masked-in elements `i > 0`, `vd[i] = vs2[i - 1]`.
3. The last source element is discarded.

##### Assembly Examples

```asm
vslide1up.vx   v24, v26, a2
vfslide1up.vf  v28, v30, fa0
```

- `vslide1up.vx v24, v26, a2`: insert integer scalar `a2` at the front of `v26`.
- `vfslide1up.vf v28, v30, fa0`: insert floating-point scalar `fa0` at the front of `v30`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r3 = __riscv_vslide1up_vx_i32m1(s, x, vl);
vfloat32m1_t r4 = __riscv_vfslide1up_vf_f32m1(sf, y, vl);
```

##### Notes

1. These instructions are useful for streaming window updates and queue-style front insertion.
2. Masking applies to destination elements in the normal way.
3. The source and destination register groups must not overlap.

#### 9.3.4 `vslide1down.vx` / `vfslide1down.vf`

##### Function

These instructions shift vector elements toward lower indices by one position and insert a scalar at the final active position.

##### Instruction Formats

```asm
vslide1down.vx  vd, vs2, rs1, vm
vfslide1down.vf vd, vs2, rs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group |
| `rs1` | Scalar integer register for `vslide1down.vx`, or scalar floating-point register for `vfslide1down.vf` |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. For active masked-in elements `i < vl - 1`, `vd[i] = vs2[i + 1]`.
2. For the final active element `vl - 1`, the scalar value from `rs1` is written.
3. The first source element is discarded.

##### Assembly Examples

```asm
vslide1down.vx   v8,  v10, a3
vfslide1down.vf  v12, v14, fa1
```

- `vslide1down.vx v8, v10, a3`: shift `v10` down and insert integer scalar `a3` at the end.
- `vfslide1down.vf v12, v14, fa1`: shift `v14` down and insert floating-point scalar `fa1` at the end.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r5 = __riscv_vslide1down_vx_i32m1(s, x, vl);
vfloat32m1_t r6 = __riscv_vfslide1down_vf_f32m1(sf, y, vl);
```

##### Notes

1. These instructions are useful for streaming window updates and queue-style tail insertion.
2. Masking applies to destination elements in the normal way.
3. `vfslide1down.vf` may transfer a scalar floating-point value from an `f` register even on implementations with no scalar floating-point unit when vector floating-point is supported.

### 9.4 Vector Register Gather Instructions

#### 9.4.1 `vrgather.vv` / `vrgather.vx` / `vrgather.vi`

##### Function

These instructions gather elements from a source vector register group according to vector, scalar, or immediate indices.

##### Instruction Formats

```asm
vrgather.vv vd, vs2, vs1, vm
vrgather.vx vd, vs2, rs1, vm
vrgather.vi vd, vs2, uimm, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group supplying gathered elements |
| `vs1` | Vector index register group for `.vv` forms |
| `rs1` | Scalar integer register supplying the index for `.vx` forms |
| `uimm` | Immediate index for `.vi` forms |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vrgather.vv` reads indices from `vs1`; each active destination element is written as `vs2[index]` when the index is less than `VLMAX`.
2. `vrgather.vx` and `vrgather.vi` splat a single source element to all active destination elements.
3. If an index is greater than or equal to `VLMAX`, the destination element is written as `0`.

##### Assembly Examples

```asm
vrgather.vv v8,  v10, v12
vrgather.vx v14, v16, a0
vrgather.vi v18, v20, 3
```

- `vrgather.vv v8, v10, v12`: gather from `v10` using per-element indices from `v12`.
- `vrgather.vx v14, v16, a0`: splat one element of `v16` selected by scalar index `a0`.
- `vrgather.vi v18, v20, 3`: splat element `3` of `v20`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r1 = __riscv_vrgather_vv_i32m1(a, idx32, vl);
vint32m1_t r2 = __riscv_vrgather_vx_i32m1(a, 3, vl);
```

##### Notes

1. In the `.vx` and `.vi` forms, the index is treated as an unsigned integer; if `XLEN > SEW`, it is not truncated to `SEW` bits.
2. The C interface commonly uses the `vx` form with a constant index; no separate `__riscv_vrgather_vi_*` intrinsic is provided here.
3. The destination register group must not overlap either source register group.

#### 9.4.2 `vrgatherei16.vv`

##### Function

This instruction gathers elements from a source vector register group using 16-bit vector indices.

##### Instruction Formats

```asm
vrgatherei16.vv vd, vs2, vs1, vm
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group supplying gathered elements |
| `vs1` | Vector index register group with `EEW=16` |
| `vm` | Mask control, written as `v0.t` or omitted |

##### Semantics

1. `vrgatherei16.vv` behaves like `vrgather.vv`, but the indices in `vs1` are encoded with `EEW=16`.
2. The data vector `vs2` still uses the current `SEW/LMUL`, while the index vector uses `EEW=16` and `EMUL = (16/SEW) * LMUL`.
3. If an index is greater than or equal to `VLMAX`, the destination element is written as `0`.

##### Assembly Examples

```asm
vrgatherei16.vv v22, v24, v26
```

- `vrgatherei16.vv v22, v24, v26`: gather from `v24` using 16-bit indices from `v26`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r3 = __riscv_vrgatherei16_vv_i32m1(a, idx16, vl);
```

##### Notes

1. `vrgatherei16.vv` can index up to 64K elements, unlike `vrgather.vv` with `SEW=8`, which can address only elements `0-255`.
2. It can also reduce index register storage when `SEW > 16`.
3. The destination register group must not overlap either source register group.

### 9.5 Vector Compress Instruction

#### 9.5.1 `vcompress.vm`

##### Function

This instruction packs the elements of a source vector selected by a source mask register into contiguous elements at the start of the destination vector register group.

##### Instruction Formats

```asm
vcompress.vm vd, vs2, vs1
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group supplying data elements |
| `vs1` | Source mask register selecting which elements are packed |

##### Semantics

1. `vcompress.vm` examines the first `vl` elements of `vs2` and packs those whose corresponding `vs1` mask bits are `1` into the lowest positions of `vd`.
2. The relative order of selected elements is preserved.
3. Destination elements after the packed region are treated as tail elements and follow the current tail policy.

##### Assembly Examples

```asm
vcompress.vm v28, v30, v0
```

- `vcompress.vm v28, v30, v0`: pack the elements of `v30` selected by mask register `v0` into the beginning of `v28`.

##### Intrinsics

Common intrinsic forms:

```c
vint32m1_t r4 = __riscv_vcompress_vm_i32m1(a, mask, vl);
```

##### Notes

1. `vcompress.vm` is encoded as an unmasked instruction; the masked encoding is reserved.
2. The destination register group must not overlap the data source register group or the source mask register.
3. Executing `vcompress.vm` with a non-zero `vstart` raises an illegal-instruction exception.

### 9.6 Whole Vector Register Move

#### 9.6.1 `vmv1r.v` / `vmv2r.v` / `vmv4r.v` / `vmv8r.v`

##### Function

These instructions copy whole vector registers, or whole vector register groups, without changing the current `vl` setting.

##### Instruction Formats

```asm
vmv1r.v vd, vs2
vmv2r.v vd, vs2
vmv4r.v vd, vs2
vmv8r.v vd, vs2
```

##### Parameters

| Parameter | Meaning |
|---|---|
| `vd` | Destination vector register group |
| `vs2` | Source vector register group |

##### Semantics

1. `vmv1r.v`, `vmv2r.v`, `vmv4r.v`, and `vmv8r.v` copy `1`, `2`, `4`, or `8` whole vector registers respectively.
2. The instructions operate as if `EEW = SEW`, `EMUL = NREG`, and `evl = EMUL * VLEN / SEW`, where `NREG` is the number of registers copied.
3. Unlike ordinary vector instructions, no elements are written only when `vstart >= evl`; the usual `vstart >= vl` rule does not apply.

##### Assembly Examples

```asm
vmv1r.v v1,  v2
vmv2r.v v10, v12
vmv4r.v v4,  v8
vmv8r.v v0,  v8
```

- `vmv1r.v v1, v2`: copy one whole vector register.
- `vmv2r.v v10, v12`: copy two whole vector registers.
- `vmv4r.v v4, v8`: copy four whole vector registers.
- `vmv8r.v v0, v8`: copy eight whole vector registers.

##### Intrinsics

No standard C intrinsic form is provided here.

##### Notes

1. The register numbers of both source and destination must be aligned for the chosen group size; other encodings are reserved.
2. If `vd == vs2`, the instruction is an architectural NOP, but it can still serve as a hint to implementations that reorganize data internally.
3. These instructions are intended to help compilers and runtimes shuffle vector register groups without needing to know or modify `vl`.
