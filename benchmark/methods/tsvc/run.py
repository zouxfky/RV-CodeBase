#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


METHOD_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = METHOD_DIR.parents[1]
REPO_DIR = BENCHMARK_DIR.parent
OPTIMIZE_DIR = REPO_DIR / "optimize"
METHODS_DIR = BENCHMARK_DIR / "methods"

DEFAULT_DATASET = BENCHMARK_DIR / "datasets/tsvc.jsonl"
DEFAULT_OUTPUT = BENCHMARK_DIR / "results/tsvc/default/results.jsonl"
DEFAULT_CONFIG = REPO_DIR / "llm_config.env"
DEFAULT_TMP_DIR = REPO_DIR / "tmp/benchmark_tsvc"
DEFAULT_SESSION_DIR = REPO_DIR / "tmp/benchmark_tsvc_sessions"

COMMON_PROMPT_DIR = BENCHMARK_DIR / "common" / "prompts"
LOCAL_PROMPT_DIR = METHOD_DIR / "prompts"
GENERATE_PROMPT = LOCAL_PROMPT_DIR / "generate.md"
REPAIR_PROMPT = COMMON_PROMPT_DIR / "repair.md"
IMPROVE_PROMPT = COMMON_PROMPT_DIR / "improve.md"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))
if str(OPTIMIZE_DIR) not in sys.path:
    sys.path.insert(0, str(OPTIMIZE_DIR))
if str(METHODS_DIR) not in sys.path:
    sys.path.insert(0, str(METHODS_DIR))

from common.io import read_jsonl, write_jsonl  # noqa: E402
import _bench  # noqa: E402
import _local  # noqa: E402


DRIVER_INCLUDE_MARKER = '#include "array_defs.h"\n'
MAIN_PATTERN = re.compile(r"\b(?:int|auto|void|signed\s+int)\s+main\s*\(")
FUNCTION_NAME_PATTERN = re.compile(
    r"(?m)^\s*(?:static\s+)?(?:[A-Za-z_]\w*[\s\*]+)+([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{"
)
MEMALIGN_CALL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])memalign\s*\(")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--tmp-dir", default=str(DEFAULT_TMP_DIR))
    parser.add_argument("--session-dir", default=str(DEFAULT_SESSION_DIR))
    parser.add_argument(
        "--compile-cmd",
        default="gcc -x c -std=gnu11 -O3 -march=rv64gcv -mabi=lp64d -I. common.c dummy.c globals.c -lm",
    )
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=240)
    parser.add_argument("--wall-timeout", type=int, default=900)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--llm-j", type=int, default=1)
    parser.add_argument("--run-j", type=int, default=1)
    parser.add_argument("-n", type=int, default=None)
    return parser.parse_args()


def load_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"empty prompt file: {path}")
    return text


def render_prompt(template: str, **kwargs: str) -> str:
    rendered = template
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def extract_tagged_code(text: str) -> str:
    match = re.search(r"<code>\s*([\s\S]*?)\s*</code>", text, re.IGNORECASE)
    if not match:
        raise ValueError("missing <code>...</code> block")
    return match.group(1).strip()


def primary_function_name(code: str) -> str:
    match = FUNCTION_NAME_PATTERN.search(code)
    if not match:
        raise ValueError("failed to infer target function name from baseline code")
    return match.group(1)


def validate_candidate_code(*, target_name: str, code: str) -> list[str]:
    errors: list[str] = []
    text = str(code).strip()
    if not text:
        errors.append("empty_code")
    if MAIN_PATTERN.search(text):
        errors.append("contains_main_function")
    if not re.search(r"\b" + re.escape(target_name) + r"\s*\(", text):
        errors.append(f"missing_target_function:{target_name}")
    return errors


def split_driver(driver_code: str) -> tuple[str, str]:
    idx = driver_code.find(DRIVER_INCLUDE_MARKER)
    if idx < 0:
        raise ValueError("failed to locate TSVC driver include prelude")
    end = idx + len(DRIVER_INCLUDE_MARKER)
    while end < len(driver_code) and driver_code[end] in "\r\n":
        end += 1
    return driver_code[:end], driver_code[end:]


def transform_driver(driver_code: str) -> str:
    return driver_code.replace(
        '    printf("%10.3f\\t%f\\n", taken, result);\n',
        '    printf("%f\\n", result);\n',
    )


def kernel_block(row: dict, code_override: str | None = None) -> str:
    code = row["code"] if code_override is None else code_override
    return str(row["prefix_code"]) + str(code) + str(row["suffix_code"])


def build_translation_unit(row: dict, code_override: str | None = None) -> str:
    driver = transform_driver(str(row["driver_code"]))
    include_prelude, driver_body = split_driver(driver)
    return (
        include_prelude.rstrip()
        + "\n\n"
        + kernel_block(row, code_override=code_override).rstrip()
        + "\n\n"
        + driver_body.rstrip()
        + "\n"
    )


