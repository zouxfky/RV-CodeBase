from pathlib import Path
from typing import Any

from openai import OpenAI


_CLIENT_CACHE: dict[tuple[str, str, int], OpenAI] = {}


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


def build_request_options(config: dict[str, str]) -> dict[str, Any]:
    request_options: dict[str, Any] = {}
    max_tokens_raw = get_config_value(config, "max_completion_tokens")
    if max_tokens_raw:
        request_options["max_tokens"] = int(max_tokens_raw)
    temperature_raw = get_config_value(config, "temperature")
    if temperature_raw:
        request_options["temperature"] = float(temperature_raw)
    return request_options


def build_responses_options(config: dict[str, str]) -> dict[str, Any]:
    request_options: dict[str, Any] = {}
    max_tokens_raw = get_config_value(config, "max_completion_tokens")
    if max_tokens_raw:
        request_options["max_output_tokens"] = int(max_tokens_raw)
    temperature_raw = get_config_value(config, "temperature")
    if temperature_raw:
        request_options["temperature"] = float(temperature_raw)
    return request_options


def extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str):
        return text

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def call_llm(
    *,
    config_path: Path,
    messages: list[dict],
    pid: str,
    phase: str,
    attempt: int,
) -> str:
    config = parse_env_file(config_path)
    client = get_client(config)
    model = get_config_value(config, "model")
    if not model:
        raise ValueError("missing model in llm_config.env")

    request_messages = list(messages)
    system_prompt = get_config_value(config, "system_prompt")
    api_type = get_config_value(config, "api_type", "chat").lower()

    if api_type in {"responses", "response"}:
        response_kwargs: dict[str, Any] = {
            "model": model,
            "input": request_messages,
            **build_responses_options(config),
        }
        if system_prompt and not any(msg.get("role") == "system" for msg in request_messages):
            response_kwargs["instructions"] = system_prompt
        response = client.responses.create(**response_kwargs)
        return extract_response_text(response)

    if system_prompt and not any(msg.get("role") == "system" for msg in request_messages):
        request_messages.insert(0, {"role": "system", "content": system_prompt})

    response = client.chat.completions.create(
        model=model,
        messages=request_messages,
        **build_request_options(config),
    )
    return response.choices[0].message.content or ""
