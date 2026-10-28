"""Build the CMSIS-NN (IME extension) dataset.

One row per int8 unit-test file of CMSIS-NN (Tests/UnitTest/TestCases/
test_arm_*s8*). The row's `code` is the library file implementing the tested
operator; the harness calls every test function in that file CNN_REPEAT
times with the upstream TFLite-generated shapes and reference outputs and
prints the number of failed checks.

    python3 -I benchmark/cmsisnn/build.py --cmsis <CMSIS-NN checkout> [--repeat-json reps.json]

The library sources, the used tests and their test data are copied to src/;
rows refer to them through the "{src}" placeholder that the runner replaces.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from amalgamate import amalgamate  # noqa: E402
from compact import compact, prune, squeeze  # noqa: E402

# Generic C paths only: no Arm DSP/MVE/NEON or float APIs.
UNDEF = ["ARM_MATH_MVEI", "ARM_MATH_DSP", "ARM_MATH_AUTOVECTORIZE", "__ARM_FEATURE_MVE", "ARM_MATH_MVE_FLOAT16",
         "ARM_MATH_MVEF", "ARM_NN_ENABLE_F32", "ARM_NN_ENABLE_F16", "ARM_NN_FLOAT_API_ENABLED", "__ARMCC_VERSION",
         "__ICCARM__", "ARM_MATH_BIG_ENDIAN", "__ARM_FEATURE_DSP", "CMSIS_NN_USE_REQUANTIZE_INLINE_ASSEMBLY",
         "ARM_GCC_12_2_ICE", "__ARM_ACLE", "__DOXYGEN__", "_MSC_VER", "ARM_FLOAT16_SUPPORTED"]
# Header helpers kept even when the original file does not use them
# (optimized versions commonly call them).
KEEP = " arm_nn_requantize arm_nn_requantize_s64 arm_nn_read_s8x4 arm_nn_read_s8x4_ia "
INCLUDE_RE = re.compile(r'^#include\s+["<](?:arm_nn\w*\.h|\.\./\w+\.h|Internal/\w+\.h)[">]\n', re.M)


def local(text: str) -> str:
    """Point project includes at the single support header."""
    text = INCLUDE_RE.sub("", text)
    return '#include "cmsisnn.h"\n' + text if "cmsisnn.h" not in text else text
SRC = HERE / "src"
# Network-level tests with no single target kernel.
SKIP = {"test_arm_ds_cnn_l_s8", "test_arm_ds_cnn_s_s8"}
# Test file -> library file, where the names differ.
TARGET = {"test_arm_grouped_convolve_s8": "arm_convolve_s8.c",
          "test_arm_reverse_transpose_conv_s8": "arm_transpose_conv_s8.c"}

UNITY_STUB = """#pragma once
/* Minimal Unity replacement: count failed checks instead of aborting. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
extern int cnn_fail;
#define TEST_ASSERT_EQUAL(a, b) do { if ((a) != (b)) cnn_fail++; } while (0)
#define TEST_ASSERT_TRUE(x) do { if (!(x)) cnn_fail++; } while (0)
"""

HARNESS = """#include <stdio.h>
#ifndef CNN_REPEAT
#define CNN_REPEAT 1
#endif
int cnn_fail;
{decls}

int main(void)
{{
  for (int r = 0; r < CNN_REPEAT; r++) {{
{calls}
  }}
  printf("failed %d\\n", cnn_fail);
  return 0;
}}
"""

# Network-sized workloads that replace the unit tests' toy shapes for the
# matrix-multiply operators: random int8 data, output hashed.
WORK_PRELUDE = """#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arm_nnfunctions.h"
#ifndef CNN_REPEAT
#define CNN_REPEAT 1
#endif
static uint32_t seed = 1;
static void fill8(int8_t *p, long n) { for (long i = 0; i < n; i++) { seed = seed * 1103515245u + 12345u; p[i] = (int8_t)(seed >> 16); } }
static void fill32(int32_t *p, long n, int range) { for (long i = 0; i < n; i++) { seed = seed * 1103515245u + 12345u; p[i] = (int32_t)((seed >> 8) % (2 * range + 1)) - range; } }
static void report(const int8_t *p, long n) { uint64_t h = 1469598103934665603ull; for (long i = 0; i < n; i++) h = (h ^ (uint8_t)p[i]) * 1099511628211ull; printf("out %016llx\\n", (unsigned long long)h); }
"""

WORKLOADS = {
    # 1x1 convolution of a MobileNet-v1 layer: 56x56x64 -> 128 channels.
    "test_arm_convolve_1x1_s8_fast": """
int main(void)
{
  enum { H = 56, W = 56, CI = 64, CO = 128 };
  int8_t *in = malloc(H * W * CI), *flt = malloc(CO * CI), *out = malloc(H * W * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, H * W * CI); fill8(flt, CO * CI); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -9; }
  cmsis_nn_context ctx = {NULL, 0};
  cmsis_nn_conv_params cp = {.input_offset = 3, .output_offset = -2, .stride = {1, 1}, .padding = {0, 0},
                             .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, H, W, CI}, fd = {CO, 1, 1, CI}, bd = {1, 1, 1, CO}, od = {1, H, W, CO};
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_convolve_1x1_s8_fast(&ctx, &cp, &qp, &id, in, &fd, flt, &bd, bias, &od, out);
  report(out, H * W * CO);
  return 0;
}
""",
    # 3x3 convolution, 28x28x64 -> 64 channels, stride 1, pad 1 (ResNet-style block).
    "test_arm_convolve_s8": """
int main(void)
{
  enum { H = 28, W = 28, CI = 64, CO = 64, KH = 3, KW = 3, G = 1 };
  int8_t *in = malloc(H * W * CI), *flt = malloc(CO * KH * KW * (CI / G)), *out = malloc(H * W * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, H * W * CI); fill8(flt, CO * KH * KW * (CI / G)); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -11; }
  cmsis_nn_conv_params cp = {.input_offset = 3, .output_offset = -2, .stride = {1, 1}, .padding = {1, 1},
                             .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, H, W, CI}, fd = {CO, KH, KW, CI / G}, bd = {1, 1, 1, CO}, od = {1, H, W, CO};
  cmsis_nn_context ctx = {NULL, arm_convolve_s8_get_buffer_size(&id, &fd)};
  ctx.buf = calloc(1, ctx.size);
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_convolve_s8(&ctx, &cp, &qp, &id, in, &fd, flt, &bd, bias, NULL, &od, out);
  report(out, H * W * CO);
  return 0;
}
""",
    # Grouped 3x3 convolution, 28x28x128 -> 128 channels in 4 groups (ResNeXt-style).
    "test_arm_grouped_convolve_s8": """
int main(void)
{
  enum { H = 28, W = 28, CI = 128, CO = 128, KH = 3, KW = 3, G = 4 };
  int8_t *in = malloc(H * W * CI), *flt = malloc(CO * KH * KW * (CI / G)), *out = malloc(H * W * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, H * W * CI); fill8(flt, CO * KH * KW * (CI / G)); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -11; }
  cmsis_nn_conv_params cp = {.input_offset = 3, .output_offset = -2, .stride = {1, 1}, .padding = {1, 1},
                             .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, H, W, CI}, fd = {CO, KH, KW, CI / G}, bd = {1, 1, 1, CO}, od = {1, H, W, CO};
  cmsis_nn_context ctx = {NULL, arm_convolve_s8_get_buffer_size(&id, &fd)};
  ctx.buf = calloc(1, ctx.size);
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_convolve_s8(&ctx, &cp, &qp, &id, in, &fd, flt, &bd, bias, NULL, &od, out);
  report(out, H * W * CO);
  return 0;
}
""",
    # 1xN convolution over a long 1-D sequence: 1x1024x32, 9 taps -> 64 channels (keyword spotting / audio).
    "test_arm_convolve_1_x_n_s8": """
int main(void)
{
  enum { W = 1024, CI = 32, CO = 64, KW = 9 };
  int8_t *in = malloc(W * CI), *flt = malloc(CO * KW * CI), *out = malloc(W * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, W * CI); fill8(flt, CO * KW * CI); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -10; }
  cmsis_nn_conv_params cp = {.input_offset = 3, .output_offset = -2, .stride = {1, 1}, .padding = {4, 0},
                             .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, 1, W, CI}, fd = {CO, 1, KW, CI}, bd = {1, 1, 1, CO}, od = {1, 1, W, CO};
  cmsis_nn_context ctx = {NULL, arm_convolve_s8_get_buffer_size(&id, &fd)};
  ctx.buf = calloc(1, ctx.size);
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_convolve_1_x_n_s8(&ctx, &cp, &qp, &id, in, &fd, flt, &bd, bias, &od, out);
  report(out, W * CO);
  return 0;
}
""",
    # Transposed convolution (2x upsampling): 14x14x64 -> 27x27x32, 3x3, stride 2, pad 1.
    "test_arm_transpose_conv_s8": """
int main(void)
{
  enum { IH = 14, IW = 14, CI = 64, CO = 32, KH = 3, KW = 3, S = 2, P = 1, OH = 27, OW = 27 };
  int8_t *in = malloc(IH * IW * CI), *flt = malloc(CO * KH * KW * CI), *out = malloc(OH * OW * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, IH * IW * CI); fill8(flt, CO * KH * KW * CI); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -10; }
  cmsis_nn_transpose_conv_params tp = {.input_offset = 3, .output_offset = -2, .stride = {S, S}, .padding = {P, P},
                                       .padding_offsets = {0, 0}, .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, IH, IW, CI}, fd = {CO, KH, KW, CI}, bd = {1, 1, 1, CO}, od = {1, OH, OW, CO};
  /* Direct-path scratch size (get_buffer_size returns the reverse-conv size for wide inputs). */
  cmsis_nn_context ctx = {NULL, ((IW - 1) * S + (KW > S ? KW : S)) * CO * (KH > S ? KH : S) * 4}, octx = {NULL, 0};
  ctx.buf = calloc(1, ctx.size);
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_transpose_conv_s8(&ctx, &octx, &tp, &qp, &id, in, &fd, flt, &bd, bias, &od, out);
  report(out, OH * OW * CO);
  return 0;
}
""",
    # Stride-1 transposed convolution of a decoder: 24x24x48 -> 22x22x48, 5x5, pad 2.
    "test_arm_reverse_transpose_conv_s8": """
