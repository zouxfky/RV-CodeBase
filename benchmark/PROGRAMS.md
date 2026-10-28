# Benchmark Programs

Each benchmark suite is evaluated on one target extension, and each program is one task. The lists are in [classes.json](classes.json), which the runners read.

| Suite | Source | Target extension | Programs |
|---|---|---|---|
| TSVC | TSVC_2 (github.com/UoB-HPC/TSVC_2) | RVV | 135 |
| Mbed TLS | Mbed TLS 3.6.2, one program per algorithm in programs/test/benchmark.c | B | 27 |
| TACLeBench | TACLeBench (kernel, sequential, app) | Zicond | 26 |
| CMSIS-NN | CMSIS-NN, one program per int8 unit-test file | IME | 21 |
| **Total** | | | **209** |

Selection criteria:

- **RVV**: a loop with data parallelism that can be strip-mined (masks, gather/scatter, reductions and compress allowed). Not counted: true recurrences, prefix scans, libm calls, early exits, pure memcpy.
- **B**: real use of rotates, byte swap, clz/ctz/cpop, orc.b, andn/orn/xnor, carry-less multiply, single-bit ops, or integer min/max.
- **Zicond**: data-dependent branches that select integer values (indices, counters, flags, corrections, carries) and can become branch-free.
- **IME**: int8 neural-network operators whose time is spent in GEMM-shaped loop nests (C += A·B), including convolutions lowered to GEMM, batched FC, and LSTM/SVDF gates, plus the pooling, padding, activation and softmax operators of the same library.

## TSVC (135, RVV)

All float. Of the 151 TSVC_2 kernels, 16 are left out because RVV cannot speed them up:
- linear or nonlinear recurrences: s321, s322, s323, s2111, s232, s256, s257, s222
- prefix scans: s112, s221, s242, s3112
- no array work or only calls: s317, s31111
- libm calls: s451
- `exit()` inside the loop: s481

## Mbed TLS (27, B)

The target file is the library file with the hot loop; the harness runs the benchmark.c call on a 16 KB buffer. Each program is built with only the modules it needs enabled. Left out: rsa, ecdsa, ecdh (over 6000 lines) and poly1305 (64-bit multiply-accumulate, no B pattern).

| Program | Target |
|---|---|
| aes_cbc | aes.c |
| aes_ccm | aes.c |
| aes_cfb128 | aes.c |
| aes_cfb8 | aes.c |
| aes_cmac | aes.c |
| aes_ctr | aes.c |
| aes_gcm | gcm.c |
| aes_xts | aes.c |
| aria | aria.c |
| camellia | camellia.c |
| chacha20 | chacha20.c |
| chachapoly | chacha20.c |
| ctr_drbg | aes.c |
| des | des.c |
| des3 | des.c |
| des3_cmac | des.c |
| dhm | bignum_core.c |
| hmac_drbg | sha256.c |
| md5 | md5.c |
| ripemd160 | ripemd160.c |
| sha1 | sha1.c |
| sha256 | sha256.c |
| sha3_224 | sha3.c |
| sha3_256 | sha3.c |
| sha3_384 | sha3.c |
| sha3_512 | sha3.c |
| sha512 | sha512.c |

B covers rotates (all hashes and ARX ciphers), byte swap (big-endian loads), andn (SHA-3 chi, SHA-2 Ch/Maj), byte extraction in table-based ciphers, and carry-less multiply in GHASH. In dhm the time goes to bignum carry chains and multiply-accumulate loops.

## TACLeBench (26, Zicond: kernel 15, sequential 10, app 1)

Left out: programs over 2800 lines (anagram, audiobeam, mpeg2, rijndael_dec, rijndael_enc, susan, powerwindow), and programs with no task, either because no Zicond pattern fits or because the time is spent outside the target file (fork-based harness, volatile accesses, fixed support library): ammunition, cjpeg_wrbmp, complex_updates, cosf, cubic, deg2rad, epic, fac, fft, filterbank, fir2dim, fmref, g723_enc, huff_dec, iir, lms, ludcmp, petrinet, rad2deg, recursion, st.

Programs: adpcm_dec, adpcm_enc, binarysearch, bitcount, bitonic, bsort, cjpeg_transupp, countnegative, dijkstra, gsm_dec, gsm_enc, h264_dec, huff_enc, insertsort, isqrt, jfdctint, lift, matrix1, md5, minver, ndes, pm, prime, quicksort, sha, statemate.

## CMSIS-NN (21, IME)

The target file is the operator's library file; the harness runs every test function of the upstream unit test (TFLite-generated shapes and reference outputs) and prints the number of failed checks. Left out: the ds_cnn_* network tests, and arm_elementwise_add_s8, arm_elementwise_mul_s8, arm_transpose_s8 (elementwise or pure data movement).

Programs: arm_convolve_s8, arm_grouped_convolve_s8 (target arm_convolve_s8.c), arm_convolve_1x1_s8_fast, arm_convolve_1_x_n_s8, arm_transpose_conv_s8, arm_reverse_transpose_conv_s8 (target arm_transpose_conv_s8.c), arm_batch_matmul_s8, arm_fully_connected_s8, arm_lstm_unidirectional_s8, arm_svdf_s8, arm_svdf_state_s16_s8, arm_depthwise_conv_s8, arm_depthwise_conv_s8_opt, arm_depthwise_conv_3x3_s8, arm_avgpool_s8, arm_max_pool_s8, arm_pad_s8, arm_maximum_s8, arm_minimum_s8, arm_softmax_s8, arm_softmax_s8_s16.
