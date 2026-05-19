You are doing top-level category classification for a code dataset.

Your task is to classify the sample into exactly one of these five categories:

- Machine Learning
- Data Structures
- Numerical Computation
- Algorithms
- Others

Reference rules and example subcategories:

{classification_rule}

How to decide:

- Use all available information together:
  - `quertion`
  - `tags`
  - `solution`
- Use `{classification_rule}` as the classification reference.
- Focus on the primary nature of the sample.
- Strongly prefer the first four categories.
- Choose `Others` only as a last resort, when the sample clearly does not fit Machine Learning, Data Structures, Numerical Computation, or Algorithms. If the sample can reasonably fit one of the first four categories, do not choose `Others`.
- Do not use `Algorithms` as a default fallback category.
- Choose `Algorithms` only when the core of the sample is a solving strategy or algorithmic paradigm.
- Prefer `Numerical Computation` over `Algorithms` for formula-heavy, arithmetic, number-theoretic, geometric, probabilistic, statistical, matrix/vector, or other mainly numerical content.
- Prefer `Data Structures` over `Algorithms` when the sample is mainly about the data structure itself.
- Prefer `Others` over `Algorithms` for system, utility, parsing, encoding, serialization, class-modeling, API, protocol, file, or format-processing code.
- Loops, conditions, or a step-by-step procedure alone do not make a sample `Algorithms`.

Output constraint:

- You must output exactly one label from this set:
  - Machine Learning
  - Data Structures
  - Numerical Computation
  - Algorithms
  - Others
- Do not output explanations, analysis, or any extra text.

Output format:

You must wrap the answer in a fenced code block with exactly three backticks.
Inside the code block, output exactly one label on exactly one line.

Valid examples:

```text
Machine Learning
```

```text
Data Structures
```

```text
Numerical Computation
```

```text
Algorithms
```

```text
Others
```

Sample to classify:

quertion:
{quertion}

tags:
{tags}

solution:
{solution}
