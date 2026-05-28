#!/usr/bin/env python3
import argparse
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BENCHMARK_DIR.parent
RAG_DIR = REPO_DIR / "rag"
DEFAULT_QUESTIONS = BENCHMARK_DIR / "data/questions.jsonl"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results/qa"
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

from common.io import read_json, read_jsonl, write_jsonl
from common.llm_config import load_llm_config
from common.qa_schema import validate_qa_questions
from graph_rag.build_graph import (
    DEFAULT_ALIAS_INDEX,
    DEFAULT_EDGES,
    DEFAULT_NODES,
    DEFAULT_QUESTION_HINTS,
    DEFAULT_SUMMARY,
    build_graph,
    candidate_alias_keys,
    concept_id,
    extract_query_symbols,
    extract_question_concepts,
    norm_key,
)
from text_rag.build_index import (
    DEFAULT_CHUNK_EMBEDDINGS,
    DEFAULT_CHUNKS,
    DEFAULT_QUESTION_EMBEDDINGS,
    ensure_artifacts as ensure_text_artifacts,
)


SYSTEM_PROMPT = """You answer questions about the RISC-V Vector Extension (RVV).
Use the provided graph evidence as the primary source of truth. Prefer exact
instruction names, assembly operand orders, operand roles, and full __riscv_*
intrinsic names that appear in the evidence. When the question asks to check,
verify, or correct a claim, state whether the claim is correct before explaining.
Do not invent unsupported variants. Keep the answer compact and technical."""


GENERIC_SEED_KEYS = {
    "vl",
    "sew",
    "lmul",
    "eew",
    "<eew>",
    "<nf>",
    "nf",
    "vd",
    "vs1",
    "vs2",
    "vs3",
    "rs1",
    "rs2",
    "imm",
    "vm",
    "v0.t",
    ".vv",
    ".vx",
    ".vi",
    ".vf",
    ".wv",
    ".wx",
    ".wi",
    ".wf",
    ".vs",
    ".mm",
}

SPECIFIC_CONCEPTS = {
    "unit_stride",
    "strided",
    "indexed",
    "segment",
    "fault_only_first",
    "packed_mask",
    "tuple",
    "widening",
    "narrowing",
    "wide_vs2",
    "narrow_source",
    "wraparound",
    "saturation",
    "fixed_point",
    "reduction",
    "slide",
    "gather",
    "compress",
    "float_to_integer_conversion",
    "integer_to_float_conversion",
    "float_to_float_conversion",
    "round_towards_zero",
    "round_to_odd",
}

BASE_EDGE_WEIGHTS = {
    "SYMBOL_OF": 1.0,
    "HAS_SYMBOL": 0.55,
    "ALIAS_OF": 0.8,
    "HAS_ALIAS": 0.15,
    "HAS_FORMAT": 0.75,
    "HAS_OPERAND_ROLE": 0.75,
    "HAS_INTRINSIC": 0.75,
    "HAS_CONCEPT": 0.25,
    "CONCEPT_OF": 0.22,
    "SAME_FAMILY_AS": 0.4,
    "CONTRASTS_WITH": 0.5,
    "SAME_SECTION_AS": 0.1,
    "SHARES_CONCEPT_WITH": 0.08,
    "BELONGS_TO_SECTION": 0.08,
    "CONTAINS_INSTRUCTION": 0.08,
    "INTRINSIC_OF": 1.0,
    "DESCRIBES_OPERAND": 0.2,
    "USES_OPERAND": 0.15,
}

PROJECTION_WEIGHTS = {
    "SYMBOL_OF": 1.0,
    "HAS_SYMBOL": 1.0,
    "HAS_FORMAT": 1.0,
    "HAS_OPERAND_ROLE": 0.9,
    "HAS_INTRINSIC": 1.0,
    "INTRINSIC_OF": 1.0,
    "HAS_CONCEPT": 0.3,
    "CONCEPT_OF": 0.3,
    "BELONGS_TO_SECTION": 0.15,
    "CONTAINS_INSTRUCTION": 0.15,
    "SAME_FAMILY_AS": 0.35,
    "CONTRASTS_WITH": 0.35,
}


