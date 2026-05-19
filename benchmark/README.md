# Benchmark

This directory contains method-agnostic benchmark code. A method can be RAG,
fine-tuning, prompting, or any other system, as long as it writes the required
prediction file.

## Common Layer

Shared utilities live in:

```text
benchmark/common/
```

- `io.py`: JSONL and JSON read/write helpers.
- `qa_schema.py`: QA field validation, prediction alignment, and shared metric names.
- `llm_config.py`: shared LLM configuration loading and validation.

The common layer does not call models and does not implement any RAG method. It
only defines the file-level contract used by evaluators and methods.

## LLM Config

LLM settings are read from the repository-level env file:

```text
llm_config.env
```

Example:

```text
api_base_url=https://api.example.com/v1
api_key=...
model=your-model-name
temperature=0.0
request_timeout_sec=120
max_retries=2
```

Fields:

- `model`: OpenAI-compatible chat model name.
- `api_base_url`: OpenAI-compatible API endpoint.
- `api_key`: API key for the model service.
- `temperature`: decoding temperature.
- `max_tokens`: optional maximum generated tokens. If omitted, requests do not
  send a token limit and the model service default is used.
- `request_timeout_sec`: request timeout.
- `max_retries`: retry count for transient call failures.

The common layer only loads this config. Each method is responsible for using it
to call the model through the `openai` Python package.

Install method dependencies with:

```bash
pip install -r benchmark/requirements.txt
```

Test the currently enabled OpenAI-compatible chat endpoint in `llm_config.env`:

```bash
./benchmark/scripts/test_llm_api.sh
```

## QA Dataset Input

QA questions are stored in:

```text
benchmark/datasets/questions.jsonl
```

Each line is one question:

```json
{
  "id": "qa-0001",
  "question": "vredsum.vs 的功能、汇编格式和内置函数是什么？",
  "answer_key": {
    "gold_evidence": ["..."],
    "formats": ["vredsum.vs vd, vs2, vs1, vm"],
    "intrinsics": ["__riscv_vredsum_vs_i32m1_i32m1"]
  }
}
```

## Method Output

Each method writes:

```text
benchmark/results/qa/<method>/predictions.jsonl
```

Each line is one prediction:

```json
{
  "id": "qa-0001",
  "method": "text_rag",
  "retrieved_evidence": ["..."],
  "answer": "..."
}
```

For methods without retrieval, `retrieved_evidence` may be omitted or set to an
empty list. Retrieval-dependent metrics will be reported as `null` or `0.0`
depending on whether evidence is missing or explicitly empty.

## Methods

Implemented QA methods:

```text
benchmark/methods/qa/no_rag/
```

The no-RAG baseline sends only the question to the configured LLM and writes empty
`retrieved_evidence`. The LLM returns plain text; the method script wraps that
text into the benchmark prediction JSONL:

```bash
python3 benchmark/methods/qa/no_rag/run.py \
  --questions benchmark/datasets/questions.jsonl \
  --output benchmark/results/qa/kimi-2.5/predictions.jsonl \
  --jobs 4
```

The script runs questions in batches of up to `--jobs` requests. After a whole
batch finishes, the main thread appends that batch's successful predictions in
question order, then decides whether to start the next batch. If it is
interrupted and rerun with the same output path, it reads existing prediction
ids and skips completed questions. The progress bar reports both successful
writes and failed requests. Failed requests do not stop later batches; the
script keeps going, writes every successful prediction, and prints failures at
the end. Rerunning with the same output path skips successes and retries the
missing ids. Worker threads do not write files, so no file write lock is needed.

## QA Metrics

The QA evaluator computes the same five metrics for every method:

- `recall`
- `faithfulness`
- `accuracy`
- `precision`
- `f1`

`recall` and `faithfulness` are retrieval-level metrics. `accuracy` is the mean
coverage of the question's expected instruction, operand-format, and
intrinsic-family claims. `precision` is the mean fraction of answer claims that
are supported by the global claim index extracted from `materials/RVV.json`.
`f1` is the harmonic mean of `accuracy` and `precision`.