def normalize_common_impl(text: str) -> str:
    value = str(text).replace("#include <malloc.h>\n", "")
    marker = "#include <string.h>\n"
    helper = (
        marker
        + "\n"
        + "static void *tsvc_memalign(size_t alignment, size_t size)\n"
        + "{\n"
        + "    void *ptr = NULL;\n"
        + "    if (posix_memalign(&ptr, alignment, size) != 0) return NULL;\n"
        + "    return ptr;\n"
        + "}\n"
    )
    if "tsvc_memalign(" not in value:
        value = value.replace(marker, helper, 1)
    return MEMALIGN_CALL_PATTERN.sub("tsvc_memalign(", value)


def compact_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def truncate_text(text: str, *, max_chars: int = 2000) -> str:
    value = str(text).replace("\r", "")
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]..."


def log_sample(sample_id: str, message: str) -> None:
    print(f"[{sample_id}] {message}", file=sys.stderr)


def load_completed(path: Path) -> dict[str, dict]:
    rows = read_jsonl(path) if path.exists() else []
    return {str(row.get("id", "")).strip(): row for row in rows if str(row.get("id", "")).strip()}


def replace_result_row(path: Path, row: dict) -> None:
    current = load_completed(path)
    current[str(row["id"])] = row
    ordered_rows = list(current.values())
    ordered_rows.sort(key=lambda item: str(item.get("id", "")))
    write_jsonl(path, ordered_rows)


def build_generate_prompt(row: dict) -> str:
    template = load_prompt(GENERATE_PROMPT)
    return render_prompt(
        template,
        baseline_code=kernel_block(row),
    )


def build_repair_prompt(row: dict, debug_result: dict) -> str:
    template = load_prompt(REPAIR_PROMPT)
    return render_prompt(
        template,
        debug_result_json=compact_json(debug_result),
    )


def build_improve_prompt(row: dict, debug_result: dict) -> str:
    template = load_prompt(IMPROVE_PROMPT)
    return render_prompt(
        template,
        debug_result_json=compact_json(debug_result),
    )


def call_tsvc_llm(
    *,
    config_path: Path,
    row: dict,
    phase: str,
    attempt: int,
    user_prompt: str,
    messages: list[dict],
) -> dict:
    import _llm  # noqa: E402

    request_messages = list(messages) + [{"role": "user", "content": user_prompt}]
    text = _llm.call_llm(
        config_path=config_path,
        messages=request_messages,
        pid=str(row["id"]),
        phase=phase,
        attempt=attempt,
    )
    updated_messages = request_messages + [{"role": "assistant", "content": text}]
    code = extract_tagged_code(text)
    target_name = primary_function_name(str(row["code"]))
    errors = validate_candidate_code(target_name=target_name, code=code)
    if errors:
        raise ValueError(
            "invalid optimized code: "
            + ", ".join(errors)
            + f"; raw_output={truncate_text(text)}"
        )
    return {
        "code": code,
        "raw_output": text,
        "messages": updated_messages,
    }