def build_user_prompt(question, evidence_texts):
    blocks = [f"Question:\n{question}", "Retrieved Graph Evidence:"]
    for index, text in enumerate(evidence_texts, start=1):
        blocks.append(f"[{index}]\n{text}")
    blocks.append("Answer:")
    return "\n\n".join(blocks)


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
            content = choice.message.content
            if choice.finish_reason != "stop":
                raise RuntimeError(
                    f"LLM did not finish normally: finish_reason={choice.finish_reason}"
                )
            answer = (content or "").strip()

        if not answer:
            raise RuntimeError("LLM returned an empty final answer.")
        return answer
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def call_llm(config, question, evidence_texts):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, evidence_texts)},
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
        "retrieved_evidence": row["retrieved_evidence"],
        "answer": row["answer"],
    }
    for key, value in row.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def append_prediction_jsonl(file_obj, row):
    file_obj.write(json.dumps(ordered_prediction(row), ensure_ascii=False) + "\n")
    file_obj.flush()


def write_predictions_jsonl(path, rows):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(ordered_prediction(row), ensure_ascii=False) + "\n")


def cosine_similarity(left, right):
    numerator = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l_value, r_value in zip(left, right):
        numerator += l_value * r_value
        left_norm += l_value * l_value
        right_norm += r_value * r_value
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / math.sqrt(left_norm * right_norm)


def top_k_embedding_chunks(question_embedding, chunk_rows, chunk_embeddings_by_id, top_k):
    scored = []
    for chunk in chunk_rows:
        embedding_row = chunk_embeddings_by_id.get(chunk["chunk_id"])
        if not embedding_row:
            continue
        score = cosine_similarity(question_embedding, embedding_row["embedding"])
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:top_k]


class GraphIndex:
    def __init__(self, nodes, edges):
        self.nodes = {row["node_id"]: row for row in nodes}
        self.out_edges = defaultdict(list)
        self.in_edges = defaultdict(list)
        for edge in edges:
            self.out_edges[edge["source"]].append(edge)
            self.in_edges[edge["target"]].append(edge)

        self.formats_by_instruction = defaultdict(list)
        self.operand_roles_by_instruction = defaultdict(list)
        self.intrinsics_by_instruction = defaultdict(list)
        self.concepts_by_instruction = defaultdict(list)
        self.symbols_by_instruction = defaultdict(list)
        self.index_instruction_children()

    def index_instruction_children(self):
        for edge in self.iter_edges():
            if not edge["source"].startswith("instruction:"):
                continue
            instruction_id = edge["source"]
            target = self.nodes.get(edge["target"])
            if not target:
                continue
            if edge["type"] == "HAS_FORMAT":
                self.formats_by_instruction[instruction_id].append(target)
            elif edge["type"] == "HAS_OPERAND_ROLE":
                self.operand_roles_by_instruction[instruction_id].append(target)
            elif edge["type"] == "HAS_INTRINSIC":
                self.intrinsics_by_instruction[instruction_id].append(target)
            elif edge["type"] == "HAS_CONCEPT":
                self.concepts_by_instruction[instruction_id].append(target)
            elif edge["type"] == "HAS_SYMBOL":
                self.symbols_by_instruction[instruction_id].append(target)

    def iter_edges(self):
        for edges in self.out_edges.values():
            yield from edges

    def incident_edges(self, node_id):
        for edge in self.out_edges.get(node_id, []):
            yield edge["target"], edge, "out"
        for edge in self.in_edges.get(node_id, []):
            yield edge["source"], edge, "in"

    def linked_instructions(self, node_id):
        if node_id.startswith("instruction:") and node_id in self.nodes:
            return [(node_id, 1.0)]

        links = []
        for neighbor_id, edge, _direction in self.incident_edges(node_id):
            if neighbor_id.startswith("instruction:"):
                weight = PROJECTION_WEIGHTS.get(edge["type"], 0.0)
                if weight > 0:
                    links.append((neighbor_id, weight))
        return links


