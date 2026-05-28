import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _jsonl_store import JsonlStore, file_lock


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
PROMPTS_DIR = SRC_DIR / "prompts"
CONFIG_PATH = SRC_DIR / "llm_config.env"
SEED_PATH = DATA_DIR / "seed.jsonl"
PROMPT_PATH = PROMPTS_DIR / "1-transform.md"

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert code transformation agent. "
    "Follow the transformation rules exactly and return only transformed code."
)
_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


class TransformOutputError(Exception):
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


def get_prefixed(config: dict[str, str], key: str, default: str = "") -> str:
    specific = config.get(f"transform_{key}", "").strip()
    if specific:
        return specific
    return config.get(key, default).strip()


def get_client(config: dict[str, str]) -> OpenAI:
    api_base_url = get_prefixed(config, "api_base_url")
    api_key = get_prefixed(config, "api_key")
    timeout_raw = get_prefixed(config, "request_timeout_sec")
    timeout = int(timeout_raw) if timeout_raw else None

    if not api_key:
        raise ValueError("missing api_key in llm_config.env")

    key = (api_base_url, api_key, timeout or 0)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client_kwargs = {"api_key": api_key}
        if api_base_url:
            client_kwargs["base_url"] = api_base_url
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        client = OpenAI(**client_kwargs)
        _CLIENT_CACHE[key] = client
    return client


def build_user_prompt(template: str, row: dict) -> str:
    return template.format(code=str(row.get("solution", "")))


def extract_code(text: str) -> str:
    stripped = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    fence_match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        code = fence_match.group(1).strip()
        if code:
            return code
    if stripped:
        return stripped
    raise TransformOutputError(text)


def serialize_response(response: object) -> str:
    if hasattr(response, "model_dump_json"):
        try:
            return response.model_dump_json(indent=2)
        except Exception:
            pass
    return repr(response)


def transform_one(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_template: str,
    row: dict,
    request_options: dict,
) -> str:
    user_prompt = build_user_prompt(user_template, row)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **request_options,
    )
    text = response.choices[0].message.content or ""
    if not text.strip():
        raise TransformOutputError(serialize_response(response))
    return extract_code(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path", nargs="?", default=str(CONFIG_PATH))
    parser.add_argument("-j", type=int, default=1, help="number of parallel transform requests")
    parser.add_argument("-n", type=int, default=None, help="max number of rows to transform this run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = parse_env_file(Path(args.config_path))

    user_template = load_text(PROMPT_PATH)
    system_prompt = get_prefixed(
        config, "system_prompt", config.get("transform_system_prompt", DEFAULT_SYSTEM_PROMPT)
    )
    model = get_prefixed(config, "model")
    if not model:
        raise ValueError("missing model in llm_config.env")

    request_options: dict = {}
    max_tokens_raw = get_prefixed(config, "max_completion_tokens")
    if max_tokens_raw:
        request_options["max_tokens"] = int(max_tokens_raw)
    temperature_raw = get_prefixed(config, "temperature")
    if temperature_raw:
        request_options["temperature"] = float(temperature_raw)

    client = get_client(config)

    with file_lock(SEED_PATH):
        store = JsonlStore(SEED_PATH, flush_every=50)
        pending_rows = [
            row for row in store.rows()
            if str(row.get("pid", "")).strip()
            and str(row.get("stage", "")).strip() == "classified"
        ]
        if args.n is not None:
            pending_rows = pending_rows[: max(0, args.n)]

        jobs = max(1, args.j)
        with tqdm(total=len(pending_rows), unit="row") as progress:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                next_index = 0
                future_map: dict = {}

                while next_index < len(pending_rows) or future_map:
                    while next_index < len(pending_rows) and len(future_map) < jobs:
                        row = pending_rows[next_index]
                        future = executor.submit(
                            transform_one,
                            client,
                            model,
                            system_prompt,
                            user_template,
                            row,
                            request_options,
                        )
                        future_map[future] = row
                        next_index += 1

                    done_future = next(as_completed(future_map))
                    row = future_map.pop(done_future)
                    pid = str(row.get("pid", "")).strip()
                    try:
                        transformed_code = done_future.result()
                        store.update_row(pid, {"code": transformed_code, "stage": "transformed"})
                    except TransformOutputError as exc:
                        store.update_row(pid, {"error": "TransformOutputError"})
                        raw_output = exc.raw_output if exc.raw_output else "<empty>"
                        tqdm.write(f"[RAW_OUTPUT] {pid}\n{raw_output}\n")
                    except Exception as exc:
                        store.update_row(pid, {"error": f"{type(exc).__name__}: {exc}"})
                        tqdm.write(f"[REQUEST_ERROR] {pid} {type(exc).__name__}: {exc}")
                    progress.update(1)
                    store.flush_if_due()

        store.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
