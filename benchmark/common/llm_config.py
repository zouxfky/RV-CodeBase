from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: int = 120
    max_retries: int = 2
    thinking: str = "disabled"


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    api_key: str = ""
    base_url: str = ""
    dimensions: int | None = None
    batch_size: int = 10
    timeout_seconds: int = 120
    max_retries: int = 2


def load_llm_config(path):
    data = read_env_file(path)

    model = get_required(data, "model")
    base_url = get_optional(data, "api_base_url", "base_url", default="")
    api_key = get_optional(data, "api_key", default="")

    return LLMConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=float(get_optional(data, "temperature", default="0.0")),
        max_tokens=parse_optional_int(get_optional(data, "max_tokens", default="")),
        timeout_seconds=int(
            get_optional(
                data,
                "request_timeout",
                "request_timeout_sec",
                "timeout_seconds",
                default="120",
            )
        ),
        max_retries=int(get_optional(data, "max_retries", default="2")),
        thinking=get_optional(data, "thinking", default="disabled").lower(),
    )


def load_embedding_config(path):
    data = read_env_file(path)

    model = get_required(data, "embedding_model")
    base_url = get_optional(
        data,
        "embedding_api_base_url",
        "embedding_base_url",
        default="",
    )
    api_key = get_optional(data, "embedding_api_key", default="")
    dimensions_value = get_optional(data, "embedding_dimensions", default="")

    return EmbeddingConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        dimensions=int(dimensions_value) if dimensions_value else None,
        batch_size=int(get_optional(data, "embedding_batch_size", default="10")),
        timeout_seconds=int(
            get_optional(
                data,
                "embedding_request_timeout_sec",
                "embedding_timeout_seconds",
                "request_timeout_sec",
                "timeout_seconds",
                default="120",
            )
        ),
        max_retries=int(get_optional(data, "embedding_max_retries", default="2")),
    )


def read_env_file(path):
    data = {}
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = strip_quotes(value.strip())
            data[key] = value
    return data


def strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def get_required(data, key):
    value = data.get(key)
    if not value:
        raise ValueError(f"llm_config.env missing required key: {key}")
    return value


def get_optional(data, *keys, default):
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return default


def parse_optional_int(value):
    return int(value) if value else None
