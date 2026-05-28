import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI
from openai import RateLimitError


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
CONFIG_PATH = SRC_DIR / "llm_config.env"
MERGE_PATH = DATA_DIR / "collected_seeds.jsonl"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.jsonl"
MAX_RETRIES = 8
BACKOFF_BASE_SEC = 2
DEFAULT_JOBS = 8

def parse_env_file(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_merge_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_embeddings_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            pid = str(item.get("pid", "")).strip()
            if not pid:
                continue
            cache[pid] = item
    return cache


def chunked(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def get_embedding_client(config: dict[str, str]) -> OpenAI:
    api_key = config.get("embedding_api_key", "").strip()
    if not api_key:
        raise ValueError("missing embedding_api_key in llm_config.env")

    base_url = config.get("embedding_api_base_url", "").strip()
    if not base_url:
        raise ValueError("missing embedding_api_base_url in llm_config.env")

    timeout = int(config.get("request_timeout_sec", "600").strip() or "600")
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def request_batch(
    client: OpenAI,
    model: str,
    dimensions: int,
    item: dict,
) -> dict:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=model,
                input=item["quertion"],
                dimensions=dimensions,
            )
            emb = response.data[0]
            return {
                "pid": item["pid"],
                "text_hash": item["text_hash"],
                "embedding": emb.embedding,
            }
        except RateLimitError as exc:
            last_exc = exc
            sleep_sec = BACKOFF_BASE_SEC * attempt
            print(f"[Retry] {item['pid']} rate_limited attempt={attempt}/{MAX_RETRIES} sleep={sleep_sec}s")
            time.sleep(sleep_sec)
        except Exception as exc:
            last_exc = exc
            sleep_sec = min(30, attempt)
            print(f"[Retry] {item['pid']} error attempt={attempt}/{MAX_RETRIES} sleep={sleep_sec}s error={exc}")
            time.sleep(sleep_sec)
    raise last_exc


def append_embedding(output_fh, entry: dict) -> None:
    output_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    output_fh.flush()


def build_items(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    for row in rows:
        pid = str(row.get("pid", "")).strip()
        quertion = str(row.get("quertion", "")).strip()
        if not pid or not quertion:
            continue
        items.append(
            {
                "pid": pid,
                "quertion": quertion,
                "text_hash": text_hash(quertion),
            }
        )
    return items


def build_embeddings_for_items(
    items: list[dict],
    config: dict[str, str],
    existing_cache: dict[str, dict],
    output_fh,
    jobs: int,
) -> dict[str, dict]:
    if not items:
        return {}

    model = config.get("embedding_model", "").strip()
    if not model:
        raise ValueError("missing embedding_model in llm_config.env")

    dimensions = int(config.get("embedding_dimensions", "1024").strip() or "1024")
    client = get_embedding_client(config)

    results_by_pid: dict[str, dict] = dict(existing_cache)
    total = len(items)
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        next_index = 0
        future_map: dict = {}

        while next_index < total or future_map:
            while next_index < total and len(future_map) < jobs:
                item = items[next_index]
                item_index = next_index + 1
                future = executor.submit(request_batch, client, model, dimensions, item)
                future_map[future] = item_index
                next_index += 1

            done_future = next(as_completed(future_map))
            item_index = future_map.pop(done_future)
            entry = done_future.result()
            results_by_pid[entry["pid"]] = entry
            append_embedding(output_fh, entry)
            print(f"[Done] embedding item {item_index}/{total}")

    return results_by_pid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=DEFAULT_JOBS, help="number of parallel embedding requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = parse_env_file(CONFIG_PATH)
    rows = read_merge_rows(MERGE_PATH)
    items = build_items(rows)

    if not items:
        raise ValueError("no non-empty quertion rows found in collected_seeds.jsonl")

    existing_cache: dict[str, dict] = {}
    if EMBEDDINGS_PATH.exists():
        existing_cache = load_embeddings_cache(EMBEDDINGS_PATH)
        print(f"[Info] loaded existing cache: {len(existing_cache)}")
    else:
        print(f"[Info] {EMBEDDINGS_PATH.name} not found. full build starts.")

    missing_items = [item for item in items if item["pid"] not in existing_cache]

    if not missing_items:
        print("[Skip] no missing pid with non-empty quertion")
        return 0

    print(f"[Info] missing embeddings to build: {len(missing_items)}")
    file_mode = "a" if EMBEDDINGS_PATH.exists() else "w"
    with EMBEDDINGS_PATH.open(file_mode, encoding="utf-8") as output_fh:
        build_embeddings_for_items(
            missing_items,
            config,
            existing_cache,
            output_fh,
            max(1, args.j),
        )
    print(f"[Done] wrote {EMBEDDINGS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