def ensure_graph_artifacts(
    materials_path,
    questions_path,
    nodes_path,
    edges_path,
    alias_index_path,
    question_hints_path,
    summary_path,
):
    paths = [
        Path(nodes_path),
        Path(edges_path),
        Path(alias_index_path),
        Path(question_hints_path),
    ]
    if all(path.exists() for path in paths):
        return

    builder, question_hints = build_graph(
        materials_path=Path(materials_path),
        questions_path=Path(questions_path),
    )
    builder.write_artifacts(
        nodes_path=Path(nodes_path),
        edges_path=Path(edges_path),
        alias_index_path=Path(alias_index_path),
        summary_path=Path(summary_path),
    )
    write_jsonl(question_hints_path, question_hints)


def load_graph_index(nodes_path, edges_path):
    return GraphIndex(read_jsonl(nodes_path), read_jsonl(edges_path))


def load_question_hints(path):
    return {row["id"]: row for row in read_jsonl(path)}


def build_hint_on_the_fly(question, graph, alias_index):
    symbols = extract_query_symbols(question["question"])
    concepts = extract_question_concepts(question["question"])
    matched_nodes = defaultdict(set)
    for symbol in symbols:
        for key in candidate_alias_keys(symbol):
            for node_id in alias_index.get(norm_key(key), []):
                matched_nodes[symbol].add(node_id)
    for concept in concepts:
        cid = concept_id(concept)
        if cid in graph.nodes:
            matched_nodes[f"concept:{concept}"].add(cid)
        for node_id in alias_index.get(norm_key(concept), []):
            matched_nodes[f"concept:{concept}"].add(node_id)
    return {
        "id": question["id"],
        "symbols": symbols,
        "concepts": concepts,
        "intents": [],
        "matched_nodes": {
            key: sorted(value)
            for key, value in matched_nodes.items()
        },
    }


def node_seed_weight(node_id, source_key, graph):
    node = graph.nodes.get(node_id, {})
    node_type = node.get("type", "")
    source = source_key.lower()

    if source_key.startswith("concept:"):
        weights = {
            "concept": 3.0,
            "instruction": 0.8,
            "format": 0.2,
            "symbol": 0.4,
            "operand_role": 0.2,
            "intrinsic": 0.2,
        }
        return weights.get(node_type, 0.1)

    weights = {
        "instruction": 10.0,
        "symbol": 8.0,
        "format": 7.0,
        "intrinsic": 9.0,
        "operand_role": 4.0,
        "concept": 3.0,
        "section": 1.0,
    }
    weight = weights.get(node_type, 0.5)
    if source in GENERIC_SEED_KEYS:
        weight *= 0.25
    return weight


def collect_graph_seed_scores(hint, graph):
    seed_scores = defaultdict(float)
    matched_nodes = hint.get("matched_nodes", {})
    for source_key, node_ids in matched_nodes.items():
        for node_id in node_ids:
            if node_id not in graph.nodes:
                continue
            seed_scores[node_id] += node_seed_weight(node_id, source_key, graph)
            if source_key.startswith("concept:") and node_id.startswith("concept:"):
                concept = source_key.split(":", 1)[1]
                concept_weight = 6.0 if concept in SPECIFIC_CONCEPTS else 0.5
                for instruction_id, link_weight in graph.linked_instructions(node_id):
                    seed_scores[instruction_id] += concept_weight * link_weight
    return seed_scores


def has_specific_graph_seed(hint):
    for source_key, node_ids in hint.get("matched_nodes", {}).items():
        source = source_key.lower()
        if source_key.startswith("concept:") or source in GENERIC_SEED_KEYS:
            continue
        if node_ids:
            return True
    return False


def has_specific_concept_seed(hint):
    return any(concept in SPECIFIC_CONCEPTS for concept in hint.get("concepts", []))