def generate_candidate(
    *,
    config_path: Path,
    row: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    return call_tsvc_llm(
        config_path=config_path,
        row=row,
        phase="tsvc_generate",
        attempt=attempt,
        user_prompt=build_generate_prompt(row),
        messages=messages,
    )


def repair_candidate(
    *,
    config_path: Path,
    row: dict,
    debug_result: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    return call_tsvc_llm(
        config_path=config_path,
        row=row,
        phase="tsvc_repair",
        attempt=attempt,
        user_prompt=build_repair_prompt(row, debug_result),
        messages=messages,
    )


def improve_candidate(
    *,
    config_path: Path,
    row: dict,
    debug_result: dict,
    messages: list[dict],
    attempt: int,
) -> dict:
    return call_tsvc_llm(
        config_path=config_path,
        row=row,
        phase="tsvc_improve",
        attempt=attempt,
        user_prompt=build_improve_prompt(row, debug_result),
        messages=messages,
    )


def build_local_job_dir(*, tmp_dir: Path, sample_id: str, attempt: int) -> Path:
    return tmp_dir / _local.safe_name(sample_id) / f"round_{attempt}"


def write_local_job_files(
    *,
    row: dict,
    job_dir: Path,
    baseline_code: str,
    optimized_code: str,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    wall_timeout: int,
) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "common.h").write_text(str(row["common"]), encoding="utf-8")
    (job_dir / "array_defs.h").write_text(str(row["array_defs"]), encoding="utf-8")
    (job_dir / "common.c").write_text(normalize_common_impl(str(row["common_impl"])), encoding="utf-8")
    (job_dir / "dummy.c").write_text(str(row["dummy"]), encoding="utf-8")
    (job_dir / "globals.c").write_text(str(row["globals"]), encoding="utf-8")
    (job_dir / "baseline.cpp").write_text(
        build_translation_unit(row, code_override=baseline_code),
        encoding="utf-8",
    )
    (job_dir / "optimized.cpp").write_text(
        build_translation_unit(row, code_override=optimized_code),
        encoding="utf-8",
    )
    (job_dir / "case_0.in").write_text("", encoding="utf-8")
    (job_dir / "cases.tsv").write_text("0\tcase_0.in\n", encoding="utf-8")
    config_lines = [
        f"PID={json.dumps(str(row['id']))}",
        "GLOBAL_SF_N=1",
        f"COMPILE_CMD={json.dumps(str(compile_cmd))}",
        f"COMPILE_TIMEOUT={int(compile_timeout)}",
        f"RUN_TIMEOUT={int(run_timeout)}",
        f"WALL_TIMEOUT={max(1, int(wall_timeout) - 5)}",
        "FLOAT_TOLERANCE=0.01",
    ]
    (job_dir / "runner_config.sh").write_text("\n".join(config_lines) + "\n", encoding="utf-8")


def debug_candidate(
    *,
    row: dict,
    optimized_code: str,
    attempt: int,
    tmp_dir: Path,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    wall_timeout: int,
) -> dict:
    baseline_code = kernel_block(row)
    job_dir = build_local_job_dir(tmp_dir=tmp_dir, sample_id=str(row["id"]), attempt=attempt)
    write_local_job_files(
        row=row,
        job_dir=job_dir,
        baseline_code=baseline_code,
        optimized_code=optimized_code,
        compile_cmd=compile_cmd,
        compile_timeout=compile_timeout,
        run_timeout=run_timeout,
        wall_timeout=wall_timeout,
    )
    try:
        local_result = _local.run_local_job(job_dir=job_dir, timeout=wall_timeout)
    except Exception as exc:
        return {
            "status": "fail",
            "stage": "run",
            "error_type": "local_exec",
            "message": str(exc),
            "global_sf_n": 1,
            "baseline_time_ms": 0.0,
            "optimized_time_ms": 0.0,
            "speedup_ratio": 0.0,
            "baseline_times_ms": [],
            "optimized_times_ms": [],
            "cases": [],
        }
    return _bench.summarize_remote_result(local_result)


def is_successful_speedup(debug_result: dict) -> bool:
    return (
        str(debug_result.get("status", "")).strip() == "pass"
        and float(debug_result.get("speedup_ratio") or 0.0) > 1.0
    )


def build_success_row(
    *,
    sample_id: str,
    rounds: int,
    best_round: int,
    code: str,
    debug_result: dict,
    message: str,
    rounds_history: list | None = None,
) -> dict:
    return {
        "id": sample_id,
        "status": "success",
        "rounds": rounds,
        "best_round": best_round,
        "best_speedup_ratio": float(debug_result.get("speedup_ratio") or 0.0),
        "baseline_time_ms": float(debug_result.get("baseline_time_ms") or 0.0),
        "optimized_time_ms": float(debug_result.get("optimized_time_ms") or 0.0),
        "code": code,
        "message": message,
        "debug": debug_result,
        "rounds_history": list(rounds_history or []),
    }


def build_failure_row(
    *,
    sample_id: str,
    rounds: int,
    stage: str,
    error_type: str,
    message: str,
    code: str = "",
    debug_result: dict | None = None,
    rounds_history: list | None = None,
) -> dict:
    return {
        "id": sample_id,
        "status": "fail",
        "rounds": rounds,
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "code": code,
        "debug": debug_result or {},
        "rounds_history": list(rounds_history or []),
    }


def select_best_candidate(best_candidate: dict | None, candidate_record: dict) -> dict | None:
    debug = candidate_record["debug_result"]
    if not is_successful_speedup(debug):
        return best_candidate
    if best_candidate is None:
        return candidate_record
    if float(debug["speedup_ratio"]) > float(best_candidate["debug_result"]["speedup_ratio"]):
        return candidate_record
    return best_candidate


def optimize_sample(row: dict, args: argparse.Namespace) -> dict:
    sample_id = str(row["id"])
    messages: list[dict] = []
    best_candidate: dict | None = None
    current_code = ""
    last_debug: dict | None = None
    rounds_done = 0

    log_sample(sample_id, "start optimization")

    for attempt in range(1, max(1, min(3, int(args.max_rounds))) + 1):
        rounds_done = attempt
        if attempt == 1:
            phase = "generate"
        elif last_debug is not None and str(last_debug.get("status", "")) != "pass":
            phase = "repair"
        else:
            phase = "improve"
        log_sample(sample_id, f"round {attempt}: start {phase}")
        try:
            if attempt == 1:
                log_sample(sample_id, f"round {attempt}: calling LLM generate")
                llm_result = generate_candidate(
                    config_path=Path(args.config),
                    row=row,
                    messages=messages,
                    attempt=attempt,
                )
            elif last_debug is not None and str(last_debug.get("status", "")) != "pass":
                log_sample(sample_id, f"round {attempt}: calling LLM repair")
                llm_result = repair_candidate(
                    config_path=Path(args.config),
                    row=row,
                    debug_result=last_debug,
                    messages=messages,
                    attempt=attempt,
                )
            else:
                log_sample(sample_id, f"round {attempt}: calling LLM improve")
                llm_result = improve_candidate(
                    config_path=Path(args.config),
                    row=row,
                    debug_result=last_debug or {},
                    messages=messages,
                    attempt=attempt,
                )
        except Exception as exc:
            log_sample(sample_id, f"round {attempt}: LLM failed: {exc}")
            return build_failure_row(
                sample_id=sample_id,
                rounds=rounds_done,
                stage="llm",
                error_type="llm_generate",
                message=str(exc),
                code=current_code,
                debug_result=last_debug,
            )

        current_code = llm_result["code"]
        messages = llm_result["messages"]
        log_sample(sample_id, f"round {attempt}: LLM returned candidate ({len(current_code)} chars)")
        log_sample(sample_id, f"round {attempt}: start local validation")
        last_debug = debug_candidate(
            row=row,
            optimized_code=current_code,
            attempt=attempt,
            tmp_dir=Path(args.tmp_dir),
            compile_cmd=args.compile_cmd,
            compile_timeout=args.compile_timeout,
            run_timeout=args.run_timeout,
            wall_timeout=args.wall_timeout,
        )
        log_sample(
            sample_id,
            "round "
            + str(attempt)
            + ": validation result "
            + f"status={last_debug.get('status')} stage={last_debug.get('stage')} "
            + f"error={last_debug.get('error_type') or '-'} "
            + f"speedup={float(last_debug.get('speedup_ratio') or 0.0):.6f}",
        )
        best_candidate = select_best_candidate(
            best_candidate,
            {
                "round": attempt,
                "code": current_code,
                "debug_result": last_debug,
            },
        )

    if best_candidate is not None:
        log_sample(
            sample_id,
            f"finished with best round {int(best_candidate['round'])}, "
            f"speedup={float(best_candidate['debug_result'].get('speedup_ratio') or 0.0):.6f}",
        )
        return build_success_row(
            sample_id=sample_id,
            rounds=rounds_done,
            best_round=int(best_candidate["round"]),
            code=str(best_candidate["code"]),
            debug_result=best_candidate["debug_result"],
            message="",
        )

    if last_debug is not None and str(last_debug.get("status", "")) == "pass":
        log_sample(
            sample_id,
            f"finished without speedup > 1.0, latest speedup={float(last_debug.get('speedup_ratio') or 0.0):.6f}",
        )
        return build_success_row(
            sample_id=sample_id,
            rounds=rounds_done,
            best_round=rounds_done,
            code=current_code,
            debug_result=last_debug,
            message=(
                f"no valid speedup > 1.0 found; latest speedup_ratio="
                f"{float(last_debug.get('speedup_ratio') or 0.0):.6f}"
            ),
        )

    log_sample(
        sample_id,
        f"finished with failure stage={str((last_debug or {}).get('stage', 'performance'))} "
        f"error={str((last_debug or {}).get('error_type', 'no_speedup'))}",
    )
    return build_failure_row(
        sample_id=sample_id,
        rounds=rounds_done,
        stage=str((last_debug or {}).get("stage", "performance")),
        error_type=str((last_debug or {}).get("error_type", "no_speedup")),
        message=str((last_debug or {}).get("message", "no valid speedup > 1.0 found")),
        code=current_code,
        debug_result=last_debug,
    )


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    dataset_rows = read_jsonl(args.dataset)
    if args.n is not None:
        dataset_rows = dataset_rows[: max(0, int(args.n))]
    completed = load_completed(output_path)
    pending = [row for row in dataset_rows if str(row["id"]) not in completed]

    print(f"已跳过 {len(dataset_rows) - len(pending)} 条，待优化 {len(pending)} 条", file=sys.stderr)

    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _local.run_benchmark_pipeline(
        pending=pending,
        args=args,
        output_path=output_path,
        replace_result_row=replace_result_row,
        build_success_row=build_success_row,
        build_failure_row=build_failure_row,
        select_best_candidate=select_best_candidate,
        generate_candidate=generate_candidate,
        repair_candidate=repair_candidate,
        improve_candidate=improve_candidate,
        debug_candidate=debug_candidate,
        log_sample=log_sample,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