int main(void)
{
  enum { IH = 24, IW = 24, CI = 48, CO = 48, KH = 5, KW = 5, S = 1, P = 2, OH = 22, OW = 22 };
  int8_t *in = malloc(IH * IW * CI), *flt = malloc(CO * KH * KW * CI), *out = malloc(OH * OW * CO);
  int32_t *bias = malloc(CO * 4), *mult = malloc(CO * 4), *shift = malloc(CO * 4);
  fill8(in, IH * IW * CI); fill8(flt, CO * KH * KW * CI); fill32(bias, CO, 4096);
  for (int i = 0; i < CO; i++) { mult[i] = 1073741824 + (i << 20); shift[i] = -10; }
  cmsis_nn_transpose_conv_params tp = {.input_offset = 3, .output_offset = -2, .stride = {S, S}, .padding = {P, P},
                                       .padding_offsets = {0, 0}, .dilation = {1, 1}, .activation = {-128, 127}};
  cmsis_nn_per_channel_quant_params qp = {mult, shift};
  cmsis_nn_dims id = {1, IH, IW, CI}, fd = {CO, KH, KW, CI}, bd = {1, 1, 1, CO}, od = {1, OH, OW, CO};
  /* Direct-path scratch size (get_buffer_size returns the reverse-conv size for wide inputs). */
  cmsis_nn_context ctx = {NULL, ((IW - 1) * S + (KW > S ? KW : S)) * CO * (KH > S ? KH : S) * 4}, octx = {NULL, 0};
  ctx.buf = calloc(1, ctx.size);
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_transpose_conv_s8(&ctx, &octx, &tp, &qp, &id, in, &fd, flt, &bd, bias, &od, out);
  report(out, OH * OW * CO);
  return 0;
}
""",
    # Fully connected layer, 32 batches, 1024 -> 1000 (classifier head).
    "test_arm_fully_connected_s8": """
