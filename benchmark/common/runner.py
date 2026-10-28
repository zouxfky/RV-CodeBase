#!/usr/bin/env python3
"""Runner for the extension benchmarks other than RVV (entry point: benchmark/run.py).

    benchmark/<suite>/dataset.jsonl                          original programs
    benchmark/<suite>/baseline/<method>/<ext>.jsonl          optimized code (manual, <model>)
    benchmark/<suite>/results/<method>/<ext>.jsonl           speedup, status, ... (manual, <model>)

Each dataset row is one whole-file kernel together with its fixed harness:

    id, suite, extension, target_file, code, files{name: text},
    compile_sources, compile_defs, output_filter, preserve_functions,
    required_functions

The LLM rewrites `code` (the kernel file); `files` and `compile_sources` stay
fixed, so the harness and the result check cannot be modified by the model.
"""
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import re
import sys
from pathlib import Path


COMMON_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = COMMON_DIR.parent
REPO_DIR = BENCHMARK_DIR.parent
OPTIMIZE_DIR = REPO_DIR / "optimize"

DEFAULT_CONFIG = REPO_DIR / "llm_config.env"
PROMPT_DIR = COMMON_DIR / "prompts"

for path in (BENCHMARK_DIR, OPTIMIZE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common.io import export_run, method_paths, read_jsonl, write_jsonl  # noqa: E402
from common import local as _local  # noqa: E402
from common.extensions import EXTENSIONS, march_for  # noqa: E402
import _bench  # noqa: E402

# Reuse the RVV runner's code-extraction and result-row helpers.
_spec = importlib.util.spec_from_file_location("rvv_run", BENCHMARK_DIR / "tsvc" / "run.py")
tsvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tsvc)

MAIN_PATTERN = tsvc.MAIN_PATTERN


# Programs of each suite under its target extension (see PROGRAMS.md):
# Mbed TLS -> B, TACLeBench -> Zicond, CMSIS-NN -> IME.
CLASSES = json.loads((BENCHMARK_DIR / "classes.json").read_text())
# TSVC (RVV) has its own runner, benchmark/tsvc/run.py.
SUITE_EXT = {suite: next(iter(c)) for suite, c in CLASSES.items() if suite != "tsvc"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="extension benchmark runner")
    parser.add_argument("--suite", required=True, choices=sorted(SUITE_EXT))
    parser.add_argument("--ext", choices=sorted(set(SUITE_EXT.values())), help="default: the suite's target extension")
    parser.add_argument("--dataset", help="default: <suite>/dataset.jsonl")
    parser.add_argument("--method", help="name under baseline/ and results/; default: the mode (llm mode: required, e.g. the model name)")
    parser.add_argument("--output", help="work file (resumable); default: tmp/benchmark_<suite>_<ext>/<method>.jsonl")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--tmp-dir")
    parser.add_argument("--session-dir")
    parser.add_argument("--platform", default="milkv", help="board name stored in every result row")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--opt", default="-O3")
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=240)
    parser.add_argument("--wall-timeout", type=int, default=1200)
    parser.add_argument("--perf-warmup", type=int, default=1)
    parser.add_argument("--perf-repeats", type=int, default=5)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--llm-j", type=int, default=1)
    parser.add_argument("--run-j", type=int, default=1)
    parser.add_argument("-n", type=int, default=None)
    parser.add_argument("--mode", choices=["llm", "manual"], default="llm")
    args = parser.parse_args()
    args.ext = args.ext or SUITE_EXT[args.suite]
    if args.ext != SUITE_EXT[args.suite]:
        parser.error(f"--ext {args.ext} is not evaluated on {args.suite}")
    suite_dir = BENCHMARK_DIR / args.suite
    if args.mode == "llm" and not args.method:
        parser.error("--method <model name> is required in llm mode")
    args.method = args.method or args.mode
    args.code_path, args.result_path = method_paths(suite_dir, args.method, args.ext)
    args.dataset = args.dataset or str(suite_dir / "dataset.jsonl")
    args.tmp_dir = args.tmp_dir or str(REPO_DIR / f"tmp/benchmark_{args.suite}_{args.ext}")
    args.output = args.output or str(Path(args.tmp_dir) / f"{args.method}.jsonl")
    args.session_dir = args.session_dir or str(REPO_DIR / f"tmp/benchmark_{args.suite}_{args.ext}_sessions")
    # _local.run_benchmark_pipeline passes one compile_cmd through; the real
    # command is built per row in debug_candidate.
    args.compile_cmd = ""
    return args


ARGS: argparse.Namespace | None = None


def compile_cmd_for(row: dict) -> str:
    assert ARGS is not None
    march = march_for(str(row["extension"]))
    parts = [
        ARGS.cc, "-x c -std=gnu11", ARGS.opt, f"-march={march}", "-mabi=lp64d", "-I.",
        str(row.get("compile_defs", "")),
        " ".join(row.get("compile_sources", [])),
    ]
    src = str(BENCHMARK_DIR / str(row.get("suite", "")) / "src")
    return " ".join(p for p in parts if p).replace("{src}", src)


