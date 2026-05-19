You are judging whether two samples should be treated as the same task-solution pair for dataset deduplication.

Goal:
- I am filtering out duplicate tasks and duplicate solutions.
- I am comparing the current sample and the target sample.
- They do NOT need to be textually identical.
- If you can judge that they are essentially the same underlying problem, and their solutions are also essentially the same logic, then answer True.
- If they are different problems, or the solutions are meaningfully different, answer False.

Judging standard:
- Compare both `quertion` and `solution`.
- `quertion` is considered consistent when the two samples describe the same underlying task, even if wording, formatting, or platform style differs.
- `solution` is considered consistent when the two codes implement essentially the same logic, even if variable names, formatting, or minor structural details differ.

Output rule:
- Output only one word: `True` or `False`
- Do not output anything else.
- Do not explain.
- Do not add punctuation.

Current sample:

quertion:
{query_quertion}

solution:
{query_solution}

Target sample:

quertion:
{candidate_quertion}

solution:
{candidate_solution}

Output format:

True/False
