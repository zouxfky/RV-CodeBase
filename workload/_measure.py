from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import subprocess
import sys
import time
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from _log import debug_print
from _parser import testcase_to_stdin, validate_testcase_shape


SF_START = 10
SF_MULTIPLIER = 10
SF_SLOW_MULTIPLIER = 5
SF_FAST_THRESHOLD_MS = 1_000
TARGET_RUNTIME_MS = 10_000
MAX_GLOBAL_SF_N = 1_000_000_000


def detect_default_compiler() -> str:
    candidates = [
        "g++-15",
        "g++-14",
        "g++-13",
        "g++-12",
        "g++-11",
        "g++-10",
        "g++",
    ]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "g++"


def compile_program(
    *,
    pid: str,
    code: str,
    program: str,
    tmp_dir: Path,
    compiler: str,
    cpp_std: str,
    compile_timeout: int,
    suffix: str,
) -> tuple[int, Path, str]:
    debug_print(f"[COMPILE_START] pid={pid} suffix={suffix}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    source = code.rstrip() + "\n\n" + program.rstrip() + "\n"
    src_path = tmp_dir / f"{pid}.{suffix}.cpp"
    bin_path = tmp_dir / f"{pid}.{suffix}.bin"
    src_path.write_text(source, encoding="utf-8")
    completed = subprocess.run(
        [
            compiler,
            "-std=" + cpp_std,
            "-O2",
            "-pipe",
            str(src_path),
            "-o",
            str(bin_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=compile_timeout,
        check=False,
    )
    message = (completed.stderr or "").strip()
    debug_print(f"[COMPILE_DONE] pid={pid} suffix={suffix} returncode={completed.returncode}")
    return completed.returncode, bin_path, message


def check_program(
    *,
    pid: str,
    code: str,
    program: str,
    tmp_dir: Path,
    compiler: str,
    cpp_std: str,
    compile_timeout: int,
) -> dict:
    try:
        returncode, bin_path, message = compile_program(
            pid=pid,
            code=code,
            program=program,
            tmp_dir=tmp_dir,
            compiler=compiler,
            cpp_std=cpp_std,
            compile_timeout=compile_timeout,
            suffix="program",
        )
    except subprocess.TimeoutExpired:
        return {
            "pid": pid,
            "status": "fail",
            "error_type": "compile",
            "message": f"compile timeout after {compile_timeout}s",
        }
    except Exception as exc:
        return {
            "pid": pid,
            "status": "fail",
            "error_type": "compile",
            "message": str(exc),
        }
    if returncode == 0:
        debug_print(f"[CHECK_PROGRAM_PASS] pid={pid}")
        return {
            "pid": pid,
            "status": "pass",
            "error_type": "",
            "message": "",
            "bin_path": str(bin_path),
        }
    debug_print(f"[CHECK_PROGRAM_FAIL] pid={pid}")
    return {
        "pid": pid,
        "status": "fail",
        "error_type": "compile",
        "message": message or "compile failed",
    }


def check_testcases(
    *,
    pid: str,
    code: str,
    program: str,
    testcase: list[dict],
    tmp_dir: Path,
    compiler: str,
    cpp_std: str,
    compile_timeout: int,
    run_timeout: int,
    bin_path: Path | None = None,
) -> dict:
    def build_case_result(
        *,
        testcase_index: int,
        status: str,
        time_ms: int,
        message: str,
    ) -> dict:
        return {
            "testcase_index": testcase_index,
            "status": status,
            "time": time_ms,
            "message": message,
        }

    def build_summary(
        *,
        global_sf_n: int,
        case_results: list[dict],
    ) -> dict:
        pass_count = sum(1 for case in case_results if case.get("status") == "pass")
        fail_count = sum(1 for case in case_results if case.get("status") == "fail")
        return {
            "pid": pid,
            "global_sf_n": global_sf_n,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "results": case_results,
        }

    def build_too_slow_message(*, global_sf_n: int, testcase_index: int) -> str:
        return (
            f"runtime exceeded {run_timeout}s for testcase_index={testcase_index} at "
            f"Global_SF_N={global_sf_n}. The non-Global_SF_N parameters make the program too slow. "
            f"Please reduce the workload slightly."
        )

    def build_too_small_message(
        *,
        global_sf_n: int,
        testcase_index: int,
        elapsed_ms: int,
        reference_indices: list[int],
    ) -> str:
        if reference_indices:
            reference_text = ",".join(str(index) for index in reference_indices)
            return (
                f"testcase_index={testcase_index} is too small at Global_SF_N={global_sf_n}: "
                f"measured runtime {elapsed_ms}ms did not exceed {TARGET_RUNTIME_MS}ms. "
                f"Please rebuild this testcase by referring to the passed testcases at indices "
                f"[{reference_text}]."
            )
        return (
            f"testcase_index={testcase_index} is too small at Global_SF_N={global_sf_n}: "
            f"measured runtime {elapsed_ms}ms did not exceed {TARGET_RUNTIME_MS}ms. "
            f"Please rebuild this testcase."
        )

    def build_scale_not_reached_message(global_sf_n: int) -> str:
        return (
            f"all testcase runtimes stayed at or below {TARGET_RUNTIME_MS}ms up to "
            f"Global_SF_N={global_sf_n}. The testcases are too small and should be rebuilt "
            f"by referring to any passed testcases once available."
        )

    def build_global_failure(message: str) -> dict:
        return build_summary(
            global_sf_n=0,
            case_results=[
                build_case_result(
                    testcase_index=0,
                    status="fail",
                    time_ms=0,
                    message=message,
                )
            ],
        )

    def run_one_case(
        *,
        testcase_item: dict,
        global_sf_n: int,
    ) -> dict:
        index = int(testcase_item["testcase_index"])
        start = time.perf_counter()
        try:
            stdin_text = testcase_to_stdin(testcase_item, global_sf_n=str(global_sf_n))
            run_completed = subprocess.run(
                [str(bin_path)],
                input=stdin_text,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=run_timeout,
                check=False,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            stderr_text = (run_completed.stderr or "").strip()
            if run_completed.returncode == 0:
                debug_print(
                    f"[RUN_TESTCASE_PASS] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
                )
                return build_case_result(
                    testcase_index=index,
                    status="pass",
                    time_ms=elapsed_ms,
                    message="",
                )
            debug_print(
                f"[RUN_TESTCASE_FAIL] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
            )
            return build_case_result(
                testcase_index=index,
                status="fail",
                time_ms=elapsed_ms,
                message=stderr_text or f"binary exited with code {run_completed.returncode}",
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            debug_print(
                f"[RUN_TESTCASE_TIMEOUT] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
            )
            return build_case_result(
                testcase_index=index,
                status="fail",
                time_ms=elapsed_ms,
                message=build_too_slow_message(
                    global_sf_n=global_sf_n,
                    testcase_index=index,
                ),
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            debug_print(
                f"[RUN_TESTCASE_EXCEPTION] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
            )
            debug_print(
                f"[RUN_TESTCASE_EXCEPTION_DETAIL] pid={pid} global_sf_n={global_sf_n} "
                f"testcase_index={index} message={str(exc)}"
            )
            return build_case_result(
                testcase_index=index,
                status="fail",
                time_ms=elapsed_ms,
                message=str(exc),
            )

    def run_suite_at_scale(
        *,
        global_sf_n: int,
        items: list[dict],
    ) -> list[dict]:
        case_results_by_index: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(items))) as executor:
            future_map = {}
            for item in items:
                testcase_index = int(item["testcase_index"])
                future = executor.submit(
                    run_one_case,
                    testcase_item=item,
                    global_sf_n=global_sf_n,
                )
                future_map[future] = testcase_index

            for future in as_completed(future_map):
                testcase_index = future_map[future]
                case_results_by_index[testcase_index] = future.result()

        return [
            case_results_by_index[int(item["testcase_index"])]
            for item in items
        ]

    def has_runtime_target_hit(case_results: list[dict]) -> bool:
        for case_result in case_results:
            message = str(case_result.get("message", ""))
            if case_result.get("status") == "pass" and int(case_result.get("time", 0)) > TARGET_RUNTIME_MS:
                return True
            if case_result.get("status") == "fail" and "runtime exceeded" in message:
                return True
        return False

    def has_non_runtime_failure(case_results: list[dict]) -> bool:
        for case_result in case_results:
            message = str(case_result.get("message", ""))
            if case_result.get("status") == "fail" and "runtime exceeded" not in message:
                return True
        return False

    def choose_next_global_sf_n(current_global_sf_n: int, case_results: list[dict]) -> int:
        if not case_results:
            return current_global_sf_n * SF_MULTIPLIER
        average_time_ms = sum(int(case_result.get("time", 0)) for case_result in case_results) / len(case_results)
        multiplier = SF_MULTIPLIER if average_time_ms < SF_FAST_THRESHOLD_MS else SF_SLOW_MULTIPLIER
        next_global_sf_n = current_global_sf_n * multiplier
        debug_print(
            f"[SF_SCALE_DECISION] pid={pid} global_sf_n={current_global_sf_n} "
            f"avg_time_ms={int(average_time_ms)} multiplier={multiplier} next_global_sf_n={next_global_sf_n}"
        )
        return next_global_sf_n

    def finalize_locked_scale_results(
        *,
        global_sf_n: int,
        case_results: list[dict],
    ) -> list[dict]:
        reference_indices = [
            int(case_result["testcase_index"])
            for case_result in case_results
            if case_result.get("status") == "pass"
            and int(case_result.get("time", 0)) > TARGET_RUNTIME_MS
        ]
        finalized: list[dict] = []
        for case_result in case_results:
            if case_result.get("status") == "pass" and int(case_result.get("time", 0)) <= TARGET_RUNTIME_MS:
                finalized.append(
                    build_case_result(
                        testcase_index=int(case_result["testcase_index"]),
                        status="fail",
                        time_ms=int(case_result.get("time", 0)),
                        message=build_too_small_message(
                            global_sf_n=global_sf_n,
                            testcase_index=int(case_result["testcase_index"]),
                            elapsed_ms=int(case_result.get("time", 0)),
                            reference_indices=reference_indices,
                        ),
                    )
                )
                continue
            finalized.append(case_result)
        return finalized

    def log_sf_round_done(*, global_sf_n: int, elapsed_ms: int, summary: dict) -> None:
        debug_print(
            f"[SF_ROUND_DONE] pid={pid} global_sf_n={global_sf_n} "
            f"elapsed_ms={elapsed_ms} pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
        )

    def log_check_testcases_done(*, global_sf_n: int, summary: dict) -> None:
        debug_print(
            f"[CHECK_TESTCASES_DONE] pid={pid} global_sf_n={global_sf_n} "
            f"pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
        )

    testcase_failed = validate_testcase_shape(testcase)
    if testcase_failed:
        debug_print(f"[CHECK_TESTCASES_INVALID] pid={pid} failed={','.join(testcase_failed)}")
        return build_global_failure("failed testcase checks: " + ", ".join(testcase_failed))

    if bin_path is None:
        debug_print(f"[CHECK_TESTCASES_COMPILE] pid={pid} compile_required=yes")
        try:
            returncode, bin_path, message = compile_program(
                pid=pid,
                code=code,
                program=program,
                tmp_dir=tmp_dir,
                compiler=compiler,
                cpp_std=cpp_std,
                compile_timeout=compile_timeout,
                suffix="testcase",
            )
        except subprocess.TimeoutExpired:
            return build_global_failure(f"compile timeout after {compile_timeout}s")
        except Exception as exc:
            return build_global_failure(str(exc))

        if returncode != 0:
            return build_global_failure(message or "compile failed")
    else:
        debug_print(f"[CHECK_TESTCASES_COMPILE] pid={pid} compile_required=no")

    if bin_path is not None and not bin_path.exists():
        debug_print(f"[CHECK_TESTCASES_MISSING_BIN] pid={pid}")
        return build_global_failure(f"missing compiled binary: {bin_path}")

    sorted_cases = sorted(testcase, key=lambda item: int(item["testcase_index"]))
    if not sorted_cases:
        return build_global_failure("empty testcase")

    global_sf_n = SF_START

    while True:
        round_start = time.perf_counter()
        debug_print(
            f"[SF_ROUND_START] pid={pid} global_sf_n={global_sf_n} "
            f"cases={len(sorted_cases)} target_ms={TARGET_RUNTIME_MS}"
        )
        case_results = run_suite_at_scale(
            global_sf_n=global_sf_n,
            items=sorted_cases,
        )

        if has_runtime_target_hit(case_results):
            finalized_results = finalize_locked_scale_results(
                global_sf_n=global_sf_n,
                case_results=case_results,
            )
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=finalized_results,
            )
            elapsed_ms = int((time.perf_counter() - round_start) * 1000)
            log_sf_round_done(global_sf_n=global_sf_n, elapsed_ms=elapsed_ms, summary=summary)
            log_check_testcases_done(global_sf_n=global_sf_n, summary=summary)
            return summary

        if has_non_runtime_failure(case_results):
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=case_results,
            )
            elapsed_ms = int((time.perf_counter() - round_start) * 1000)
            log_sf_round_done(global_sf_n=global_sf_n, elapsed_ms=elapsed_ms, summary=summary)
            log_check_testcases_done(global_sf_n=global_sf_n, summary=summary)
            return summary

        if global_sf_n >= MAX_GLOBAL_SF_N:
            finalized_results = [
                build_case_result(
                    testcase_index=int(case_result["testcase_index"]),
                    status="fail",
                    time_ms=int(case_result.get("time", 0)),
                    message=build_too_small_message(
                        global_sf_n=global_sf_n,
                        testcase_index=int(case_result["testcase_index"]),
                        elapsed_ms=int(case_result.get("time", 0)),
                        reference_indices=[],
                    )
                    if case_result.get("status") == "pass"
                    else build_scale_not_reached_message(global_sf_n),
                )
                for case_result in case_results
            ]
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=finalized_results,
            )
            elapsed_ms = int((time.perf_counter() - round_start) * 1000)
            log_sf_round_done(global_sf_n=global_sf_n, elapsed_ms=elapsed_ms, summary=summary)
            log_check_testcases_done(global_sf_n=global_sf_n, summary=summary)
            return summary
        elapsed_ms = int((time.perf_counter() - round_start) * 1000)
        interim_summary = build_summary(
            global_sf_n=global_sf_n,
            case_results=case_results,
        )
        log_sf_round_done(global_sf_n=global_sf_n, elapsed_ms=elapsed_ms, summary=interim_summary)
        global_sf_n = choose_next_global_sf_n(global_sf_n, case_results)
        if global_sf_n > MAX_GLOBAL_SF_N:
            global_sf_n = MAX_GLOBAL_SF_N