int main(void)
{
  enum { B = 32, K = 1024, N = 1000 };
  int8_t *in = malloc(B * K), *w = malloc(N * K), *out = malloc(B * N);
  int32_t *bias = malloc(N * 4);
  fill8(in, B * K); fill8(w, N * K); fill32(bias, N, 4096);
  cmsis_nn_context ctx = {NULL, 0};
  cmsis_nn_fc_params fp = {.input_offset = 5, .filter_offset = 0, .output_offset = -3, .activation = {-128, 127}};
  cmsis_nn_per_tensor_quant_params qp = {1518500250, -12};
  cmsis_nn_dims id = {B, 1, 1, K}, fd = {K, 1, 1, N}, bd = {1, 1, 1, N}, od = {B, 1, 1, N};
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_fully_connected_s8(&ctx, &fp, &qp, &id, in, &fd, w, &bd, bias, &od, out);
  report(out, B * N);
  return 0;
}
""",
    # Attention scores Q x K^T: 8 heads, 128 tokens, head size 64.
    "test_arm_batch_matmul_s8": """
int main(void)
{
  enum { HEADS = 8, T = 128, D = 64 };
  int8_t *q = malloc(HEADS * T * D), *k = malloc(HEADS * T * D), *out = malloc(HEADS * T * T);
  fill8(q, HEADS * T * D); fill8(k, HEADS * T * D);
  cmsis_nn_context ctx = {NULL, 0};
  const cmsis_nn_bmm_params bp = {false, true, {.input_offset = 2, .filter_offset = -1, .output_offset = 1,
                                                .activation = {-128, 127}}};
  cmsis_nn_per_tensor_quant_params qp = {1518500250, -10};
  cmsis_nn_dims ld = {1, HEADS, T, D}, rd = {1, HEADS, T, D}, od = {1, HEADS, T, T};
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_batch_matmul_s8(&ctx, &bp, &qp, &ld, q, &rd, k, &od, out);
  report(out, HEADS * T * T);
  return 0;
}
""",
    # Speech LSTM layer, time-major: 16 streams, 16 steps, 256 inputs, 256 hidden units.
    "test_arm_lstm_unidirectional_s8": """
