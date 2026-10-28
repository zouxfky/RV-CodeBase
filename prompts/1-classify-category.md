You are doing top-level category classification for a code dataset used for RISC-V extension-guided optimization.

Your task is to classify the sample into exactly one of these four categories, according to its primary computational characteristics:

- Numerical Computation
- Bit-level Computation
- Control-intensive Computation
- Machine Learning

Reference rules and example subcategories:

{classification_rule}

How to decide:

- Use all available information together:
  - `quertion`
  - `tags`
  - `solution`
- Use `{classification_rule}` as the classification reference.
- Focus on the hot computation of the sample, i.e., the part that dominates execution time, not on the surrounding I/O or setup code.
- Choose `Numerical Computation` when the hot computation is arithmetic over arrays, vectors, or matrices that can be processed element-wise or as reductions.
- Choose `Bit-level Computation` when the hot computation is dominated by shifts, rotations, bitwise logic, bit counting, byte manipulation, or encoding, hashing, and encryption routines built from them.
- Choose `Control-intensive Computation` when the hot computation is dominated by data-dependent conditions, such as filtering, thresholding, selection, masking, or state updates, rather than by arithmetic throughput.
- Choose `Machine Learning` when the hot computation is a neural-network or learning operator, such as matrix multiplication, convolution, fully connected layers, or quantized inference kernels.
- Prefer `Machine Learning` over `Numerical Computation` for matrix multiplication and convolution kernels, including generic GEMM.
- Prefer `Bit-level Computation` over `Control-intensive Computation` when conditions only guard bitwise work.
- Loops, conditions, or a step-by-step procedure alone do not make a sample `Control-intensive Computation`.

Output constraint:

- You must output exactly one label from this set:
  - Numerical Computation
  - Bit-level Computation
  - Control-intensive Computation
  - Machine Learning
- Do not output explanations, analysis, or any extra text.

Output format:

You must wrap the answer in a fenced code block with exactly three backticks.
Inside the code block, output exactly one label on exactly one line.

Valid examples:

```text
Numerical Computation
```

```text
Bit-level Computation
```

```text
Control-intensive Computation
```

```text
Machine Learning
```

Sample to classify:

quertion:
{quertion}

tags:
{tags}

solution:
{solution}