def find_function(code: str, name: str) -> tuple[int, int] | None:
    for match in tsvc.FUNCTION_NAME_PATTERN.finditer(code):
        if match.group(1) != name:
            continue
        closing = tsvc.find_matching_brace(code, match.end() - 1)
        return match.start(), closing + 1
    return None


def restore_preserved(row: dict, code: str) -> str:
    """Put back the original definitions of result-check functions."""
    original = str(row["code"])
    for name in row.get("preserve_functions", []):
        src = find_function(original, name)
        if src is None:
            continue
        body = original[src[0]:src[1]]
        dst = find_function(code, name)
        if dst is None:
            code = code.rstrip() + "\n\n" + body + "\n"
        else:
            code = code[:dst[0]] + body + code[dst[1]:]
    return code


def validate(row: dict, code: str) -> list[str]:
    errors = []
    if not code.strip():
        errors.append("empty_code")
    if MAIN_PATTERN.search(code):
        errors.append("contains_main_function")
    for name in row.get("required_functions", []):
        if not re.search(r"\b" + re.escape(name) + r"\s*\(", code):
            errors.append(f"missing_function:{name}")
    return errors


def render(name: str, **kwargs: str) -> str:
    return tsvc.render_prompt(tsvc.load_prompt(PROMPT_DIR / name), **kwargs)


def call_llm(*, config_path: Path, row: dict, phase: str, attempt: int, user_prompt: str, messages: list[dict]) -> dict:
    import _llm  # noqa: E402

    request_messages = list(messages) + [{"role": "user", "content": user_prompt}]
    text = _llm.call_llm(
        config_path=config_path,
        messages=request_messages,
        pid=str(row["id"]),
        phase=f"ext_{phase}",
        attempt=attempt,
    )
    code = restore_preserved(row, tsvc.extract_tagged_code(text))
    errors = validate(row, code)
    if errors:
        raise ValueError("invalid optimized code: " + ", ".join(errors) + f"; raw_output={tsvc.truncate_text(text)}")
    return {
        "code": code,
        "raw_output": text,
        "messages": request_messages + [{"role": "assistant", "content": f"<code>{code}</code>"}],
    }


def generate_candidate(*, config_path: Path, row: dict, messages: list[dict], attempt: int) -> dict:
    prompt = render(
        "generate.md",
        extension_info=EXTENSIONS[str(row["extension"])]["info"],
        baseline_code=str(row["code"]),
    )
    return call_llm(config_path=config_path, row=row, phase="generate", attempt=attempt, user_prompt=prompt, messages=messages)


def repair_candidate(*, config_path: Path, row: dict, debug_result: dict, messages: list[dict], attempt: int) -> dict:
    prompt = render("repair.md", debug_result_json=tsvc.compact_json(debug_result))
    return call_llm(config_path=config_path, row=row, phase="repair", attempt=attempt, user_prompt=prompt, messages=messages)


def improve_candidate(*, config_path: Path, row: dict, debug_result: dict, messages: list[dict], attempt: int) -> dict:
    prompt = render("improve.md", debug_result_json=tsvc.compact_json(debug_result))
    return call_llm(config_path=config_path, row=row, phase="improve", attempt=attempt, user_prompt=prompt, messages=messages)