static cmsis_nn_lstm_gate gate(int32_t *ksum_in, int32_t *ksum_h, int8_t *wi, int8_t *wh, int act)
{
  cmsis_nn_lstm_gate g = {1300000000, -4, wi, ksum_in, 1300000000, -4, wh, ksum_h, NULL, act};
  return g;
}
int main(void)
{
  enum { B = 16, T = 16, I = 256, H = 256, IZP = 3, OZP = -2 };
  int8_t *in = malloc(T * B * I), *out = malloc(T * B * H), *w[8];
  int32_t *ks[8], *bias = malloc(H * 4);
  fill8(in, T * B * I); fill32(bias, H, 2048);
  for (int i = 0; i < 8; i++)
  {
    int k = i < 4 ? I : H;
    w[i] = malloc(H * k); fill8(w[i], H * k); ks[i] = malloc(H * 4);
    arm_vector_sum_s8(ks[i], k, H, w[i], i < 4 ? IZP : -OZP, 0, i < 4 ? bias : NULL);
  }
  cmsis_nn_lstm_params p = {.time_major = 1, .batch_size = B, .time_steps = T, .input_size = I, .hidden_size = H,
                            .input_offset = IZP, .forget_to_cell_multiplier = 1073741824, .forget_to_cell_shift = -14,
                            .input_to_cell_multiplier = 1073741824, .input_to_cell_shift = -15, .cell_clip = 32767,
                            .cell_scale_power = -14, .output_multiplier = 1441324494, .output_shift = -22,
                            .output_offset = OZP};
  p.forget_gate = gate(ks[0], ks[4], w[0], w[4], ARM_SIGMOID);
  p.input_gate = gate(ks[1], ks[5], w[1], w[5], ARM_SIGMOID);
  p.cell_gate = gate(ks[2], ks[6], w[2], w[6], ARM_TANH);
  p.output_gate = gate(ks[3], ks[7], w[3], w[7], ARM_SIGMOID);
  cmsis_nn_lstm_context c = {malloc(B * H * 2), malloc(B * H * 2), malloc(B * H * 2), NULL};
  for (int r = 0; r < CNN_REPEAT; r++)
    arm_lstm_unidirectional_s8(in, out, &p, &c);
  report(out, T * B * H);
  return 0;
}
""",
    # Keyword-spotting SVDF layer: 32 streams, 512 inputs, 1024 features (rank 2), 16-frame memory; 4 frames.
    "test_arm_svdf_s8": """
