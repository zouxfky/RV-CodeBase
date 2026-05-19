#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import re
import sys
from pathlib import Path


METHOD_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = METHOD_DIR.parents[1]
REPO_DIR = BENCHMARK_DIR.parent
OPTIMIZE_DIR = REPO_DIR / "optimize"

DEFAULT_DATASET = BENCHMARK_DIR / "datasets/polybenchc.jsonl"
DEFAULT_OUTPUT = BENCHMARK_DIR / "results/polybenchc/default/results.jsonl"
DEFAULT_CONFIG = REPO_DIR / "llm_config.env"
DEFAULT_TMP_DIR = REPO_DIR / "tmp/benchmark_polybenchc"

GENERATE_PROMPT = METHOD_DIR / "generate.md"
REPAIR_PROMPT = METHOD_DIR / "repair.md"
IMPROVE_PROMPT = METHOD_DIR / "improve.md"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))
if str(OPTIMIZE_DIR) not in sys.path:
    sys.path.insert(0, str(OPTIMIZE_DIR))

from common.io import read_jsonl, write_jsonl  # noqa: E402
import _bench  # noqa: E402
import _remote  # noqa: E402


MAIN_PATTERN = re.compile(r"\b(?:int|auto|void|signed\s+int)\s+main\s*\(")
FUNCTION_NAME_PATTERN = re.compile(
    r"(?m)^\s*(?:static\s+)?(?:[A-Za-z_]\w*[\s\*]+)+([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{"
)
TAGGED_CODE_PATTERN = re.compile(r"<code>\s*([\s\S]*?)\s*</code>", re.IGNORECASE)
QUOTED_INCLUDE_PATTERN = re.compile(r'#include\s+"([^"]+)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--tmp-dir", default=str(DEFAULT_TMP_DIR))
    parser.add_argument("--remote-host", default="sg2044")
    parser.add_argument("--ssh-password", default="")
    parser.add_argument("--remote-root", default="/tmp/benchmark_polybenchc")
    parser.add_argument(
        "--compile-cmd",
        default="gcc -x c -std=gnu11 -O3 -march=rv64gcv -mabi=lp64d -I. polybench.c",
    )
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=240)
    parser.add_argument("--ssh-timeout", type=int, default=900)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("-j", "--jobs", type=int, default=1)
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


def compact_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def truncate_text(text: str, *, max_chars: int = 2000) -> str:
    value = str(text).replace("\r", "")
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]..."


def log_sample(sample_id: str, message: str) -> None:
    print(f"[{sample_id}] {message}", file=sys.stderr)


def extract_tagged_code(text: str) -> str:
    match = TAGGED_CODE_PATTERN.search(text)
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


def benchmark_header_name(row: dict) -> str:
    includes = QUOTED_INCLUDE_PATTERN.findall(str(row["prefix_code"]))
    if not includes:
        raise ValueError(f"failed to infer benchmark header name for {row['id']}")
    return includes[-1]


def baseline_block(row: dict) -> str:
    return str(row["prefix_code"]) + str(row["code"]) + str(row["suffix_code"])


def candidate_block(row: dict) -> str:
    return str(row["prefix_code"]) + str(row["code"])


def normalize_main_source(source: str) -> str:
    value = str(source)
    value = value.replace("  polybench_print_instruments;\n", "")
    value = value.replace("\tpolybench_print_instruments;\n", "")
    value = value.replace("  polybench_print_instruments();\n", "")
    value = value.replace("\tpolybench_print_instruments();\n", "")
    return value


def build_translation_unit(
    row: dict,
    *,
    candidate_block_override: str | None = None,
    full_block_override: str | None = None,
) -> str:
    if full_block_override is not None:
        block = str(full_block_override)
    elif candidate_block_override is not None:
        block = str(candidate_block_override) + str(row["suffix_code"])
    else:
        block = baseline_block(row)
    return normalize_main_source(block).rstrip() + "\n"


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
        sample_id=str(row["id"]),
        target_name=primary_function_name(str(row["code"])),
        baseline_code=candidate_block(row),
    )


def build_repair_prompt(row: dict, debug_result: dict) -> str:
    template = load_prompt(REPAIR_PROMPT)
    return render_prompt(
        template,
        sample_id=str(row["id"]),
        target_name=primary_function_name(str(row["code"])),
        debug_result_json=compact_json(debug_result),
    )


def build_improve_prompt(row: dict, debug_result: dict) -> str:
    template = load_prompt(IMPROVE_PROMPT)
    return render_prompt(
        template,
        sample_id=str(row["id"]),
        target_name=primary_function_name(str(row["code"])),
        debug_result_json=compact_json(debug_result),
    )