def write_job(
    *,
    row: dict,
    job_dir: Path,
    baseline_code: str,
    optimized_code: str,
    baseline_compile_cmd: str,
    optimized_compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    wall_timeout: int,
) -> None:
    assert ARGS is not None
    job_dir.mkdir(parents=True, exist_ok=True)
    for name, text in dict(row.get("files", {})).items():
        (job_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (job_dir / name).write_text(str(text), encoding="utf-8")
    (job_dir / "baseline.cpp").write_text(baseline_code, encoding="utf-8")
    (job_dir / "optimized.cpp").write_text(optimized_code, encoding="utf-8")
    (job_dir / "case_0.in").write_text("", encoding="utf-8")
    (job_dir / "cases.tsv").write_text("0\tcase_0.in\n", encoding="utf-8")
    lines = [
        f"PID={json.dumps(str(row['id']))}",
        "GLOBAL_SF_N=1",
        f"COMPILE_CMD={json.dumps(optimized_compile_cmd)}",
        f"BASELINE_COMPILE_CMD={json.dumps(baseline_compile_cmd)}",
        'COMPILE_TAIL="-lm"',
        f"COMPILE_TIMEOUT={int(compile_timeout)}",
        f"RUN_TIMEOUT={int(run_timeout)}",
        f"WALL_TIMEOUT={max(1, int(wall_timeout) - 5)}",
        "FLOAT_TOLERANCE=0",
        "FLOAT_REL_TOLERANCE=0",
        f"OUTPUT_FILTER={json.dumps(str(row.get('output_filter', '')))}",
        f"EXT_INSN_REGEX={json.dumps(EXTENSIONS[str(row['extension'])]['insn_regex'])}",
        f"PERF_WARMUP={int(ARGS.perf_warmup)}",
        f"PERF_REPEATS={int(ARGS.perf_repeats)}",
        # Baseline binaries are compiled per job; the shared cache is keyed on
        # TSVC support files only, so disable it here.
        "BASELINE_CACHE=0",
    ]
    (job_dir / "runner_config.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_job(job_dir: Path, wall_timeout: int, pid: str) -> dict:
    try:
        return _bench.summarize_remote_result(_local.run_local_job(job_dir=job_dir, timeout=wall_timeout))
    except Exception as exc:
        return {
            "status": "fail", "stage": "run", "error_type": "local_exec", "message": str(exc),
            "global_sf_n": 1, "baseline_time_ms": 0.0, "optimized_time_ms": 0.0, "speedup_ratio": 0.0,
            "baseline_times_ms": [], "optimized_times_ms": [], "cases": [], "ext_insn_count": {},
        }


def debug_candidate(*, row: dict, optimized_code: str, attempt: int, tmp_dir: Path, compile_cmd: str,
                    compile_timeout: int, run_timeout: int, wall_timeout: int) -> dict:
    job_dir = tmp_dir / _local.safe_name(str(row["id"])) / f"round_{attempt}"
    cmd = compile_cmd_for(row)
    write_job(
        row=row, job_dir=job_dir, baseline_code=str(row["code"]), optimized_code=optimized_code,
        baseline_compile_cmd=cmd, optimized_compile_cmd=cmd,
        compile_timeout=compile_timeout, run_timeout=run_timeout, wall_timeout=wall_timeout,
    )
    return run_job(job_dir, wall_timeout, str(row["id"]))


WRITE_LOCK = threading.Lock()


def parallel(rows: list[dict], jobs: int, fn) -> None:
    """Run fn(row) over rows with `jobs` threads (each job is a board subprocess)."""
    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        for fut in [pool.submit(fn, r) for r in rows]:
            fut.result()


def main() -> int:
    global ARGS
    ARGS = args = parse_args()
    extension = args.ext
    output_path = Path(args.output)
    rows = read_jsonl(args.dataset)
    wanted = set(CLASSES[args.suite][extension])
    rows = [r for r in rows if r["id"] in wanted and r["extension"] == extension]
    if args.n is not None:
        rows = rows[: max(0, int(args.n))]
    by_id = {str(r["id"]): r for r in rows}
    if args.mode == "manual":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        manual = {r["id"]: r["code"] for r in read_jsonl(args.code_path)}
        def manual_one(row: dict) -> None:
            code = manual.get(str(row["id"]))
            if code is None:
                return
            debug = debug_candidate(row=row, optimized_code=code, attempt=0, tmp_dir=Path(args.tmp_dir) / "manual",
                                    compile_cmd="", compile_timeout=args.compile_timeout,
                                    run_timeout=args.run_timeout, wall_timeout=args.wall_timeout)
            tsvc.log_sample(str(row["id"]), f"manual status={debug['status']} speedup={debug['speedup_ratio']:.4f} "
                            f"insn={debug.get('ext_insn_count')} {debug.get('message', '')[:300]}")
            result = {"id": str(row["id"]), "mode": "manual", "status": debug["status"],
                      "best_speedup_ratio": debug["speedup_ratio"], "code": code, "debug": debug,
                      "platform": args.platform, "extension": row["extension"], "suite": row["suite"]}
            with WRITE_LOCK:
                tsvc.replace_result_row(output_path, result)
        parallel(rows, args.run_j, manual_one)
        export_run(output_path, None, args.result_path, extension)
        return 0

    def replace_result_row(path: Path, result: dict) -> None:
        src = by_id.get(str(result["id"]), {})
        result.update(platform=args.platform, extension=src.get("extension"), suite=src.get("suite"),
                      cc=args.cc, opt=args.opt)
        tsvc.replace_result_row(path, result)

    completed = tsvc.load_completed(output_path)
    pending = [r for r in rows if str(r["id"]) not in completed]
    print(f"skipped {len(rows) - len(pending)}, pending {len(pending)}", file=sys.stderr)
    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _local.run_benchmark_pipeline(
        pending=pending,
        args=args,
        output_path=output_path,
        replace_result_row=replace_result_row,
        build_success_row=tsvc.build_success_row,
        build_failure_row=tsvc.build_failure_row,
        select_best_candidate=tsvc.select_best_candidate,
        generate_candidate=generate_candidate,
        repair_candidate=repair_candidate,
        improve_candidate=improve_candidate,
        debug_candidate=debug_candidate,
        log_sample=tsvc.log_sample,
    )
    export_run(output_path, args.code_path, args.result_path, extension)
    return 0

