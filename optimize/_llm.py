import json
from pathlib import Path
from typing import Any
from urllib import error, request


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


def build_url(config: dict[str, str], endpoint: str) -> str:
    api_base_url = get_config_value(config, "api_base_url")
    if not api_base_url:
        api_base_url = "https://api.openai.com/v1"
    return api_base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def request_timeout(config: dict[str, str]) -> int | None:
    timeout_raw = get_config_value(config, "request_timeout_sec")
    return int(timeout_raw) if timeout_raw else None


def post_json(*, config: dict[str, str], endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = get_config_value(config, "api_key")
    if not api_key:
        raise ValueError("missing api_key in llm_config.env")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        build_url(config, endpoint),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=request_timeout(config)) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response is not JSON: {text[:1000]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("LLM response must be a JSON object")
    return data


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
    if isinstance(response, dict):
        text = response.get("output_text")
        if isinstance(text, str):
            return text
        parts: list[str] = []
        for item in response.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                value = content.get("text")
                if isinstance(value, str):
                    parts.append(value)
        if parts:
            return "".join(parts)

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
    model = get_config_value(config, "model")
    if not model:
        raise ValueError("missing model in llm_config.env")

    request_messages = list(messages)
    system_prompt = get_config_value(config, "system_prompt")
    api_type = get_config_value(config, "api_type", "chat").lower()

    if api_type in {"responses", "response"}:
        response_payload: dict[str, Any] = {
            "model": model,
            "input": request_messages,
            **build_responses_options(config),
        }
        if system_prompt and not any(msg.get("role") == "system" for msg in request_messages):
            response_payload["instructions"] = system_prompt
        response = post_json(config=config, endpoint="responses", payload=response_payload)
        return extract_response_text(response)

    if system_prompt and not any(msg.get("role") == "system" for msg in request_messages):
        request_messages.insert(0, {"role": "system", "content": system_prompt})

    response = post_json(
        config=config,
        endpoint="chat/completions",
        payload={
            "model": model,
            "messages": request_messages,
            **build_request_options(config),
        },
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""
