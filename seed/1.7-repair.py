import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from openai import OpenAI
from tqdm import tqdm


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
PROMPTS_DIR = SRC_DIR / "prompts"
CONFIG_PATH = SRC_DIR / "llm_config.env"
INPUT_PATH = DATA_DIR / "merge_dedupe_classify_transform.jsonl"
VERIFY_PATH = DATA_DIR / "verify.jsonl"
OUTPUT_PATH = DATA_DIR / "merge_dedupe_classify_transform_repair.jsonl"
PROMPT_PATH = PROMPTS_DIR / "1-repair.md"

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert code repair agent. "
    "Fix the transformed C++ code according to the verification message and "
    "return only repaired code."
)
_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


class RepairOutputError(Exception):
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


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def load_output_map(path: Path) -> dict[str, dict]:
    output_map: dict[str, dict] = {}
    if not path.exists():
        return output_map
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            pid = str(item.get("pid", "")).strip()
            if pid:
                output_map[pid] = item
    return output_map


def get_prefixed(config: dict[str, str], prefix: str, key: str, default: str = "") -> str:
    specific = config.get(f"{prefix}_{key}", "").strip()
    if specific:
        return specific
    return config.get(key, default).strip()


def get_client(config: dict[str, str]) -> OpenAI:
    api_base_url = get_prefixed(config, "repair", "api_base_url")
    api_key = get_prefixed(config, "repair", "api_key")
    timeout_raw = get_prefixed(config, "repair", "request_timeout_sec")
    timeout = int(timeout_raw) if timeout_raw else None

    if not api_key:
        raise ValueError("missing api_key in llm_config.env")

    key = (api_base_url, api_key, timeout or 0)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if api_base_url:
            client_kwargs["base_url"] = api_base_url
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        client = OpenAI(**client_kwargs)
        _CLIENT_CACHE[key] = client
    return client


def build_user_prompt(template: str, row: dict, verify_item: dict) -> str:
    transform_code = str(row.get("transform", ""))
    message = str(verify_item.get("message", ""))
    return template.format(
        transform_code=transform_code,
        message=message,
    )


def extract_code(text: str) -> str:
    stripped = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    fence_match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        code = fence_match.group(1).strip()
        if code:
            return code
    if stripped:
        return stripped
    raise RepairOutputError(text)


def serialize_response(response: object) -> str:
    if hasattr(response, "model_dump_json"):
        try:
            return response.model_dump_json(indent=2)
        except Exception:
            pass
    return repr(response)


def repair_one(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    row: dict,
    verify_item: dict,
    request_options: dict,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(user_template, row, verify_item)},
        ],
        **request_options,
    )
    text = response.choices[0].message.content or ""
    if not text.strip():
        raise RepairOutputError(serialize_response(response))
    return extract_code(text)


def process_fail_row(
    row: dict,
    verify_map: dict[str, dict],
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    request_options: dict,
) -> tuple[str, dict]:
    pid = str(row.get("pid", "")).strip()
    verify_item = verify_map.get(pid)

    if not verify_item or str(verify_item.get("status", "")).strip() != "fail":
        return pid, dict(row)

    repaired_code = repair_one(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_template=user_template,
        row=row,
        verify_item=verify_item,
        request_options=request_options,
    )
    return pid, {**row, "repair": repaired_code}


def needs_repair(pid: str, verify_map: dict[str, dict]) -> bool:
    verify_item = verify_map.get(pid)
    if not verify_item:
        return False
    return str(verify_item.get("status", "")).strip() == "fail"


def process_row_safe(
    row: dict,
    verify_map: dict[str, dict],
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    request_options: dict,
) -> tuple[str, dict, str | None, bool]:
    pid = str(row.get("pid", "")).strip()
    if not needs_repair(pid, verify_map):
        return pid, dict(row), None, False

    try:
        pid, record = process_fail_row(
            row=row,
            verify_map=verify_map,
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_template=user_template,
            request_options=request_options,
        )
        return pid, record, None, True
    except RepairOutputError as exc:
        return pid, {**row, "repair": "ERROR"}, exc.raw_output or "<empty>", True
    except Exception as exc:
        return pid, {**row, "repair": "ERROR"}, f"{type(exc).__name__}: {exc}", True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", nargs="?", default=str(CONFIG_PATH))
    parser.add_argument("-j", type=int, default=1, help="number of parallel repair requests")
    parser.add_argument("-n", type=int, default=None, help="max number of rows to process this run")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="drop rows with repair == ERROR from repair jsonl before resuming",
    )
    return parser.parse_args()