def add_embedding_seeds(
    seed_scores,
    question,
    question_embeddings_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    embedding_top_k,
    embedding_weight,
):
    question_embedding_row = question_embeddings_by_id.get(question["id"])
    if not question_embedding_row:
        return []
    embedding_hits = top_k_embedding_chunks(
        question_embedding=question_embedding_row["embedding"],
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        top_k=embedding_top_k,
    )
    for rank, (_score, chunk) in enumerate(embedding_hits, start=1):
        instruction_id = f"instruction:{chunk['chunk_id']}"
        seed_scores[instruction_id] += embedding_weight / rank
    return embedding_hits


def edge_type_weight(edge_type, intents):
    weight = BASE_EDGE_WEIGHTS.get(edge_type, 0.0)
    if weight <= 0:
        return 0.0

    intent_set = set(intents or [])
    if "format" in intent_set and edge_type == "HAS_FORMAT":
        weight *= 2.0
    if "operand_roles" in intent_set and edge_type == "HAS_OPERAND_ROLE":
        weight *= 2.0
    if "intrinsic" in intent_set and edge_type == "HAS_INTRINSIC":
        weight *= 2.0
    if ("contrast" in intent_set or "verify_claim" in intent_set) and edge_type == "CONTRASTS_WITH":
        weight *= 2.0
    if "contrast" in intent_set and edge_type == "SAME_FAMILY_AS":
        weight *= 1.5
    return weight


def expand_seed_nodes(seed_scores, graph, intents, graph_depth):
    node_scores = defaultdict(float)
    frontier = dict(seed_scores)
    for node_id, score in seed_scores.items():
        node_scores[node_id] += score

    for _depth in range(max(0, graph_depth)):
        next_frontier = defaultdict(float)
        for node_id, score in frontier.items():
            for neighbor_id, edge, _direction in graph.incident_edges(node_id):
                if neighbor_id not in graph.nodes:
                    continue
                weight = edge_type_weight(edge["type"], intents)
                if weight <= 0:
                    continue
                next_score = score * weight * float(edge.get("weight", 1.0))
                if next_score < 0.05:
                    continue
                node_scores[neighbor_id] += next_score
                next_frontier[neighbor_id] += next_score
        frontier = next_frontier
        if not frontier:
            break
    return node_scores


def project_to_instruction_scores(node_scores, graph):
    instruction_scores = defaultdict(float)
    support_nodes = defaultdict(list)
    for node_id, score in node_scores.items():
        for instruction_id, link_weight in graph.linked_instructions(node_id):
            projected_score = score * link_weight
            instruction_scores[instruction_id] += projected_score
            support_nodes[instruction_id].append((node_id, projected_score))
    return instruction_scores, support_nodes


def support_summary(graph, support_items, max_items):
    seen = set()
    summarized = []
    for node_id, score in sorted(support_items, key=lambda item: item[1], reverse=True):
        if node_id in seen or node_id not in graph.nodes:
            continue
        seen.add(node_id)
        node = graph.nodes[node_id]
        label = node.get("label", node_id)
        summarized.append(f"{node['type']}: {label} (score={score:.2f})")
        if len(summarized) >= max_items:
            break
    return summarized


def render_graph_evidence(instruction_id, graph, support_items, max_intrinsics=20):
    instruction = graph.nodes[instruction_id]
    lines = [
        f"Instruction: {instruction['label']}",
        f"Section: {instruction.get('section_number', '')} {instruction.get('section_title', '')}".strip(),
    ]

    summary = support_summary(graph, support_items, max_items=12)
    if summary:
        lines.append("Matched Graph Nodes:")
        lines.extend(f"- {item}" for item in summary)

    formats = graph.formats_by_instruction.get(instruction_id, [])
    if formats:
        lines.append("Relevant Formats:")
        lines.extend(f"- {row['label']}" for row in formats)

    roles = graph.operand_roles_by_instruction.get(instruction_id, [])
    if roles:
        lines.append("Relevant Operand Roles:")
        for row in roles:
            meaning = row.get("meaning", "")
            lines.append(f"- {row.get('parameter', row['label'])}: {meaning}")

    intrinsics = graph.intrinsics_by_instruction.get(instruction_id, [])
    if intrinsics:
        lines.append("Relevant Intrinsics:")
        lines.extend(f"- {row['label']}" for row in intrinsics[:max_intrinsics])

    concepts = graph.concepts_by_instruction.get(instruction_id, [])
    if concepts:
        labels = ", ".join(row["label"] for row in concepts)
        lines.append(f"Concepts: {labels}")

    lines.append("Full Source:")
    lines.append(instruction.get("text", ""))
    return "\n".join(line for line in lines if line)


