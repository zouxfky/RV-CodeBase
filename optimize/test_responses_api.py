import argparse
from pathlib import Path
import sys
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "llm_config.env"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import _llm


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--prompt",
        default=(
            "Return exactly this text inside a code block tag:\n"
            "<code>\nvoid solve() {}\n</code>"
        ),
    )
    return parser.parse_args()


def response_text(response: Any) -> str:
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


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = _llm.parse_env_file(config_path)

    api_type = _llm.get_config_value(config, "api_type", "chat")
    model = _llm.get_config_value(config, "model")
    api_base_url = _llm.get_config_value(config, "api_base_url")
    if not model:
        raise ValueError(f"missing model in {config_path}")

    client = _llm.get_client(config)
    request_options = _llm.build_responses_options(config)
    system_prompt = _llm.get_config_value(config, "system_prompt")

    kwargs: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": args.prompt}],
        **request_options,
    }
    if system_prompt:
        kwargs["instructions"] = system_prompt

    print(f"config: {config_path}")
    print(f"api_base_url: {api_base_url or '(default)'}")
    print(f"model: {model}")
    print(f"api_type: {api_type}")
    print("request: responses.create")

    response = client.responses.create(**kwargs)
    print(f"response_id: {getattr(response, 'id', '')}")
    print(f"status: {getattr(response, 'status', '')}")
    print("output:")
    print(response_text(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