int main(void)
{
  enum { B = 32, I = 512, F = 1024, R = 2, TB = 16, FRAMES = 4 };
  int8_t *in = malloc(FRAMES * B * I), *wf = malloc(F * I), *wt = malloc(F * TB), *st = malloc(B * F * TB);
  int8_t *out = malloc(B * F / R);
  int32_t *bias = malloc(F / R * 4);
  fill8(in, FRAMES * B * I); fill8(wf, F * I); fill8(wt, F * TB); fill32(bias, F / R, 4096);
  cmsis_nn_context ctx = {malloc(F * 4), F * 4}, actx = {malloc(B * F * 4), B * F * 4}, octx = {malloc(B * F * 2), B * F * 2};
  cmsis_nn_svdf_params sp = {.rank = R, .input_offset = 4, .output_offset = -1, .input_activation = {-128, 127},
                             .output_activation = {-128, 127}};
  cmsis_nn_per_tensor_quant_params qi = {1717987072, -11}, qo = {1099511552, -12};
  cmsis_nn_dims id = {B, I, 1, 1}, sd = {0}, fd = {F, 1, 1, I}, td = {F, TB, 1, 1}, bd = {0}, od = {B, F / R, 1, 1};
  for (int r = 0; r < CNN_REPEAT; r++)
  {
    memset(st, 0, B * F * TB);
    for (int f = 0; f < FRAMES; f++)
      arm_svdf_s8(&ctx, &actx, &octx, &sp, &qi, &qo, &id, in + f * B * I, &sd, st, &fd, wf, &td, wt, &bd, bias, &od, out);
  }
  report(out, B * F / R);
  report(st, B * F * TB);
  return 0;
}
""",
    # Same SVDF layer with an int16 state and time weights.
    "test_arm_svdf_state_s16_s8": """
