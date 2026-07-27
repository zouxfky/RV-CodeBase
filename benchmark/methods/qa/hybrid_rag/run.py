#!/usr/bin/env python3
import argparse
import math
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
from text_rag.build_index import (
    DEFAULT_CHUNK_EMBEDDINGS,
    DEFAULT_CHUNKS,
    DEFAULT_QUESTION_EMBEDDINGS,
    ensure_artifacts,
)

if str(QA_METHODS_DIR) not in sys.path:
    sys.path.insert(0, str(QA_METHODS_DIR))

from bm25.run import build_bm25, call_llm, tokenize
from no_rag.run import (
    append_prediction_jsonl,
    load_completed_predictions,
    print_failures,
    progress_bar,
)


def cosine_similarity(left, right):
    numerator = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right):
        numerator += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / math.sqrt(left_norm * right_norm)


def top_ranked_indices(scores, candidate_k):
    return sorted(
        range(len(scores)),
        key=lambda index: (-float(scores[index]), index),
    )[:candidate_k]


def reciprocal_rank_fusion(
    bm25_ranked_indices,
    dense_ranked_indices,
    rrf_k,
    bm25_weight,
    dense_weight,
):
    fused_scores = {}
    for rank, index in enumerate(bm25_ranked_indices, start=1):
        fused_scores[index] = fused_scores.get(index, 0.0) + (
            bm25_weight / (rrf_k + rank)
        )
    for rank, index in enumerate(dense_ranked_indices, start=1):
        fused_scores[index] = fused_scores.get(index, 0.0) + (
            dense_weight / (rrf_k + rank)
        )

    return sorted(
        fused_scores,
        key=lambda index: (-fused_scores[index], index),
    )


def top_k_evidence(
    question,
    question_embedding,
    chunk_rows,
    chunk_embeddings_by_id,
    bm25,
    top_k,
    candidate_k,
    rrf_k,
    bm25_weight,
    dense_weight,
):
    bm25_scores = bm25.get_scores(tokenize(question))
    dense_scores = [
        cosine_similarity(
            question_embedding,
            chunk_embeddings_by_id[chunk["chunk_id"]]["embedding"],
        )
        for chunk in chunk_rows
    ]

    effective_candidate_k = min(candidate_k, len(chunk_rows))
    bm25_ranked_indices = top_ranked_indices(
        bm25_scores,
        effective_candidate_k,
    )
    dense_ranked_indices = top_ranked_indices(
        dense_scores,
        effective_candidate_k,
    )
    fused_indices = reciprocal_rank_fusion(
        bm25_ranked_indices=bm25_ranked_indices,
        dense_ranked_indices=dense_ranked_indices,
        rrf_k=rrf_k,
        bm25_weight=bm25_weight,
        dense_weight=dense_weight,
    )
    return [chunk_rows[index] for index in fused_indices[:top_k]]


def make_prediction(
    question,
    question_embeddings_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    bm25,
    config,
    method,
    top_k,
    candidate_k,
    rrf_k,
    bm25_weight,
    dense_weight,
):
    question_embedding = question_embeddings_by_id[question["id"]]["embedding"]
    evidence_rows = top_k_evidence(
        question=question["question"],
        question_embedding=question_embedding,
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        bm25=bm25,
        top_k=top_k,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        bm25_weight=bm25_weight,
        dense_weight=dense_weight,
    )
    evidence_texts = [row["text"] for row in evidence_rows]
    answer = call_llm(config, question["question"], evidence_texts)
    return {
        "id": question["id"],
        "method": method,
        "retrieved_evidence": evidence_texts,
        "answer": answer,
    }


def run_hybrid_rag(
    questions,
    question_embeddings_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    bm25,
    config,
    method,
    limit,
    output,
    jobs,
    top_k,
    candidate_k,
    rrf_k,
    bm25_weight,
    dense_weight,
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
                            question_embeddings_by_id,
                            chunk_rows,
                            chunk_embeddings_by_id,
                            bm25,
                            config,
                            method,
                            top_k,
                            candidate_k,
                            rrf_k,
                            bm25_weight,
                            dense_weight,
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
    parser = argparse.ArgumentParser(
        description="Run the BM25 + dense retrieval HybridRAG QA baseline."
    )
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--output", default=None)
    parser.add_argument("--method", default="hybrid-rag")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--rrf-k", type=float, default=60.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument(
        "--materials",
        default=str(REPO_DIR / "rag/data/rvv.json"),
    )
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument(
        "--chunk-embeddings",
        default=str(DEFAULT_CHUNK_EMBEDDINGS),
    )
    parser.add_argument(
        "--question-embeddings",
        default=str(DEFAULT_QUESTION_EMBEDDINGS),
    )
    parser.add_argument("--config", default=str(REPO_DIR / "llm_config.env"))
    args = parser.parse_args()

    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if args.candidate_k < args.top_k:
        parser.error("--candidate-k must be at least --top-k")
    if args.rrf_k < 0:
        parser.error("--rrf-k must be non-negative")
    if args.bm25_weight < 0 or args.dense_weight < 0:
        parser.error("retriever weights must be non-negative")
    if args.bm25_weight == 0 and args.dense_weight == 0:
        parser.error("at least one retriever weight must be positive")
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

    chunk_rows, chunk_embeddings_by_id, question_embeddings_by_id = (
        ensure_artifacts(
            materials_path=Path(args.materials),
            questions_path=Path(args.questions),
            chunks_path=Path(args.chunks),
            chunk_embeddings_path=Path(args.chunk_embeddings),
            question_embeddings_path=Path(args.question_embeddings),
            config_path=Path(args.config),
        )
    )
    bm25 = build_bm25(chunk_rows, k1=args.k1, b=args.b)
    print(
        f"Hybrid index: chunks={len(chunk_rows)} top_k={args.top_k} "
        f"candidate_k={args.candidate_k} rrf_k={args.rrf_k} "
        f"bm25_weight={args.bm25_weight} dense_weight={args.dense_weight}",
        file=sys.stderr,
    )

    run_hybrid_rag(
        questions=questions,
        question_embeddings_by_id=question_embeddings_by_id,
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        bm25=bm25,
        config=config,
        method=args.method,
        limit=args.limit,
        output=output,
        jobs=args.jobs,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        rrf_k=args.rrf_k,
        bm25_weight=args.bm25_weight,
        dense_weight=args.dense_weight,
    )


if __name__ == "__main__":
    main()
