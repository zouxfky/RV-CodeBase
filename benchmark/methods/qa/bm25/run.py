#!/usr/bin/env python3
import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BENCHMARK_DIR.parent
RAG_DIR = REPO_DIR / "rag"
QA_METHODS_DIR = BENCHMARK_DIR / "methods/qa"
DEFAULT_QUESTIONS = BENCHMARK_DIR / "data/questions.jsonl"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"

for import_path in (BENCHMARK_DIR, RAG_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from common.io import read_jsonl
from common.llm_config import load_llm_config
from common.qa_schema import validate_qa_questions
from text_rag.build_index import DEFAULT_CHUNKS, ensure_chunk_file

# Reuse the established request and JSONL handling so all QA baselines have
# identical generation, retry, and resume behavior.
if str(QA_METHODS_DIR) not in sys.path:
    sys.path.insert(0, str(QA_METHODS_DIR))

from no_rag.run import (
    append_prediction_jsonl,
    call_openai_compatible,
    load_completed_predictions,
    print_failures,
    progress_bar,
)


SYSTEM_PROMPT = """You answer questions about the RISC-V Vector Extension (RVV).
Use the provided evidence as the primary source of truth. Prefer exact
instruction names, assembly operand orders, and full __riscv_* intrinsic names
that appear in the evidence. Do not invent unsupported variants. Keep the
answer compact and technical."""


TOKEN_RE = re.compile(
    r"__[a-z0-9_<>#*]+"
    r"|[a-z][a-z0-9]*(?:\.[a-z0-9<>]+)+"
    r"|[a-z0-9]+(?:_[a-z0-9<>#*]+)+"
    r"|[a-z0-9]+"
)
TOKEN_PART_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    """Tokenize prose while retaining exact RVV instructions and intrinsics."""
    tokens = []
    for token in TOKEN_RE.findall(text.lower()):
        tokens.append(token)
        if any(separator in token for separator in ("_", ".", "<", ">", "#", "*")):
            tokens.extend(
                part for part in TOKEN_PART_RE.findall(token) if len(part) > 1
            )
    return tokens


def build_user_prompt(question, evidence_texts):
    blocks = [f"Question:\n{question}", "Retrieved Evidence:"]
    for index, text in enumerate(evidence_texts, start=1):
        blocks.append(f"[{index}]\n{text}")
    blocks.append("Answer:")
    return "\n\n".join(blocks)


def call_llm(config, question, evidence_texts):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, evidence_texts)},
    ]
    return call_openai_compatible(config, messages)


def build_bm25(chunk_rows, k1, b):
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise RuntimeError(
            "The rank-bm25 package is required. Install it with: "
            "pip install rank-bm25"
        ) from exc

    corpus = [tokenize(row["text"]) for row in chunk_rows]
    if not corpus:
        raise ValueError("BM25 corpus is empty")
    return BM25Okapi(corpus, k1=k1, b=b)


def top_k_evidence(question, chunk_rows, bm25, top_k):
    scores = bm25.get_scores(tokenize(question))
    ranked_indices = sorted(
        range(len(chunk_rows)),
        key=lambda index: (-float(scores[index]), index),
    )
    return [chunk_rows[index] for index in ranked_indices[:top_k]]


def make_prediction(question, chunk_rows, bm25, config, method, top_k):
    evidence_rows = top_k_evidence(
        question=question["question"],
        chunk_rows=chunk_rows,
        bm25=bm25,
        top_k=top_k,
    )
    evidence_texts = [row["text"] for row in evidence_rows]
    answer = call_llm(config, question["question"], evidence_texts)
    return {
        "id": question["id"],
        "method": method,
        "retrieved_evidence": evidence_texts,
        "answer": answer,
    }


def run_bm25_rag(
    questions,
    chunk_rows,
    bm25,
    config,
    method,
    limit,
    output,
    jobs,
    top_k,
):
    rows = questions[:limit] if limit is not None else questions
    completed_predictions = load_completed_predictions(output)
    completed_ids = {row["id"] for row in completed_predictions}
    pending = [row for row in rows if row["id"] not in completed_ids]
    print(
        f"已跳过 {len(rows) - len(pending)} 条，待生成 {len(pending)} 条",
        file=sys.stderr,
    )

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
                        executor.submit(
                            make_prediction,
                            question,
                            chunk_rows,
                            bm25,
                            config,
                            method,
                            top_k,
                        ): index
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

                    failures.extend(
                        item for item in batch_failures if item is not None
                    )
                    progress.set_postfix(
                        written=written_count,
                        failed=len(failures),
                    )

    if failures:
        print(
            f"本次成功写入 {written_count} 条。失败条目可重新运行断点补跑。",
            file=sys.stderr,
        )
        print_failures(failures)
        sys.exit(1)

    print(f"本次成功写入 {written_count} 条。", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run the BM25-RAG QA baseline.")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--output", default=None)
    parser.add_argument("--method", default="bm25-rag")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument(
        "--materials",
        default=str(REPO_DIR / "rag/data/rvv.json"),
    )
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--config", default=str(REPO_DIR / "llm_config.env"))
    args = parser.parse_args()

    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if args.k1 < 0:
        parser.error("--k1 must be non-negative")
    if not 0 <= args.b <= 1:
        parser.error("--b must be between 0 and 1")

    questions = read_jsonl(args.questions)
    validate_qa_questions(questions)
    config = load_llm_config(Path(args.config))
    output = args.output or str(
        DEFAULT_RESULTS_DIR / args.method / "predictions.jsonl"
    )
    max_tokens_label = (
        config.max_tokens if config.max_tokens is not None else "server-default"
    )
    print(
        f"LLM config: model={config.model} max_tokens={max_tokens_label} "
        f"request_timeout={config.timeout_seconds}s "
        f"max_retries={config.max_retries}",
        file=sys.stderr,
    )

    chunk_rows = ensure_chunk_file(
        materials_path=Path(args.materials),
        chunks_path=Path(args.chunks),
    )
    bm25 = build_bm25(chunk_rows, k1=args.k1, b=args.b)
    print(
        f"BM25 index: chunks={len(chunk_rows)} top_k={args.top_k} "
        f"k1={args.k1} b={args.b}",
        file=sys.stderr,
    )

    run_bm25_rag(
        questions=questions,
        chunk_rows=chunk_rows,
        bm25=bm25,
        config=config,
        method=args.method,
        limit=args.limit,
        output=output,
        jobs=args.jobs,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
