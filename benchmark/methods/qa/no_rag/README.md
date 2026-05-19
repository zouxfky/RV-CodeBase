# No-RAG QA Baseline

This method answers each QA question with the configured LLM directly. It does
not retrieve or pass any RVV document evidence to the model.

The LLM is expected to return plain text only. The script wraps that text into
the benchmark `predictions.jsonl` format.

Output format:

```json
{
  "id": "qa-0001",
  "method": "no-rag",
  "retrieved_evidence": [],
  "answer": "..."
}
```

The default method name is `no-rag` for the model-only baseline. If you want
model-specific result folders, set `--method` and `--output` accordingly.

Because `retrieved_evidence` is empty, retrieval-dependent metrics behave as
follows:

- `faithfulness`: `null` because there is no retrieved evidence to support the answer.

Answer-level metrics are still computed:

- `accuracy`: coverage of the expected instruction, operand-format, and
  intrinsic-family claims.
- `precision`: validity of the answer's extracted claims against the global RVV
  claim index from `materials/RVV.json`.
- `f1`: harmonic mean of `accuracy` and `precision`.

Run:

```bash
python3 benchmark/methods/qa/no_rag/run.py \
  --questions benchmark/datasets/questions.jsonl \
  --output benchmark/results/qa/no-rag/predictions.jsonl \
  --jobs 4
```

The script reads model settings from the repository-level `llm_config.env`.

The script supports resume by output file. It appends one JSONL row after each
successful answer. When rerun with the same output path, existing `id` values
are skipped and only missing questions are generated.

Parallel requests are controlled by `--jobs`. Worker threads only call the
LLM and return plain-text answers. The main thread is the only writer, so the
output JSONL file does not need a write lock.

Progress output is intentionally minimal: one skipped-count line plus a `tqdm`
progress bar when `tqdm` is installed.

The method uses the `openai` Python package with an OpenAI-compatible
`base_url`.

Dependencies:

```bash
pip install -r benchmark/requirements.txt
```
