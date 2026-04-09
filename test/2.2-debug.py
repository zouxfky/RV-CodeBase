import shutil
import subprocess
import sys
import time
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from _parser import testcase_to_stdin, validate_testcase_shape


def debug_print(message: str) -> None:
    print(message, flush=True)


SF_START = 10
SF_MULTIPLIER = 10
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
        capture_output=True,
        text=True,
        timeout=compile_timeout,
        check=False,
    )
    message = (completed.stderr or completed.stdout or "").strip()
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
    debug_print(f"[CHECK_PROGRAM_START] pid={pid}")
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
    debug_print(f"[CHECK_TESTCASES_START] pid={pid} total={len(testcase) if isinstance(testcase, list) else 'invalid'}")

    def build_case_result(
        *,
        testcase_index: int,
        status: str,
        time_ms: int,
        message: str,
        stdout: str,
    ) -> dict:
        return {
            "testcase_index": testcase_index,
            "status": status,
            "time": time_ms,
            "message": message,
            "stdout": stdout,
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

    def build_scale_not_reached_message(global_sf_n: int, elapsed_ms: int) -> str:
        return (
            f"runtime is still {elapsed_ms}ms at Global_SF_N={global_sf_n}, which did not exceed "
            f"{TARGET_RUNTIME_MS}ms. Please increase the non-Global_SF_N parameters so the program "
            f"takes longer under scaling."
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
                    stdout="",
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
            debug_print(
                f"[RUN_TESTCASE_START] pid={pid} global_sf_n={global_sf_n} testcase_index={index}"
            )
            stdin_text = testcase_to_stdin(testcase_item, global_sf_n=str(global_sf_n))
            run_completed = subprocess.run(
                [str(bin_path)],
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=run_timeout,
                check=False,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            stdout_text = (run_completed.stdout or "").rstrip("\r\n")
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
                    stdout=stdout_text,
                )
            debug_print(
                f"[RUN_TESTCASE_FAIL] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
            )
            return build_case_result(
                testcase_index=index,
                status="fail",
                time_ms=elapsed_ms,
                message=stderr_text or stdout_text or f"binary exited with code {run_completed.returncode}",
                stdout=stdout_text,
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
                stdout="",
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            debug_print(
                f"[RUN_TESTCASE_EXCEPTION] pid={pid} global_sf_n={global_sf_n} testcase_index={index} time_ms={elapsed_ms}"
            )
            debug_print(str(exc))
            return build_case_result(
                testcase_index=index,
                status="fail",
                time_ms=elapsed_ms,
                message=str(exc),
                stdout="",
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

    calibration_case = sorted_cases[0]
    global_sf_n = SF_START
    selected_calibration_result: dict | None = None

    debug_print(
        f"[SF_SEARCH_START] pid={pid} testcase_index={int(calibration_case['testcase_index'])} "
        f"start_sf={SF_START} target_ms={TARGET_RUNTIME_MS}"
    )
    while True:
        probe_result = run_one_case(
            testcase_item=calibration_case,
            global_sf_n=global_sf_n,
        )
        if probe_result["status"] == "fail":
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=[probe_result],
            )
            debug_print(
                f"[CHECK_TESTCASES_DONE] pid={pid} pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
            )
            return summary
        if int(probe_result["time"]) > TARGET_RUNTIME_MS:
            selected_calibration_result = probe_result
            debug_print(
                f"[SF_LOCKED] pid={pid} global_sf_n={global_sf_n} time_ms={int(probe_result['time'])}"
            )
            break
        if global_sf_n >= MAX_GLOBAL_SF_N:
            probe_result = build_case_result(
                testcase_index=int(calibration_case["testcase_index"]),
                status="fail",
                time_ms=int(probe_result["time"]),
                message=build_scale_not_reached_message(global_sf_n, int(probe_result["time"])),
                stdout=str(probe_result.get("stdout", "")),
            )
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=[probe_result],
            )
            debug_print(
                f"[CHECK_TESTCASES_DONE] pid={pid} pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
            )
            return summary
        global_sf_n *= SF_MULTIPLIER
        debug_print(f"[SF_SEARCH_NEXT] pid={pid} next_global_sf_n={global_sf_n}")

    case_results: list[dict] = []
    if selected_calibration_result is not None:
        case_results.append(selected_calibration_result)

    for item in sorted_cases[1:]:
        case_result = run_one_case(
            testcase_item=item,
            global_sf_n=global_sf_n,
        )
        case_results.append(case_result)
        if case_result["status"] == "fail" and "runtime exceeded" in str(case_result["message"]):
            summary = build_summary(
                global_sf_n=global_sf_n,
                case_results=case_results,
            )
            debug_print(
                f"[CHECK_TESTCASES_DONE] pid={pid} pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
            )
            return summary

    summary = build_summary(
        global_sf_n=global_sf_n,
        case_results=case_results,
    )
    debug_print(
        f"[CHECK_TESTCASES_DONE] pid={pid} pass_count={summary['pass_count']} fail_count={summary['fail_count']}"
    )
    return summary
