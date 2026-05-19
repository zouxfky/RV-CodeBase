import json
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
PROMPTS_DIR = ROOT_DIR / "prompts"
GENERATE_PROMPT = PROMPTS_DIR / "3-optimize-generate.md"
REPAIR_PROMPT = PROMPTS_DIR / "3-optimize-repair.md"
IMPROVE_PROMPT = PROMPTS_DIR / "3-optimize-improve.md"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import _llm
import _parser


class OptimizeLLMError(ValueError):
    def __init__(self, message: str, *, messages: list[dict] | None = None) -> None:
        super().__init__(message)
        self.messages = messages or []


def load_prompt_text(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"missing prompt file: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"empty prompt file: {path}")
    return text


def render_prompt(template: str, **kwargs: str) -> str:
    rendered = template
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def dumps_compact(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def truncate_text(text: str, *, max_chars: int = 2000) -> str:
    value = str(text).replace("\r", "")
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]..."


def call_optimize_llm(
    *,
    config_path: Path,
    pid: str,
    phase: str,
    attempt: int,
    user_prompt: str,
    messages: list[dict],
) -> dict:
    request_messages = list(messages) + [{"role": "user", "content": user_prompt}]
    text = _llm.call_llm(
        config_path=config_path,
        messages=request_messages,
        pid=pid,
        phase=phase,
        attempt=attempt,
    )
    updated_messages = request_messages + [{"role": "assistant", "content": text}]
    try:
        parsed = _parser.parse_optimize_response(text)
    except Exception as exc:
        raise OptimizeLLMError(
            f"{exc}; raw_output={truncate_text(text)}",
            messages=updated_messages,
        ) from exc
    errors = _parser.validate_optimized_code(parsed["code"])
    if errors:
        raise OptimizeLLMError(
            "invalid optimized code: "
            + ", ".join(errors)
            + f"; raw_output={truncate_text(text)}",
            messages=updated_messages,
        )
    return {
        "code": parsed["code"],
        "raw_output": text,
        "messages": updated_messages,
    }


def build_generate_prompt(
    *,
    pid: str,
    context: dict,
) -> str:
    template = load_prompt_text(GENERATE_PROMPT)
    return render_prompt(
        template,
        pid=pid,
        baseline_code=context["baseline_code"],
        main_program=context["main_program"],
    )


def build_repair_prompt(
    *,
    pid: str,
    debug_result: dict,
) -> str:
    template = load_prompt_text(REPAIR_PROMPT)
    return render_prompt(
        template,
        pid=pid,
        debug_result_json=dumps_compact(debug_result),
    )


def build_improve_prompt(
    *,
    pid: str,
    debug_result: dict,
) -> str:
    template = load_prompt_text(IMPROVE_PROMPT)
    return render_prompt(
        template,
        pid=pid,
        debug_result_json=dumps_compact(debug_result),
    )


def generate_candidate(
    *,
    config_path: Path,
    pid: str,
    context: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    prompt = build_generate_prompt(
        pid=pid,
        context=context,
    )
    return call_optimize_llm(
        config_path=config_path,
        pid=pid,
        phase="3.1_generate",
        attempt=attempt,
        user_prompt=prompt,
        messages=messages,
    )


def repair_candidate(
    *,
    config_path: Path,
    pid: str,
    debug_result: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    prompt = build_repair_prompt(
        pid=pid,
        debug_result=debug_result,
    )
    return call_optimize_llm(
        config_path=config_path,
        pid=pid,
        phase="3.1_repair",
        attempt=attempt,
        user_prompt=prompt,
        messages=messages,
    )


def improve_candidate(
    *,
    config_path: Path,
    pid: str,
    debug_result: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    prompt = build_improve_prompt(
        pid=pid,
        debug_result=debug_result,
    )
    return call_optimize_llm(
        config_path=config_path,
        pid=pid,
        phase="3.1_improve",
        attempt=attempt,
        user_prompt=prompt,
        messages=messages,
    )
