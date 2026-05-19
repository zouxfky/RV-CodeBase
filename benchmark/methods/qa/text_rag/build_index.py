#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BENCHMARK_DIR.parent
METHOD_DIR = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = BENCHMARK_DIR / "datasets/questions.jsonl"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from common.io import read_json, read_jsonl, write_jsonl
from common.llm_config import load_embedding_config
from common.qa_schema import validate_qa_questions


DEFAULT_CHUNKS = METHOD_DIR / "artifacts/chunks.jsonl"
DEFAULT_CHUNK_EMBEDDINGS = METHOD_DIR / "artifacts/chunk_embeddings.jsonl"
DEFAULT_QUESTION_EMBEDDINGS = METHOD_DIR / "artifacts/question_embeddings.jsonl"


def progress_bar(total, desc, unit):
    try:
        from tqdm import tqdm
    except ImportError as exc:
        raise RuntimeError(
            "The tqdm package is required. Install it with: pip install tqdm"
        ) from exc
    return tqdm(total=total, desc=desc, unit=unit)


def instruction_names_from_title(title):
    names = []
    for part in title.replace("`", "").split("/"):
        name = part.strip()
        if name:
            names.append(name)
    return names


def render_instruction_chunk(chapter, section, instruction):
    fields = [
        ("Section", section["title"]),
        ("Instruction", instruction["title"]),
        ("Function", instruction.get("function", "")),
        ("Instruction Formats", instruction.get("instruction_formats", "")),
        ("Parameters", instruction.get("parameters", "")),
        ("Semantics", instruction.get("semantics", "")),
        ("Assembly Examples", instruction.get("assembly_examples", "")),
        ("Intrinsics", instruction.get("intrinsics", "")),
        ("Notes", instruction.get("notes", "")),
    ]
    parts = []
    for label, value in fields:
        if value:
            parts.append(f"{label}: {value}")
    return "\n\n".join(parts).strip()


def build_chunks(materials_path):
    materials = read_json(materials_path)
    chunks = []
    for chapter in materials.get("chapters", []):
        for section in chapter.get("sections", []):
            for instruction in section.get("instructions", []):
                chunk_id = instruction["number"]
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "chapter_number": chapter["number"],
                        "chapter_title": chapter["title"],
                        "section_number": section["number"],
                        "section_title": section["title"],
                        "instruction_number": instruction["number"],
                        "instruction_title": instruction["title"],
                        "instruction_names": instruction_names_from_title(
                            instruction["title"]
                        ),
                        "text": render_instruction_chunk(chapter, section, instruction),
                    }
                )
    return chunks


def load_existing_by_id(path, id_field):
    if not Path(path).exists():
        return {}
    rows = read_jsonl(path)
    return {row[id_field]: row for row in rows}


def batched(items, batch_size):
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def embed_texts(config, texts):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The openai package is required. Install it with: pip install openai"
        ) from exc

    if not config.base_url:
        raise ValueError("Embedding config requires embedding_api_base_url")

    client = OpenAI(
        api_key=config.api_key or "EMPTY",
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
    try:
        request = {
            "model": config.model,
            "input": texts,
        }
        if config.dimensions is not None:
            request["dimensions"] = config.dimensions
        response = client.embeddings.create(**request)
        return [item.embedding for item in response.data]
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def ensure_chunk_file(materials_path, chunks_path):
    output = Path(chunks_path)
    if output.exists():
        chunks = read_jsonl(output)
        print(f"复用 chunks: {output} ({len(chunks)} 条)", file=sys.stderr)
        return chunks

    chunks = build_chunks(materials_path)
    write_jsonl(output, chunks)
    print(f"已创建 chunks: {output} ({len(chunks)} 条)", file=sys.stderr)
    return chunks


def ensure_embeddings(rows, path, id_field, text_field, config, desc):
    output = Path(path)
    existing = load_existing_by_id(output, id_field)
    pending = [row for row in rows if row[id_field] not in existing]
    print(
        f"{desc}: 复用 {len(existing)} 条，待生成 {len(pending)} 条 -> {output}",
        file=sys.stderr,
    )

    if pending:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as f:
            with progress_bar(total=len(pending), desc=desc, unit="item") as progress:
                for batch in batched(pending, max(1, config.batch_size)):
                    embeddings = embed_texts(config, [row[text_field] for row in batch])
                    for row, embedding in zip(batch, embeddings):
                        payload = {
                            id_field: row[id_field],
                            text_field: row[text_field],
                            "embedding": embedding,
                        }
                        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                        existing[row[id_field]] = payload
                        progress.update(1)

    return existing


def build_question_rows(questions_path):
    questions = read_jsonl(questions_path)
    validate_qa_questions(questions)
    return [{"id": row["id"], "question": row["question"]} for row in questions]


def ensure_artifacts(
    materials_path,
    questions_path,
    chunks_path,
    chunk_embeddings_path,
    question_embeddings_path,
    config_path,
):
    embedding_config = load_embedding_config(config_path)
    chunks = ensure_chunk_file(materials_path, chunks_path)
    chunk_embeddings = ensure_embeddings(
        rows=chunks,
        path=chunk_embeddings_path,
        id_field="chunk_id",
        text_field="text",
        config=embedding_config,
        desc="embedding-chunks",
    )
    questions = build_question_rows(questions_path)
    question_embeddings = ensure_embeddings(
        rows=questions,
        path=question_embeddings_path,
        id_field="id",
        text_field="question",
        config=embedding_config,
        desc="embedding-questions",
    )
    return chunks, chunk_embeddings, question_embeddings


def main():
    parser = argparse.ArgumentParser(description="Build TextRAG chunks and embeddings.")
    parser.add_argument(
        "--materials",
        default=str(REPO_DIR / "materials/RVV.json"),
    )
    parser.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS),
    )
    parser.add_argument(
        "--chunks-output",
        default=str(DEFAULT_CHUNKS),
    )
    parser.add_argument(
        "--chunk-embeddings-output",
        default=str(DEFAULT_CHUNK_EMBEDDINGS),
    )
    parser.add_argument(
        "--question-embeddings-output",
        default=str(DEFAULT_QUESTION_EMBEDDINGS),
    )
    parser.add_argument(
        "--config",
        default=str(REPO_DIR / "llm_config.env"),
    )
    args = parser.parse_args()

    chunks, chunk_embeddings, question_embeddings = ensure_artifacts(
        materials_path=Path(args.materials),
        questions_path=Path(args.questions),
        chunks_path=Path(args.chunks_output),
        chunk_embeddings_path=Path(args.chunk_embeddings_output),
        question_embeddings_path=Path(args.question_embeddings_output),
        config_path=Path(args.config),
    )
    print(
        f"chunks={len(chunks)} chunk_embeddings={len(chunk_embeddings)} "
        f"question_embeddings={len(question_embeddings)}"
    )


if __name__ == "__main__":
    main()