def retrieve_graph_evidence(
    question,
    graph,
    alias_index,
    question_hints_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    question_embeddings_by_id,
    top_k,
    embedding_top_k,
    graph_depth,
):
    hint = question_hints_by_id.get(question["id"])
    if hint is None:
        hint = build_hint_on_the_fly(question, graph, alias_index)

    seed_scores = collect_graph_seed_scores(hint, graph)
    embedding_weight = 3.0 if has_specific_graph_seed(hint) or has_specific_concept_seed(hint) else 8.0
    embedding_hits = add_embedding_seeds(
        seed_scores=seed_scores,
        question=question,
        question_embeddings_by_id=question_embeddings_by_id,
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        embedding_top_k=embedding_top_k,
        embedding_weight=embedding_weight,
    )

    node_scores = expand_seed_nodes(
        seed_scores=seed_scores,
        graph=graph,
        intents=hint.get("intents", []),
        graph_depth=graph_depth,
    )
    instruction_scores, support_nodes = project_to_instruction_scores(node_scores, graph)

    if not instruction_scores:
        for rank, (_score, chunk) in enumerate(embedding_hits, start=1):
            instruction_id = f"instruction:{chunk['chunk_id']}"
            instruction_scores[instruction_id] += 1.0 / rank
            support_nodes[instruction_id].append((instruction_id, 1.0 / rank))

    ranked = sorted(
        instruction_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )
    selected = ranked[: max(1, top_k)]
    evidence_rows = []
    for instruction_id, score in selected:
        evidence_rows.append(
            {
                "instruction_id": instruction_id,
                "score": score,
                "text": render_graph_evidence(
                    instruction_id=instruction_id,
                    graph=graph,
                    support_items=support_nodes[instruction_id],
                ),
                "support_nodes": [
                    node_id
                    for node_id, _score in sorted(
                        support_nodes[instruction_id],
                        key=lambda item: item[1],
                        reverse=True,
                    )[:20]
                ],
            }
        )
    return evidence_rows


def make_prediction(
    question,
    graph,
    alias_index,
    question_hints_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    question_embeddings_by_id,
    config,
    method,
    top_k,
    embedding_top_k,
    graph_depth,
    debug_retrieval,
):
    evidence_rows = retrieve_graph_evidence(
        question=question,
        graph=graph,
        alias_index=alias_index,
        question_hints_by_id=question_hints_by_id,
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        question_embeddings_by_id=question_embeddings_by_id,
        top_k=top_k,
        embedding_top_k=embedding_top_k,
        graph_depth=graph_depth,
    )
    evidence_texts = [row["text"] for row in evidence_rows]
    answer = call_llm(config, question["question"], evidence_texts)
    prediction = {
        "id": question["id"],
        "method": method,
        "retrieved_evidence": evidence_texts,
        "answer": answer,
    }
    if debug_retrieval:
        prediction["retrieved_nodes"] = [
            {
                "instruction_id": row["instruction_id"],
                "score": row["score"],
                "support_nodes": row["support_nodes"],
            }
            for row in evidence_rows
        ]
    return prediction


def print_failures(failures):
    print(f"失败 {len(failures)} 条：{', '.join(item[0] for item in failures)}", file=sys.stderr)
    for question_id, exc in failures:
        print(f"- {question_id}: {type(exc).__name__}: {exc}", file=sys.stderr)