def prune_error_repairs(path: Path) -> None:
    if not path.exists():
        return

    kept_rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("repair") == "ERROR":
                continue
            kept_rows.append(row)

    with path.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    config = parse_env_file(Path(args.config_path))
    if args.repeat:
        prune_error_repairs(OUTPUT_PATH)
    rows = read_jsonl(INPUT_PATH)
    verify_rows = read_jsonl(VERIFY_PATH)
    verify_map = {
        str(item.get("pid", "")).strip(): item
        for item in verify_rows
        if str(item.get("pid", "")).strip()
    }
    existing_output_map = load_output_map(OUTPUT_PATH)
    user_template = load_text(PROMPT_PATH)

    system_prompt = get_prefixed(
        config, "repair", "system_prompt", DEFAULT_SYSTEM_PROMPT
    )
    model = get_prefixed(config, "repair", "model")
    if not model:
        raise ValueError("missing model in llm_config.env")

    request_options: dict[str, Any] = {}
    max_tokens_raw = get_prefixed(config, "repair", "max_completion_tokens")
    if max_tokens_raw:
        request_options["max_tokens"] = int(max_tokens_raw)
    temperature_raw = get_prefixed(config, "repair", "temperature")
    if temperature_raw:
        request_options["temperature"] = float(temperature_raw)

    client = get_client(config)

    pending_rows = [row for row in rows if str(row.get("pid", "")).strip()]
    if args.n is not None:
        pending_rows = pending_rows[: max(0, args.n)]
    pass_rows = [
        dict(row)
        for row in pending_rows
        if not needs_repair(str(row.get("pid", "")).strip(), verify_map)
    ]
    fail_rows = [
        row
        for row in pending_rows
        if needs_repair(str(row.get("pid", "")).strip(), verify_map)
    ]
    copied_pass_count = sum(
        1 for row in pass_rows if str(row.get("pid", "")).strip() in existing_output_map
    )
    repaired_fail_count = sum(
        1
        for row in fail_rows
        if "repair" in existing_output_map.get(str(row.get("pid", "")).strip(), {})
    )
    pending_fail_rows = [
        row
        for row in fail_rows
        if "repair" not in existing_output_map.get(str(row.get("pid", "")).strip(), {})
    ]

    tqdm.write(
        f"[RESUME] pass_copied={copied_pass_count}/{len(pass_rows)} "
        f"fail_repaired={repaired_fail_count}/{len(fail_rows)} "
        f"fail_pending={len(pending_fail_rows)}"
    )

    jobs = max(1, args.j)
    with OUTPUT_PATH.open("a", encoding="utf-8") as fh:
        for row in pass_rows:
            pid = str(row.get("pid", "")).strip()
            if pid in existing_output_map:
                continue
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing_output_map[pid] = row
        fh.flush()

        with tqdm(total=len(pending_fail_rows), unit="row") as progress:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                next_index = 0
                future_map: dict = {}

                while next_index < len(pending_fail_rows) or future_map:
                    while next_index < len(pending_fail_rows) and len(future_map) < jobs:
                        row = pending_fail_rows[next_index]
                        future = executor.submit(
                            process_row_safe,
                            row,
                            verify_map,
                            client,
                            model,
                            system_prompt,
                            user_template,
                            request_options,
                        )
                        future_map[future] = row
                        next_index += 1

                    done_future = next(as_completed(future_map))
                    row = future_map.pop(done_future)
                    pid = str(row.get("pid", "")).strip()
                    pid, record, error_text, _ = done_future.result()
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    fh.flush()
                    existing_output_map[pid] = record
                    if error_text is not None:
                        tqdm.write(f"[REPAIR_ERROR] {pid}\n{error_text}\n")
                    progress.update(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
