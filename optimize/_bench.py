import json
import re
from pathlib import Path


_PARAM_KEY_PATTERN = re.compile(r"^param(\d+)$")


def testcase_param_keys(item: dict) -> list[str]:
    pairs: list[tuple[int, str]] = []
    for key in item.keys():
        match = _PARAM_KEY_PATTERN.match(str(key))
        if match:
            pairs.append((int(match.group(1)), str(key)))
    return [key for _, key in sorted(pairs)]


def testcase_to_stdin(testcase_item: dict, *, global_sf_n: int) -> str:
    param_keys = testcase_param_keys(testcase_item)
    if not param_keys:
        raise ValueError("testcase item must contain param1, param2, ...")
    parts: list[str] = []
    for key in param_keys:
        value = testcase_item.get(key)
        if not isinstance(value, str):
            raise ValueError(f"testcase field {key} must be a string")
        parts.append(value.rstrip("\n"))
    parts.append(str(global_sf_n))
    return "\n".join(parts) + "\n"


def build_combined_source(*, solve_code: str, main_program: str) -> str:
    return solve_code.rstrip() + "\n\n" + main_program.rstrip() + "\n"


def build_remote_job_payload(
    *,
    pid: str,
    baseline_code: str,
    optimized_code: str,
    main_program: str,
    testcases: list[dict],
    global_sf_n: int,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
) -> dict:
    cases = []
    for item in testcases:
        cases.append(
            {
                "testcase_index": int(item["testcase_index"]),
                "stdin": testcase_to_stdin(item, global_sf_n=global_sf_n),
            }
        )
    return {
        "pid": pid,
        "baseline_source": build_combined_source(
            solve_code=baseline_code,
            main_program=main_program,
        ),
        "optimized_source": build_combined_source(
            solve_code=optimized_code,
            main_program=main_program,
        ),
        "global_sf_n": global_sf_n,
        "cases": cases,
        "compile_cmd": compile_cmd,
        "compile_timeout": compile_timeout,
        "run_timeout": run_timeout,
        "float_tolerance": 0.01,
    }


def summarize_remote_result(remote_result: dict) -> dict:
    status = str(remote_result.get("status", "")).strip() or "fail"
    baseline_time_ms = float(remote_result.get("baseline_time_ms") or 0.0)
    optimized_time_ms = float(remote_result.get("optimized_time_ms") or 0.0)
    speedup_ratio = float(remote_result.get("speedup_ratio") or 0.0)
    return {
        "status": status,
        "stage": str(remote_result.get("stage", "")),
        "error_type": str(remote_result.get("error_type", "")),
        "message": str(remote_result.get("message", "")),
        "global_sf_n": remote_result.get("global_sf_n"),
        "baseline_time_ms": baseline_time_ms,
        "optimized_time_ms": optimized_time_ms,
        "speedup_ratio": speedup_ratio,
        "baseline_times_ms": list(remote_result.get("baseline_times_ms", [])),
        "optimized_times_ms": list(remote_result.get("optimized_times_ms", [])),
        "cases": list(remote_result.get("cases", [])),
    }


def is_successful_speedup(debug_result: dict) -> bool:
    return (
        str(debug_result.get("status", "")).strip() == "pass"
        and float(debug_result.get("speedup_ratio") or 0.0) > 1.0
    )


def compact_debug_result(debug_result: dict, *, max_output_chars: int = 500) -> dict:
    compact = dict(debug_result)
    cases = []
    for case in compact.get("cases", []):
        item = dict(case)
        for key in ("baseline_output", "optimized_output", "stderr"):
            value = item.get(key)
            if isinstance(value, str) and len(value) > max_output_chars:
                item[key] = value[:max_output_chars] + "\n...[truncated]..."
        cases.append(item)
    compact["cases"] = cases
    return json.loads(json.dumps(compact, ensure_ascii=False))
