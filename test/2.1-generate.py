import json
import importlib.util
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))


def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IO_API = load_script_module("test_generate_io_api", CURRENT_DIR / "_io.py")
PARSER_API = load_script_module("test_generate_parser_api", CURRENT_DIR / "_parser.py")

write_raw_log = IO_API.write_raw_log
parse_program_response = PARSER_API.parse_program_response
parse_testcase_response = PARSER_API.parse_testcase_response


ROOT_DIR = CURRENT_DIR.parent
PROMPTS_DIR = ROOT_DIR / "prompts"
CONFIG_PATH = ROOT_DIR / "llm_config.env"
PROGRAM_GENERATE_PROMPT = PROMPTS_DIR / "program_generate.md"
PROGRAM_REPAIR_PROMPT = PROMPTS_DIR / "program_repair.md"
TESTCASE_GENERATE_PROMPT = PROMPTS_DIR / "testcase_generate.md"
TESTCASE_REPAIR_PROMPT = PROMPTS_DIR / "testcase_repair.md"

_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


def debug_print(message: str) -> None:
    return None


def render_prompt(template: str, **kwargs: str) -> str:
    rendered = template
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def parse_env_file(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    if not path.exists():
        return config
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def get_config_value(config: dict[str, str], key: str, default: str = "") -> str:
    return config.get(key, default).strip()


def get_client(config: dict[str, str]) -> OpenAI:
    api_base_url = get_config_value(config, "api_base_url")
    api_key = get_config_value(config, "api_key")
    timeout_raw = get_config_value(config, "request_timeout_sec")
    timeout = int(timeout_raw) if timeout_raw else None
    if not api_key:
        raise ValueError("missing api_key in llm_config.env")
    key = (api_base_url, api_key, timeout or 0)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if api_base_url:
            kwargs["base_url"] = api_base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        client = OpenAI(**kwargs)
        _CLIENT_CACHE[key] = client
    return client


def load_prompt_text(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"missing prompt file: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"empty prompt file: {path}")
    return text


def build_request_options(config: dict[str, str]) -> dict[str, Any]:
    request_options: dict[str, Any] = {}
    max_tokens_raw = get_config_value(config, "max_completion_tokens")
    if max_tokens_raw:
        request_options["max_tokens"] = int(max_tokens_raw)
    temperature_raw = get_config_value(config, "temperature")
    if temperature_raw:
        request_options["temperature"] = float(temperature_raw)
    return request_options


def call_llm(
    *,
    config_path: Path,
    messages: list[dict],
    log_dir: Path,
    pid: str,
    phase: str,
    attempt: int,
) -> tuple[str, list[dict]]:
    debug_print(f"[LLM_CALL_START] pid={pid} phase={phase} attempt={attempt} messages={len(messages)}")
    config = parse_env_file(config_path)
    client = get_client(config)
    model = get_config_value(config, "model")
    if not model:
        raise ValueError("missing model in llm_config.env")
    system_prompt = get_config_value(config, "system_prompt")
    request_options = build_request_options(config)

    outbound_messages = list(messages)
    if system_prompt and not any(msg.get("role") == "system" for msg in outbound_messages):
        outbound_messages.insert(0, {"role": "system", "content": system_prompt})

    response = client.chat.completions.create(
        model=model,
        messages=outbound_messages,
        **request_options,
    )
    text = response.choices[0].message.content or ""
    debug_print(f"[LLM_CALL_DONE] pid={pid} phase={phase} attempt={attempt} chars={len(text)}")

    write_raw_log(log_dir, pid, phase, attempt, text)
    updated_messages = list(messages) + [{"role": "assistant", "content": text}]
    return text, updated_messages


def _append_user(messages: list[dict], content: str) -> list[dict]:
    return list(messages) + [{"role": "user", "content": content}]


def generate_program(
    *,
    config_path: Path,
    pid: str,
    code: str,
    messages: list[dict],
    log_dir: Path,
    attempt: int,
) -> dict:
    debug_print(f"[GENERATE_PROGRAM] pid={pid} attempt={attempt}")
    prompt = load_prompt_text(PROGRAM_GENERATE_PROMPT)
    user_content = render_prompt(prompt, pid=pid, code=code)
    text, updated_messages = call_llm(
        config_path=config_path,
        messages=_append_user(messages, user_content),
        log_dir=log_dir,
        pid=pid,
        phase="program_generate",
        attempt=attempt,
    )
    return {
        "raw_output": text,
        "messages": updated_messages,
        "program": parse_program_response(text),
    }


def repair_program(
    *,
    config_path: Path,
    pid: str,
    code: str,
    program: str,
    error: str,
    messages: list[dict],
    log_dir: Path,
    attempt: int,
) -> dict:
    debug_print(f"[REPAIR_PROGRAM] pid={pid} attempt={attempt}")
    prompt = load_prompt_text(PROGRAM_REPAIR_PROMPT)
    user_content = render_prompt(
        prompt,
        pid=pid,
        code=code,
        program=program,
        error=error,
    )
    text, updated_messages = call_llm(
        config_path=config_path,
        messages=_append_user(messages, user_content),
        log_dir=log_dir,
        pid=pid,
        phase="program_repair",
        attempt=attempt,
    )
    return {
        "raw_output": text,
        "messages": updated_messages,
        "program": parse_program_response(text),
    }


def generate_testcase(
    *,
    config_path: Path,
    pid: str,
    code: str,
    program: str,
    messages: list[dict],
    log_dir: Path,
    attempt: int,
) -> dict:
    debug_print(f"[GENERATE_TESTCASE] pid={pid} attempt={attempt}")
    prompt = load_prompt_text(TESTCASE_GENERATE_PROMPT)
    user_content = render_prompt(prompt, pid=pid, code=code, program=program)
    text, updated_messages = call_llm(
        config_path=config_path,
        messages=_append_user(messages, user_content),
        log_dir=log_dir,
        pid=pid,
        phase="testcase_generate",
        attempt=attempt,
    )
    return {
        "raw_output": text,
        "messages": updated_messages,
        "testcase": parse_testcase_response(text),
    }


def repair_testcase(
    *,
    config_path: Path,
    pid: str,
    code: str,
    program: str,
    testcase: list[dict],
    error: str,
    messages: list[dict],
    log_dir: Path,
    attempt: int,
) -> dict:
    debug_print(f"[REPAIR_TESTCASE] pid={pid} attempt={attempt}")
    prompt = load_prompt_text(TESTCASE_REPAIR_PROMPT)
    user_content = render_prompt(
        prompt,
        pid=pid,
        code=code,
        program=program,
        testcase=json.dumps(testcase, ensure_ascii=False, indent=2),
        error=error,
    )
    text, updated_messages = call_llm(
        config_path=config_path,
        messages=_append_user(messages, user_content),
        log_dir=log_dir,
        pid=pid,
        phase="testcase_repair",
        attempt=attempt,
    )
    return {
        "raw_output": text,
        "messages": updated_messages,
        "testcase": parse_testcase_response(text),
    }
