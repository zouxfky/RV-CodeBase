#!/usr/bin/env python3
import argparse
import json
import sys
from concurrent.futures import as_completed, ThreadPoolExecutor
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BENCHMARK_DIR.parent
DEFAULT_QUESTIONS = BENCHMARK_DIR / "data/questions.jsonl"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_jsonl
from common.llm_config import load_llm_config
from common.qa_schema import validate_qa_questions


SYSTEM_PROMPT = """You answer questions about the RISC-V Vector Extension (RVV).
Answer directly and technically. When the question asks for instruction formats,
include the assembly format explicitly. When it asks for intrinsics, include the
full __riscv_* intrinsic names when you know them. Do not invent unsupported
details. Keep the answer compact: prefer one short paragraph plus only the
specific formats or intrinsic names needed. Avoid long tutorials, broad tables,
and unrelated caveats."""


def build_user_prompt(question):
    return f"Question:\n{question}\n\nAnswer:"


def use_responses_api(base_url):
    return "api2.tabcode.cc" in (base_url or "").lower()


def extract_responses_text(response):
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None) or []
    parts = []
    for item in output:
        for content in getattr(item, "content", None) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def call_openai_compatible(config, messages):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The openai package is required. Install it with: pip install openai"
        ) from exc

    if not config.base_url:
        raise ValueError("OpenAI-compatible config requires base_url")

    client = OpenAI(
        api_key=config.api_key or "EMPTY",
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
    try:
        if use_responses_api(config.base_url):
            request = {
                "model": config.model,
                "input": messages,
            }
            if config.max_tokens is not None:
                request["max_output_tokens"] = config.max_tokens
            if config.thinking and config.thinking != "disabled":
                request["reasoning"] = {"effort": "high"}
            response = client.responses.create(
                **request,
                timeout=config.timeout_seconds,
            )
            answer = extract_responses_text(response)
        else:
            request = {
                "model": config.model,
                "messages": messages,
                "temperature": config.temperature,
            }
            if config.max_tokens is not None:
                request["max_tokens"] = config.max_tokens
            if config.thinking:
                request["extra_body"] = {"thinking": {"type": config.thinking}}

            response = client.chat.completions.create(
                **request,
                timeout=config.timeout_seconds,
            )
            choice = response.choices[0]
            message = choice.message
            content = message.content
            if choice.finish_reason != "stop":
                raise RuntimeError(
                    f"LLM did not finish normally: finish_reason={choice.finish_reason}"
                )
            answer = (content or "").strip()

        if not answer:
            raise RuntimeError(
                "LLM returned an empty final answer. "
                "The model may have spent all tokens on reasoning; keep thinking=disabled "
                "or set/increase max_tokens in llm_config.env."
            )
        return answer
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def call_llm(config, question):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question)},
    ]

    return call_openai_compatible(config, messages)


def progress_bar(total):
    try:
        from tqdm import tqdm
    except ImportError as exc:
        raise RuntimeError(
            "The tqdm package is required. Install it with: pip install tqdm"
        ) from exc
    return tqdm(total=total, desc="generating", unit="q")


def load_completed_predictions(output):
    path = Path(output)
    if not path.exists():
        return []
    rows = read_jsonl(path)
    completed = []
    seen_ids = set()
    for row in rows:
        prediction_id = row.get("id")
        answer = row.get("answer")
        if not prediction_id or not isinstance(answer, str) or not answer.strip():
            continue
        if prediction_id in seen_ids:
            continue
        completed.append(row)
        seen_ids.add(prediction_id)
    if len(completed) != len(rows):
        write_predictions_jsonl(path, completed)
    return completed


def ordered_prediction(row):
    ordered = {
        "id": row["id"],
        "method": row["method"],
    }
    if "retrieved_evidence" in row:
        ordered["retrieved_evidence"] = row["retrieved_evidence"]
    ordered["answer"] = row["answer"]
    for key, value in row.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def write_predictions_jsonl(path, rows):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(ordered_prediction(row), ensure_ascii=False) + "\n")


def append_prediction_jsonl(file_obj, row):
    file_obj.write(json.dumps(ordered_prediction(row), ensure_ascii=False) + "\n")
    file_obj.flush()


def make_prediction(question, config, method):
    answer = call_llm(config, question["question"])
    return {
        "id": question["id"],
        "method": method,
        "retrieved_evidence": [],
        "answer": answer,
    }


def print_failures(failures):
    print(f"失败 {len(failures)} 条：{', '.join(item[0] for item in failures)}", file=sys.stderr)
    for question_id, exc in failures:
        print(f"- {question_id}: {type(exc).__name__}: {exc}", file=sys.stderr)


def run_direct_qa(questions, config, method, limit, output, jobs):
    rows = questions[:limit] if limit is not None else questions
    completed_predictions = load_completed_predictions(output)
    completed_ids = {row["id"] for row in completed_predictions}
    pending = [row for row in rows if row["id"] not in completed_ids]
    print(f"已跳过 {len(rows) - len(pending)} 条，待生成 {len(pending)} 条", file=sys.stderr)

    if not pending:
        return

    worker_count = max(1, jobs)
    failures = []
    written_count = 0

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("a", encoding="utf-8") as output_file:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            with progress_bar(total=len(pending)) as progress:
                progress.set_postfix(written=written_count, failed=len(failures))
                for batch_start in range(0, len(pending), worker_count):
                    batch = pending[batch_start : batch_start + worker_count]
                    future_to_index = {
                        executor.submit(make_prediction, question, config, method): index
                        for index, question in enumerate(batch)
                    }
                    batch_predictions = [None] * len(batch)
                    batch_failures = [None] * len(batch)
                    batch_failed_count = 0

                    for future in as_completed(future_to_index):
                        index = future_to_index[future]
                        question_id = batch[index]["id"]
                        try:
                            batch_predictions[index] = future.result()
                        except Exception as exc:
                            batch_failures[index] = (question_id, exc)
                            batch_failed_count += 1

                        progress.update(1)
                        progress.set_postfix(
                            written=written_count,
                            failed=len(failures) + batch_failed_count,
                        )

                    for prediction in batch_predictions:
                        if prediction is not None:
                            append_prediction_jsonl(output_file, prediction)
                            written_count += 1

                    failures.extend(item for item in batch_failures if item is not None)
                    progress.set_postfix(written=written_count, failed=len(failures))

    if failures:
        print(f"本次成功写入 {written_count} 条。失败条目可重新运行断点补跑。", file=sys.stderr)
        print_failures(failures)
        sys.exit(1)

    print(f"本次成功写入 {written_count} 条。", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run the direct no-RAG QA baseline.")
    parser.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
    )
    parser.add_argument(
        "--output",
        default=None,
    )
    parser.add_argument("--method", default="no-rag")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    questions = read_jsonl(args.questions)
    validate_qa_questions(questions)
    config = load_llm_config(REPO_DIR / "llm_config.env")
    output = args.output or str(DEFAULT_RESULTS_DIR / args.method / "predictions.jsonl")
    max_tokens_label = config.max_tokens if config.max_tokens is not None else "server-default"
    print(
        f"LLM config: model={config.model} max_tokens={max_tokens_label} "
        f"request_timeout={config.timeout_seconds}s max_retries={config.max_retries}",
        file=sys.stderr,
    )

    run_direct_qa(
        questions=questions,
        config=config,
        method=args.method,
        limit=args.limit,
        output=output,
        jobs=args.jobs,
    )


if __name__ == "__main__":
    main()
