import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
PROMPTS_DIR = SRC_DIR / "prompts"
CONFIG_PATH = SRC_DIR / "llm_config.env"
INPUT_PATH = DATA_DIR / "merge_dedupe.jsonl"
OUTPUT_PATH = DATA_DIR / "merge_dedupe_classify.jsonl"
PROMPT_PATH = PROMPTS_DIR / "classify_category.md"
RULE_PATH = PROMPTS_DIR / "classify_rule.md"

DEFAULT_SYSTEM_PROMPT = (
    "You are a strict classifier. "
    "You must return exactly one valid top-level category."
)
VALID_LABELS = {
    "Machine Learning",
    "Data Structures",
    "Numerical Computation",
    "Algorithms",
    "Others",
}
_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


class ClassificationOutputError(Exception):
    def __init__(self, raw_output: str):
        super().__init__(raw_output)
        self.raw_output = raw_output


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


def load_completed_pids(path: Path) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            pid = str(item.get("pid", "")).strip()
            if pid:
                completed.add(pid)
    return completed


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


def build_user_prompt(template: str, classification_rule: str, row: dict) -> str:
    return template.format(
        classification_rule=classification_rule,
        pid=str(row.get("pid", "")),
        quertion=str(row.get("quertion", "")),
        tags=json.dumps(row.get("tags", []), ensure_ascii=False),
        solution=str(row.get("solution", "")),
    )


def parse_label(text: str) -> str:
    stripped = text.strip()
    fence_match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()

    found = []
    for label in VALID_LABELS:
        if re.search(rf"\b{re.escape(label)}\b", stripped):
            found.append(label)

    found = sorted(set(found))
    if len(found) == 1:
        return found[0]

    raise ValueError(f"invalid classification output: {text!r}")


def classify_one(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    classification_rule: str,
    row: dict,
    temperature: float,
    max_completion_tokens: int,
) -> str:
    user_prompt = build_user_prompt(user_template, classification_rule, row)
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
    try:
        return parse_label(text)
    except Exception as exc:
        raise ClassificationOutputError(text) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", nargs="?", default=str(CONFIG_PATH))
    parser.add_argument("-j", type=int, default=1, help="number of parallel classification requests")
    parser.add_argument("-n", type=int, default=None, help="max number of rows to classify this run")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="drop rows with category == ERROR from classify jsonl before resuming",
    )
    return parser.parse_args()


def prune_error_rows(path: Path) -> None:
    if not path.exists():
        return

    kept_rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("category", "")).strip() == "ERROR":
                continue
            kept_rows.append(row)

    with path.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    config = parse_env_file(Path(args.config_path))
    if args.repeat:
        prune_error_rows(OUTPUT_PATH)
    rows = read_jsonl(INPUT_PATH)
    completed_pids = load_completed_pids(OUTPUT_PATH)

    user_template = load_text(PROMPT_PATH)
    classification_rule = load_text(RULE_PATH)
    system_prompt = config.get("classification_system_prompt", DEFAULT_SYSTEM_PROMPT)
    model = config.get("model", "").strip()
    if not model:
        raise ValueError("missing model in llm_config.env")

    temperature = float(config.get("temperature", "1").strip() or "1")
    max_completion_tokens = int(config.get("max_completion_tokens", "1024").strip() or "1024")
    client = get_client(config)

    pending_rows = [
        row for row in rows
        if str(row.get("pid", "")).strip() and str(row.get("pid", "")).strip() not in completed_pids
    ]
    if args.n is not None:
        pending_rows = pending_rows[: max(0, args.n)]

    progress = tqdm(total=len(pending_rows), desc="classify", unit="sample")
    with OUTPUT_PATH.open("a", encoding="utf-8") as fh:
        jobs = max(1, args.j)
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            next_index = 0
            future_map: dict = {}

            while next_index < len(pending_rows) or future_map:
                while next_index < len(pending_rows) and len(future_map) < jobs:
                    row = pending_rows[next_index]
                    future = executor.submit(
                        classify_one,
                        client,
                        model,
                        system_prompt,
                        user_template,
                        classification_rule,
                        row,
                        temperature,
                        max_completion_tokens,
                    )
                    future_map[future] = row
                    next_index += 1

                done_future = next(as_completed(future_map))
                row = future_map.pop(done_future)
                try:
                    label = done_future.result()
                except Exception:
                    label = "ERROR"

                record = {
                    **row,
                    "category": label,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                progress.update(1)

    progress.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