def run_graph_rag(
    questions,
    graph,
    alias_index,
    question_hints_by_id,
    chunk_rows,
    chunk_embeddings_by_id,
    question_embeddings_by_id,
    config,
    method,
    limit,
    output,
    jobs,
    top_k,
    embedding_top_k,
    graph_depth,
    debug_retrieval,
):
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
                        executor.submit(
                            make_prediction,
                            question,
                            graph,
                            alias_index,
                            question_hints_by_id,
                            chunk_rows,
                            chunk_embeddings_by_id,
                            question_embeddings_by_id,
                            config,
                            method,
                            top_k,
                            embedding_top_k,
                            graph_depth,
                            debug_retrieval,
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

                    failures.extend(item for item in batch_failures if item is not None)
                    progress.set_postfix(written=written_count, failed=len(failures))

    if failures:
        print(f"本次成功写入 {written_count} 条。失败条目可重新运行断点补跑。", file=sys.stderr)
        print_failures(failures)
        sys.exit(1)

    print(f"本次成功写入 {written_count} 条。", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run the GraphRAG QA baseline.")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--output", default=None)
    parser.add_argument("--method", default="graph-rag")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embedding-top-k", type=int, default=8)
    parser.add_argument("--graph-depth", type=int, default=1)
    parser.add_argument("--debug-retrieval", action="store_true")
    parser.add_argument("--materials", default=str(REPO_DIR / "rag/data/rvv.json"))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--chunk-embeddings", default=str(DEFAULT_CHUNK_EMBEDDINGS))
    parser.add_argument("--question-embeddings", default=str(DEFAULT_QUESTION_EMBEDDINGS))
    parser.add_argument("--graph-nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--graph-edges", default=str(DEFAULT_EDGES))
    parser.add_argument("--alias-index", default=str(DEFAULT_ALIAS_INDEX))
    parser.add_argument("--question-hints", default=str(DEFAULT_QUESTION_HINTS))
    parser.add_argument("--graph-summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--config", default=str(REPO_DIR / "llm_config.env"))
    args = parser.parse_args()

    questions = read_jsonl(args.questions)
    validate_qa_questions(questions)
    config = load_llm_config(Path(args.config))
    output = args.output or str(DEFAULT_RESULTS_DIR / args.method / "predictions.jsonl")
    max_tokens_label = config.max_tokens if config.max_tokens is not None else "server-default"
    print(
        f"LLM config: model={config.model} max_tokens={max_tokens_label} "
        f"request_timeout={config.timeout_seconds}s max_retries={config.max_retries}",
        file=sys.stderr,
    )

    ensure_graph_artifacts(
        materials_path=Path(args.materials),
        questions_path=Path(args.questions),
        nodes_path=Path(args.graph_nodes),
        edges_path=Path(args.graph_edges),
        alias_index_path=Path(args.alias_index),
        question_hints_path=Path(args.question_hints),
        summary_path=Path(args.graph_summary),
    )

    chunk_rows, chunk_embeddings_by_id, question_embeddings_by_id = ensure_text_artifacts(
        materials_path=Path(args.materials),
        questions_path=Path(args.questions),
        chunks_path=Path(args.chunks),
        chunk_embeddings_path=Path(args.chunk_embeddings),
        question_embeddings_path=Path(args.question_embeddings),
        config_path=Path(args.config),
    )

    graph = load_graph_index(args.graph_nodes, args.graph_edges)
    alias_index = read_json(args.alias_index)
    question_hints_by_id = load_question_hints(args.question_hints)

    print(
        f"GraphRAG retrieval: nodes={len(graph.nodes)} top_k={max(1, args.top_k)} "
        f"embedding_top_k={max(0, args.embedding_top_k)} graph_depth={max(0, args.graph_depth)}",
        file=sys.stderr,
    )

    run_graph_rag(
        questions=questions,
        graph=graph,
        alias_index=alias_index,
        question_hints_by_id=question_hints_by_id,
        chunk_rows=chunk_rows,
        chunk_embeddings_by_id=chunk_embeddings_by_id,
        question_embeddings_by_id=question_embeddings_by_id,
        config=config,
        method=args.method,
        limit=args.limit,
        output=output,
        jobs=args.jobs,
        top_k=max(1, args.top_k),
        embedding_top_k=max(0, args.embedding_top_k),
        graph_depth=max(0, args.graph_depth),
        debug_retrieval=args.debug_retrieval,
    )


if __name__ == "__main__":
    main()