int main(void)
{
  enum { B = 32, I = 512, F = 1024, R = 2, TB = 16, FRAMES = 4 };
  int8_t *in = malloc(FRAMES * B * I), *wf = malloc(F * I), *out = malloc(B * F / R);
  int16_t *wt = malloc(F * TB * 2), *st = malloc(B * F * TB * 2);
  int32_t *bias = malloc(F / R * 4);
  fill8(in, FRAMES * B * I); fill8(wf, F * I); fill8((int8_t *)wt, F * TB * 2); fill32(bias, F / R, 4096);
  for (int i = 0; i < F * TB; i++) wt[i] >>= 4;
  cmsis_nn_context actx = {malloc(B * F * 4), B * F * 4}, octx = {malloc(B * F * 2), B * F * 2};
  cmsis_nn_svdf_params sp = {.rank = R, .input_offset = 4, .output_offset = -1, .input_activation = {-32768, 32767},
                             .output_activation = {-128, 127}};
  cmsis_nn_per_tensor_quant_params qi = {1717987072, -4}, qo = {1099511552, -18};
  cmsis_nn_dims id = {B, I, 1, 1}, sd = {0}, fd = {F, 1, 1, I}, td = {F, TB, 1, 1}, bd = {0}, od = {B, F / R, 1, 1};
  for (int r = 0; r < CNN_REPEAT; r++)
  {
    memset(st, 0, B * F * TB * 2);
    for (int f = 0; f < FRAMES; f++)
      arm_svdf_state_s16_s8(&actx, &octx, &sp, &qi, &qo, &id, in + f * B * I, &sd, st, &fd, wf, &td, wt, &bd, bias, &od, out);
  }
  report(out, B * F / R);
  report((int8_t *)st, B * F * TB * 2);
  return 0;
}
""",
}

TEST_FN_RE = re.compile(r"^void\s+(\w+)\s*\(\s*void\s*\)\s*$", re.M)
DATA_RE = re.compile(r'#include\s+"\.\./TestData/(\w+)/')
DEF_RE = re.compile(r"^[0-9a-f]+ [TDBSRC] _?(\w+)$")
UND_RE = re.compile(r"^\s+U _?(\w+)$")


def vendor(cmsis: Path) -> list[Path]:
    """Copy library, int8 tests and their test data into src/; return the test files."""
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.copytree(cmsis / "Include", SRC / "Include")
    shutil.copytree(cmsis / "Source", SRC / "Source", ignore=shutil.ignore_patterns("CMakeLists.txt", "Bindings", "*_f16.c", "*_f32.c"))
    shutil.copy(cmsis / "LICENSE", SRC / "LICENSE")
    cases = cmsis / "Tests/UnitTest/TestCases"
    shutil.copytree(cases / "Utils", SRC / "tests/Utils")
    (SRC / "tests/unity.h").write_text(UNITY_STUB)
    tests, data = [], set()
    for d in sorted(cases.glob("test_arm_*s8*")):
        for f in sorted(d.glob("test_arm_*.c")):
            if f.stem in SKIP:
                continue
            dst = SRC / "tests" / d.name / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
            tests.append(dst)
            data |= set(DATA_RE.findall(f.read_text()))
    for name in sorted(data):
        shutil.copytree(cases / "TestData" / name, SRC / "tests/TestData" / name)
    return tests


def symbols(cc: str, path: Path, obj: Path, flags: list[str]) -> tuple[set, set]:
    subprocess.run([cc, "-c", "-O0", "-w", *flags, str(path), "-o", str(obj)], check=True)
    out = subprocess.run(["nm", str(obj)], check=True, capture_output=True, text=True).stdout
    defs, undef = set(), set()
    for line in out.splitlines():
        if m := DEF_RE.match(line):
            defs.add(m.group(1))
        elif m := UND_RE.match(line):
            undef.add(m.group(1))
    return defs, undef


def closure(start: set, table: dict, skip: str) -> list[str]:
    owner = {}
    for name, (defs, _) in table.items():
        for s in defs:
            owner.setdefault(s, name)
    need, seen, todo = set(), set(), set(start)
    while todo:
        s = todo.pop()
        if s in seen:
            continue
        seen.add(s)
        f = owner.get(s)
        if f is None or f in need:
            continue
        need.add(f)
        todo |= table[f][1]
    need.discard(skip)
    return sorted(need)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmsis", required=True)
    ap.add_argument("--cc", default="cc")
    ap.add_argument("--repeat-json", default=str(HERE / "repeat.json"))
    ap.add_argument("--output", default=str(HERE / "dataset.jsonl"))
    args = ap.parse_args()
    reps = json.loads(Path(args.repeat_json).read_text()) if args.repeat_json else {}
    tests = vendor(Path(args.cmsis))
    flags = [f"-I{SRC / 'Include'}", f"-I{SRC / 'tests'}"]
    lib = {p.relative_to(SRC).as_posix(): p for p in sorted((SRC / "Source").rglob("*.c"))}
    by_name = {Path(k).name: k for k in lib}
    global HEADER
    internal = "".join(f'#include "Internal/{p.name}"\n' for p in sorted((SRC / "Include/Internal").glob("*.h"))
                       if not re.search(r"_f(16|32)|_flt", p.name))
    HEADER = INCLUDE_RE.sub("", compact(amalgamate([("cmsisnn.h", '#include "arm_nnfunctions.h"\n#include "arm_nnsupportfunctions.h"\n'
                                                     '#include "arm_nn_tables.h"\n' + internal)],
                                      [SRC / "Include"]), UNDEF))
    rows = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        table = {k: symbols(args.cc, p, td / (p.stem + ".o"), flags) for k, p in lib.items()}
        for test in tests:
            name = test.stem[len("test_"):]
            target = by_name.get(TARGET.get(test.stem, name + ".c"))
            if target is None:
                print("no target for", test.stem)
                continue
            rel = test.relative_to(SRC).as_posix()
            if test.stem in WORKLOADS:
                harness = WORK_PRELUDE + WORKLOADS[test.stem]
                hpath = td / "harness.c"
                hpath.write_text(harness)
                _, tund = symbols(args.cc, hpath, td / "harness.o", flags)
                tests_src = []
            else:
                fns = TEST_FN_RE.findall(test.read_text())
                harness = HARNESS.format(decls="\n".join(f"void {f}(void);" for f in fns),
                                         calls="\n".join(f"    {f}();" for f in fns))
                _, tund = symbols(args.cc, test, td / (test.stem + ".o"), flags)
                tests_src = [f"{{src}}/{rel}"]
            deps = closure(tund | table[target][1], table, target)
            test_text = "" if not tests_src else test.read_text().replace("#include <unity.h>", '#include "unity.h"')
            code = local(compact(lib[target].read_text(), UNDEF))
            libc = "\n".join(local(compact(lib[d].read_text(), UNDEF)) for d in deps)
            harness_c = local(compact(amalgamate([(str(test), test_text)] if test_text else [], [SRC / "tests"]) + "\n" + harness
                                      if test_text else harness, UNDEF))
            header = squeeze(prune(HEADER, code + libc + harness_c + KEEP))
            files = {"cmsisnn.h": header, "harness.c": harness_c}
            if libc.strip():
                files["lib.c"] = libc
            rows.append({
                "id": f"cmsisnn/{name}",
                "suite": "cmsisnn",
                "extension": "ime",
                "target_file": Path(target).name,
                "code": code,
                "files": files,
                "compile_sources": [k for k in ("harness.c", "lib.c") if k in files],
                "compile_defs": f"-w -DCNN_REPEAT={int(reps.get(name, 1))}",
                "output_filter": "",
                "preserve_functions": [],
                "required_functions": [],
            })
    # Keep only the programs listed for this suite in classes.json.
    tasked = set().union(*json.loads((HERE.parent / "classes.json").read_text())["cmsisnn"].values())
    rows = [r for r in rows if r["id"] in tasked]
    with open(args.output, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
