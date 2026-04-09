import json
import re


PROGRAM_TAG = "program"
TESTCASE_TAG = "testcase"
_PARAM_KEY_PATTERN = re.compile(r"^param(\d+)$")


def extract_tagged_block(text: str, tag: str) -> str:
    pattern = re.compile(
        rf"<{tag}>\s*([\s\S]*?)\s*</{tag}>",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"missing <{tag}>...</{tag}> block")
    return match.group(1).strip()


def parse_program_response(text: str) -> str:
    return extract_tagged_block(text, PROGRAM_TAG)


def parse_testcase_response(text: str) -> list[dict]:
    block = extract_tagged_block(text, TESTCASE_TAG)
    payload = json.loads(block)
    if not isinstance(payload, list):
        raise ValueError("testcase payload must be a JSON array")
    return payload


def testcase_param_keys(item: dict) -> list[str]:
    pairs: list[tuple[int, str]] = []
    for key in item.keys():
        match = _PARAM_KEY_PATTERN.match(str(key))
        if not match:
            continue
        pairs.append((int(match.group(1)), key))
    return [key for _, key in sorted(pairs)]


def _validate_testcase_items(
    testcases: list[dict],
    *,
    require_consecutive_indices: bool,
) -> tuple[list[str], list[int]]:
    failed: list[str] = []
    if not isinstance(testcases, list):
        return ["testcase_not_array"], []
    if not testcases:
        failed.append("empty_testcase")
    indices: list[int] = []
    for item in testcases:
        if not isinstance(item, dict):
            failed.append("testcase_item_not_object")
            continue
        if "testcase_index" not in item:
            failed.append("missing_testcase_index")
            continue
        try:
            indices.append(int(item["testcase_index"]))
        except Exception:
            failed.append("invalid_testcase_index")
            continue
        param_keys = testcase_param_keys(item)
        if not param_keys:
            failed.append("missing_params")
            continue
        expected_param_keys = [f"param{i}" for i in range(1, len(param_keys) + 1)]
        if param_keys != expected_param_keys:
            failed.append("unexpected_param_sequence")
        for key in param_keys:
            if not isinstance(item.get(key), str):
                failed.append("param_not_string")
    if len(indices) != len(set(indices)):
        failed.append("duplicate_testcase_index")
    if require_consecutive_indices and indices and sorted(indices) != list(range(1, len(indices) + 1)):
        failed.append("unexpected_testcase_index_sequence")
    return sorted(set(failed)), indices


def validate_testcase_shape(testcases: list[dict]) -> list[str]:
    failed, _ = _validate_testcase_items(
        testcases,
        require_consecutive_indices=True,
    )
    return failed


def validate_partial_testcase_shape(
    testcases: list[dict],
    *,
    allowed_indices: set[int] | None = None,
) -> list[str]:
    failed, indices = _validate_testcase_items(
        testcases,
        require_consecutive_indices=False,
    )
    if allowed_indices is not None:
        for index in indices:
            if index not in allowed_indices:
                failed.append("unexpected_testcase_index")
                break
    return sorted(set(failed))


def testcase_to_stdin(testcase_item: dict, *, global_sf_n: str | None = None) -> str:
    if not isinstance(testcase_item, dict):
        raise ValueError("testcase item must be an object")
    param_keys = testcase_param_keys(testcase_item)
    if not param_keys:
        raise ValueError("testcase item must contain param1, param2, ...")
    parts: list[str] = []
    for key in param_keys:
        value = testcase_item.get(key)
        if not isinstance(value, str):
            raise ValueError(f"testcase item field {key} must be a string")
        parts.append(value.rstrip("\n"))
    if global_sf_n is not None:
        parts.append(str(global_sf_n).rstrip("\n"))
    return "\n".join(parts) + "\n"


def merge_testcase_updates(base_testcases: list[dict], updates: list[dict]) -> list[dict]:
    update_map: dict[int, dict] = {}
    for item in updates:
        update_map[int(item["testcase_index"])] = item
    merged: list[dict] = []
    for item in base_testcases:
        index = int(item["testcase_index"])
        merged.append(update_map.get(index, item))
    return merged