def call_polybenchc_llm(
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
    return call_polybenchc_llm(
        config_path=config_path,
        row=row,
        phase="polybenchc_generate",
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
    return call_polybenchc_llm(
        config_path=config_path,
        row=row,
        phase="polybenchc_repair",
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
    return call_polybenchc_llm(
        config_path=config_path,
        row=row,
        phase="polybenchc_improve",
        attempt=attempt,
        user_prompt=build_improve_prompt(row, debug_result),
        messages=messages,
    )


def build_local_job_dir(*, tmp_dir: Path, sample_id: str, attempt: int) -> Path:
    return tmp_dir / _remote.safe_name(sample_id) / f"round_{attempt}"


def write_remote_job_files(
    *,
    row: dict,
    job_dir: Path,
    baseline_code: str,
    optimized_code: str,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    ssh_timeout: int,
) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "polybench.h").write_text(str(row["polybench_h"]), encoding="utf-8")
    (job_dir / "polybench.c").write_text(str(row["polybench_c"]), encoding="utf-8")
    (job_dir / benchmark_header_name(row)).write_text(str(row["benchmark_h"]), encoding="utf-8")
    (job_dir / "papi_counters.list").write_text(str(row["papi_counters"]), encoding="utf-8")
    (job_dir / "baseline.cpp").write_text(
        build_translation_unit(row, full_block_override=baseline_code),
        encoding="utf-8",
    )
    (job_dir / "optimized.cpp").write_text(
        build_translation_unit(row, candidate_block_override=optimized_code),
        encoding="utf-8",
    )
    (job_dir / "case_0.in").write_text("", encoding="utf-8")
    (job_dir / "cases.tsv").write_text("0\tcase_0.in\n", encoding="utf-8")
    config_lines = [
        f"PID={json.dumps(str(row['id']))}",
        "GLOBAL_SF_N=1",
        f"COMPILE_CMD={json.dumps(str(compile_cmd))}",
        'COMPILE_TAIL="-lm"',
        f"COMPILE_TIMEOUT={int(compile_timeout)}",
        f"RUN_TIMEOUT={int(run_timeout)}",
        f"WALL_TIMEOUT={max(1, int(ssh_timeout) - 5)}",
        "FLOAT_TOLERANCE=0.01",
    ]
    (job_dir / "runner_config.sh").write_text("\n".join(config_lines) + "\n", encoding="utf-8")


def debug_candidate(
    *,
    row: dict,
    optimized_code: str,
    attempt: int,
    host: str,
    ssh_password: str,
    remote_root: str,
    tmp_dir: Path,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    ssh_timeout: int,
) -> dict:
    baseline_code = baseline_block(row)
    job_dir = build_local_job_dir(tmp_dir=tmp_dir, sample_id=str(row["id"]), attempt=attempt)
    write_remote_job_files(
        row=row,
        job_dir=job_dir,
        baseline_code=baseline_code,
        optimized_code=optimized_code,
        compile_cmd=compile_cmd,
        compile_timeout=compile_timeout,
        run_timeout=run_timeout,
        ssh_timeout=ssh_timeout,
    )
    try:
        remote_result = _remote.run_remote_job(
            host=host,
            remote_root=remote_root,
            local_job_dir=job_dir,
            pid=str(row["id"]),
            attempt=attempt,
            timeout=ssh_timeout,
            ssh_password=ssh_password,
        )
    except Exception as exc:
        return {
            "status": "fail",
            "stage": "remote",
            "error_type": "remote_exec",
            "message": str(exc),
            "global_sf_n": 1,
            "baseline_time_ms": 0.0,
            "optimized_time_ms": 0.0,
            "speedup_ratio": 0.0,
            "baseline_times_ms": [],
            "optimized_times_ms": [],
            "cases": [],
        }
    return _bench.summarize_remote_result(remote_result)


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
        log_sample(sample_id, f"round {attempt}: start remote validation")
        last_debug = debug_candidate(
            row=row,
            optimized_code=current_code,
            attempt=attempt,
            host=args.remote_host,
            ssh_password=args.ssh_password,
            remote_root=args.remote_root,
            tmp_dir=Path(args.tmp_dir),
            compile_cmd=args.compile_cmd,
            compile_timeout=args.compile_timeout,
            run_timeout=args.run_timeout,
            ssh_timeout=args.ssh_timeout,
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

    jobs = max(1, int(args.jobs))
    if jobs == 1:
        for index, row in enumerate(pending, start=1):
            sample_id = str(row["id"])
            print(f"[{index}/{len(pending)}] optimizing {sample_id}", file=sys.stderr)
            result = optimize_sample(row, args)
            replace_result_row(output_path, result)
        return 0

    print(f"并行任务数: {jobs}", file=sys.stderr)
    future_to_meta: dict[concurrent.futures.Future, tuple[int, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        for index, row in enumerate(pending, start=1):
            sample_id = str(row["id"])
            print(f"[submit {index}/{len(pending)}] {sample_id}", file=sys.stderr)
            future = executor.submit(optimize_sample, row, args)
            future_to_meta[future] = (index, sample_id)

        completed_count = 0
        for future in concurrent.futures.as_completed(future_to_meta):
            index, sample_id = future_to_meta[future]
            completed_count += 1
            try:
                result = future.result()
            except Exception as exc:
                result = build_failure_row(
                    sample_id=sample_id,
                    rounds=0,
                    stage="runner",
                    error_type="executor_exception",
                    message=str(exc),
                )
            print(
                f"[done {completed_count}/{len(pending)} | submit {index}] {sample_id} -> {result.get('status')}",
                file=sys.stderr,
            )
            replace_result_row(output_path, result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
