import argparse
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
PROMPTS_DIR = SRC_DIR / "prompts"
CONFIG_PATH = SRC_DIR / "llm_config.env"
MERGE_PATH = DATA_DIR / "merge.jsonl"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.jsonl"
PROMPT_PATH = PROMPTS_DIR / "1-match.md"
COMPLETED_PATH = DATA_DIR / "match.jsonl"

TOP_K = 10
DEFAULT_SYSTEM_PROMPT = (
    "You are a strict duplicate judge for dataset deduplication. "
    "You must output only True or False."
)

_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


def parse_env_file(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_embeddings(path: Path) -> dict[str, dict]:
    embeddings: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            pid = str(item.get("pid", "")).strip()
            if pid:
                embeddings[pid] = item
    return embeddings


def load_completed_source_pids(path: Path) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            source_pid = str(item.get("source_pid", "")).strip()
            if source_pid:
                completed.add(source_pid)
    return completed


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def non_empty_quertion_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("quertion", "")).strip()]


def alive_query_pids(rows: list[dict]) -> list[str]:
    return [
        str(row.get("pid", "")).strip()
        for row in rows
        if str(row.get("quertion", "")).strip()
    ]


def verify_embeddings(rows: list[dict], embeddings: dict[str, dict]) -> tuple[bool, str]:
    merge_map: dict[str, str] = {}
    for row in non_empty_quertion_rows(rows):
        pid = str(row.get("pid", "")).strip()
        merge_map[pid] = text_hash(str(row.get("quertion", "")).strip())

    merge_pids = set(merge_map.keys())
    embedding_pids = set(embeddings.keys())

    missing = sorted(merge_pids - embedding_pids)
    extra = sorted(embedding_pids - merge_pids)
    mismatched = sorted(
        pid for pid in (merge_pids & embedding_pids)
        if str(embeddings[pid].get("text_hash", "")).strip() != merge_map[pid]
    )

    if missing or extra or mismatched:
        parts: list[str] = []
        if missing:
            parts.append(f"missing={len(missing)} first={missing[:5]}")
        if extra:
            parts.append(f"extra={len(extra)} first={extra[:5]}")
        if mismatched:
            parts.append(f"text_hash_mismatch={len(mismatched)} first={mismatched[:5]}")
        return False, " | ".join(parts)
    return True, ""


def get_client(config: dict[str, str]) -> OpenAI:
    api_base_url = config.get("api_base_url", "").strip()
    api_key = config.get("api_key", "").strip()
    timeout = int(config.get("request_timeout_sec", "600").strip() or "600")

    if not api_base_url:
        raise ValueError("missing api_base_url in llm_config.env")
    if not api_key:
        raise ValueError("missing api_key in llm_config.env")

    key = (api_base_url, api_key, timeout)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = OpenAI(api_key=api_key, base_url=api_base_url, timeout=timeout)
        _CLIENT_CACHE[key] = client
    return client


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * norm2**0.5)


