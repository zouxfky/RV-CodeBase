import re


_TAG_PATTERN_TEMPLATE = r"<{tag}>\s*([\s\S]*?)\s*</{tag}>"
_MAIN_PATTERN = re.compile(r"\b(?:int|auto|void|signed\s+int)\s+main\s*\(")
_SOLVE_PATTERN = re.compile(r"\bvoid\s+solve\s*\(")


def extract_tagged_block(text: str, tag: str) -> str:
    pattern = re.compile(
        _TAG_PATTERN_TEMPLATE.format(tag=re.escape(tag)),
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"missing <{tag}>...</{tag}> block")
    return match.group(1).strip()


def parse_optimize_response(text: str) -> dict:
    code = extract_tagged_block(text, "code")
    return {
        "code": code,
    }


def validate_optimized_code(code: str) -> list[str]:
    errors: list[str] = []
    text = str(code).strip()
    if not text:
        errors.append("empty_code")
    if not _SOLVE_PATTERN.search(text):
        errors.append("missing_solve_function")
    if _MAIN_PATTERN.search(text):
        errors.append("contains_main_function")
    if "Global_SF_N" not in text:
        errors.append("missing_Global_SF_N")
    if "Global_Result" not in text:
        errors.append("missing_Global_Result")
    return errors


def truncate_text(text: str, max_chars: int) -> str:
    value = str(text)
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    keep = max(0, max_chars - 80)
    return value[:keep] + "\n...[truncated]..."