def top_k_similar(query_pid: str, alive_pids: list[str], embeddings: dict[str, dict], top_k: int) -> list[tuple[str, float]]:
    query_vec = embeddings[query_pid]["embedding"]
    scored: list[tuple[str, float]] = []
    for pid in alive_pids:
        if pid == query_pid:
            continue
        score = cosine_similarity(query_vec, embeddings[pid]["embedding"])
        scored.append((pid, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def build_user_prompt(template: str, query_row: dict, candidate_row: dict) -> str:
    return template.format(
        query_pid=str(query_row.get("pid", "")),
        query_quertion=str(query_row.get("quertion", "")),
        query_solution=str(query_row.get("solution", "")),
        candidate_pid=str(candidate_row.get("pid", "")),
        candidate_quertion=str(candidate_row.get("quertion", "")),
        candidate_solution=str(candidate_row.get("solution", "")),
    )


def parse_bool_response(text: str) -> bool:
    stripped = text.strip()
    if stripped == "True":
        return True
    if stripped == "False":
        return False
    match = re.search(r"\b(True|False)\b", stripped)
    if match:
        return match.group(1) == "True"
    raise ValueError(f"invalid model output: {stripped!r}")


def judge_pair(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    query_row: dict,
    candidate_row: dict,
    temperature: float,
    max_completion_tokens: int,
) -> tuple[str, str, bool]:
    user_prompt = build_user_prompt(user_template, query_row, candidate_row)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        temperature=temperature,
        stream=False,
        stop=None,
    )
    text = response.choices[0].message.content or ""
    verdict = parse_bool_response(text)
    return str(query_row["pid"]), str(candidate_row["pid"]), verdict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", nargs="?", default=str(CONFIG_PATH))
    parser.add_argument("-j", type=int, default=1, help="number of query rows per batch")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = parse_env_file(Path(args.config_path))
    rows = read_jsonl(MERGE_PATH)

    if not EMBEDDINGS_PATH.exists():
        print("[Exit] embeddings.jsonl not found. please build embeddings first.")
        return 1

    embeddings = load_embeddings(EMBEDDINGS_PATH)
    ok, reason = verify_embeddings(rows, embeddings)
    if not ok:
        print(f"[Exit] embeddings.jsonl is incomplete or stale: {reason}")
        return 1

    user_template = load_text(PROMPT_PATH)
    system_prompt = config.get("dedupe_system_prompt", DEFAULT_SYSTEM_PROMPT)
    model = config.get("model", "").strip()
    if not model:
        raise ValueError("missing model in llm_config.env")
    temperature = float(config.get("temperature", "0").strip() or "0")
    max_completion_tokens = int(config.get("max_completion_tokens", "1024").strip() or "1024")

    client = get_client(config)
    completed_source_pids = load_completed_source_pids(COMPLETED_PATH)

    rows_by_pid = {
        str(row.get("pid", "")).strip(): row
        for row in rows
        if str(row.get("pid", "")).strip()
    }
    alive_pids = alive_query_pids(rows)
    pending_query_pids = [pid for pid in alive_pids if pid not in completed_source_pids]

    batch_size = max(1, args.j)
    with COMPLETED_PATH.open("a", encoding="utf-8") as fh:
        with tqdm(total=len(pending_query_pids), unit="query") as progress:
            for batch_start in range(0, len(pending_query_pids), batch_size):
                batch = pending_query_pids[batch_start: batch_start + batch_size]
                future_map = {}
                results_by_query: dict[str, list[dict]] = {pid: [] for pid in batch}

                with ThreadPoolExecutor(max_workers=batch_size * TOP_K) as executor:
                    for query_pid in batch:
                        query_row = rows_by_pid[query_pid]
                        candidates = top_k_similar(query_pid, alive_pids, embeddings, TOP_K)
                        for candidate_pid, score in candidates:
                            candidate_row = rows_by_pid[candidate_pid]
                            future = executor.submit(
                                judge_pair,
                                client,
                                model,
                                system_prompt,
                                user_template,
                                query_row,
                                candidate_row,
                                temperature,
                                max_completion_tokens,
                            )
                            future_map[future] = (query_pid, candidate_pid, score)

                    for future in as_completed(future_map):
                        query_pid, candidate_pid, score = future_map[future]
                        try:
                            _, _, verdict = future.result()
                        except Exception as exc:
                            print(f"[Warn] pair failed {query_pid} -> {candidate_pid}: {exc}")
                            verdict = False
                        results_by_query[query_pid].append(
                            {
                                "pid": candidate_pid,
                                "score": score,
                                "result": verdict,
                            }
                        )

                for query_pid in batch:
                    results_by_query[query_pid].sort(
                        key=lambda item: item["score"],
                        reverse=True,
                    )
                    record = {
                        "source_pid": query_pid,
                        "target": results_by_query[query_pid],
                    }
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    fh.flush()
                    progress.update(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
