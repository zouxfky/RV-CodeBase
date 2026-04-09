import argparse
import importlib.util
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IO_API = load_script_module("test_io_api", CURRENT_DIR / "_io.py")
SESSION_API = load_script_module("test_session_api", CURRENT_DIR / "_session.py")
GENERATE_API = load_script_module("test_generate_api", CURRENT_DIR / "2.1-generate.py")
DEBUG_API = load_script_module("test_debug_api", CURRENT_DIR / "2.2-debug.py")
PARSER_API = load_script_module("test_parser_api", CURRENT_DIR / "_parser.py")

append_jsonl = IO_API.append_jsonl
load_pid_set = IO_API.load_pid_set
read_jsonl = IO_API.read_jsonl
write_session = SESSION_API.write_session
merge_testcase_updates = PARSER_API.merge_testcase_updates
validate_partial_testcase_shape = PARSER_API.validate_partial_testcase_shape


ROOT_DIR = CURRENT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
TMP_DIR = ROOT_DIR / "tmp"
DEFAULT_INPUT_PATH = DATA_DIR / "seed.jsonl"
DEFAULT_OUTPUT_PATH = DATA_DIR / "testcase.jsonl"
DEFAULT_RESULT_PATH = DATA_DIR / "output.jsonl"
DEFAULT_LOG_DIR = TMP_DIR / "test_logs"
DEFAULT_DEBUG_TMP_DIR = TMP_DIR / "test_debug"
DEFAULT_SESSION_DIR = TMP_DIR / "test_sessions"
DEFAULT_CONFIG_PATH = ROOT_DIR / "llm_config.env"


def debug_print(message: str) -> None:
    print(message, flush=True)


def log_result(result: dict) -> None:
    pid = str(result.get("pid", "<unknown>"))
    if result.get("success"):
        debug_print(f"[PASS] pid={pid}")
        return

    error_type = str(result.get("error_type", "")).strip() or "unknown"
    message = str(result.get("message", "")).rstrip()
    debug_print(f"[FAIL] pid={pid} error_type={error_type}")
    if message:
        for line in message.splitlines():
            debug_print(line)


def build_testcase_repair_payload(*, testcase: list[dict], result_row: dict) -> tuple[list[dict], str, set[int]]:
    all_indices = {int(item["testcase_index"]) for item in testcase}
    failed_indices: set[int] = set()
    filtered_results: list[dict] = []

    for case in result_row.get("results", []):
        if case.get("status") != "fail":
            continue
        failed_case = dict(case)
        try:
            testcase_index = int(failed_case.get("testcase_index", 0))
        except Exception:
            testcase_index = 0
        if testcase_index > 0:
            failed_indices.add(testcase_index)
        filtered_results.append(failed_case)

    if not failed_indices:
        failed_indices = set(all_indices)

    failed_testcases = [
        item for item in testcase if int(item["testcase_index"]) in failed_indices
    ]
    filtered_error = {
        "pid": result_row.get("pid"),
        "global_sf_n": result_row.get("global_sf_n", 0),
        "fail_count": len(filtered_results),
        "results": filtered_results,
    }
    return failed_testcases, json.dumps(filtered_error, ensure_ascii=False, indent=2), failed_indices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--result-output", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--debug-tmp-dir", default=str(DEFAULT_DEBUG_TMP_DIR))
    parser.add_argument("--session-dir", default=str(DEFAULT_SESSION_DIR))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--compiler", default=DEBUG_API.detect_default_compiler())
    parser.add_argument("--std", default="c++17")
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=240)
    parser.add_argument("--program-max-rounds", type=int, default=5)
    parser.add_argument("--testcase-max-rounds", type=int, default=5)
    parser.add_argument("--llm-j", type=int, default=1)
    parser.add_argument("--run-j", type=int, default=1)
    parser.add_argument("-n", type=int, default=None)
    return parser.parse_args()


def process_one_pid(
    *,
    row: dict,
    args: argparse.Namespace,
) -> dict:
    pid = str(row.get("pid", "")).strip()
    code = str(row.get("code", ""))
    debug_print(f"[PID_START] pid={pid or '<empty>'}")
    if not pid or not code.strip():
        return {
            "pid": pid or "<empty>",
            "success": False,
            "error_type": "input",
            "message": "missing pid or code",
        }

    log_dir = Path(args.log_dir)
    debug_tmp_dir = Path(args.debug_tmp_dir)
    session_dir = Path(args.session_dir)
    config_path = Path(args.config)

    program_messages: list[dict] = []
    testcase_messages: list[dict] = []
    program = ""
    program_bin_path: Path | None = None
    testcase: list[dict] = []
    testcase_repair_subset: list[dict] = []
    testcase_repair_indices: set[int] = set()
    last_error_type = ""
    last_message = ""

    write_session(session_dir=session_dir, pid=pid, session_name="program", messages=program_messages)
    debug_print(f"[PROGRAM_SESSION] pid={pid} initialized")

    for attempt in range(1, args.program_max_rounds + 1):
        try:
            if not program:
                debug_print(f"[PROGRAM_GENERATE] pid={pid} attempt={attempt} start")
                with args.llm_semaphore:
                    result = GENERATE_API.generate_program(
                        config_path=config_path,
                        pid=pid,
                        code=code,
                        messages=program_messages,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
            else:
                debug_print(f"[PROGRAM_REPAIR] pid={pid} attempt={attempt} start")
                with args.llm_semaphore:
                    result = GENERATE_API.repair_program(
                        config_path=config_path,
                        pid=pid,
                        code=code,
                        program=program,
                        error=last_message,
                        messages=program_messages,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
            program_messages = result["messages"]
            program = result["program"]
            write_session(session_dir=session_dir, pid=pid, session_name="program", messages=program_messages)
            debug_print(f"[PROGRAM_READY] pid={pid} attempt={attempt} code_len={len(program)}")
            with args.run_semaphore:
                debug_print(f"[PROGRAM_CHECK] pid={pid} attempt={attempt} start")
                light = DEBUG_API.check_program(
                    pid=pid,
                    code=code,
                    program=program,
                    tmp_dir=debug_tmp_dir,
                    compiler=args.compiler,
                    cpp_std=args.std,
                    compile_timeout=args.compile_timeout,
                )
            if light["status"] == "pass":
                debug_print(f"[PROGRAM_CHECK_PASS] pid={pid} attempt={attempt}")
                last_error_type = ""
                last_message = ""
                raw_bin_path = str(light.get("bin_path", "")).strip()
                if not raw_bin_path:
                    raise ValueError("missing bin_path from program verification")
                program_bin_path = Path(raw_bin_path)
                program_messages = []
                break
            last_error_type = light["error_type"]
            last_message = light["message"]
            debug_print(f"[PROGRAM_CHECK_FAIL] pid={pid} attempt={attempt} error_type={last_error_type}")
        except Exception as exc:
            last_error_type = "program"
            last_message = str(exc)
            debug_print(f"[PROGRAM_EXCEPTION] pid={pid} attempt={attempt}")
            debug_print(last_message)
    else:
        return {
            "pid": pid,
            "success": False,
            "error_type": last_error_type or "program",
            "message": last_message or "program generation failed",
        }

    write_session(session_dir=session_dir, pid=pid, session_name="testcase", messages=testcase_messages)
    debug_print(f"[TESTCASE_SESSION] pid={pid} initialized")

    for attempt in range(1, args.testcase_max_rounds + 1):
        try:
            if not testcase:
                debug_print(f"[TESTCASE_GENERATE] pid={pid} attempt={attempt} start")
                with args.llm_semaphore:
                    result = GENERATE_API.generate_testcase(
                        config_path=config_path,
                        pid=pid,
                        code=code,
                        program=program,
                        messages=testcase_messages,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
            else:
                debug_print(f"[TESTCASE_REPAIR] pid={pid} attempt={attempt} start")
                debug_print(
                    f"[TESTCASE_REPAIR_INPUT] pid={pid} attempt={attempt} "
                    f"failed_cases={len(testcase_repair_subset)} indices={sorted(testcase_repair_indices)}"
                )
                with args.llm_semaphore:
                    result = GENERATE_API.repair_testcase(
                        config_path=config_path,
                        pid=pid,
                        code=code,
                        program=program,
                        testcase=testcase_repair_subset,
                        error=last_message,
                        messages=testcase_messages,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
            testcase_messages = result["messages"]
            if testcase:
                repaired_subset = result["testcase"]
                repair_failed = validate_partial_testcase_shape(
                    repaired_subset,
                    allowed_indices=testcase_repair_indices or None,
                )
                if repair_failed:
                    raise ValueError(
                        "failed testcase repair checks: " + ", ".join(repair_failed)
                    )
                testcase = merge_testcase_updates(testcase, repaired_subset)
            else:
                testcase = result["testcase"]
            write_session(session_dir=session_dir, pid=pid, session_name="testcase", messages=testcase_messages)
            debug_print(f"[TESTCASE_READY] pid={pid} attempt={attempt} cases={len(testcase)}")
            with args.run_semaphore:
                debug_print(f"[TESTCASE_CHECK] pid={pid} attempt={attempt} start")
                result_row = DEBUG_API.check_testcases(
                    pid=pid,
                    code=code,
                    program=program,
                    testcase=testcase,
                    tmp_dir=debug_tmp_dir,
                    compiler=args.compiler,
                    cpp_std=args.std,
                    compile_timeout=args.compile_timeout,
                    run_timeout=args.run_timeout,
                    bin_path=program_bin_path,
                )
            fail_count = int(result_row.get("fail_count", 0))
            if fail_count == 0:
                debug_print(f"[TESTCASE_CHECK_PASS] pid={pid} attempt={attempt}")
                return {
                    "pid": pid,
                    "success": True,
                    "testcase_row": {
                        "pid": pid,
                        "program": program,
                        "testcase": testcase,
                    },
                    "result_row": result_row,
                }
            last_error_type = "debug"
            testcase_repair_subset, last_message, testcase_repair_indices = build_testcase_repair_payload(
                testcase=testcase,
                result_row=result_row,
            )
            debug_print(
                f"[TESTCASE_CHECK_FAIL] pid={pid} attempt={attempt} fail_count={fail_count}"
            )
            debug_print(
                f"[TESTCASE_REPAIR_PREP] pid={pid} failed_cases={len(testcase_repair_subset)} "
                f"indices={sorted(testcase_repair_indices)}"
            )
        except Exception as exc:
            last_error_type = "testcase"
            last_message = str(exc)
            debug_print(f"[TESTCASE_EXCEPTION] pid={pid} attempt={attempt}")
            debug_print(last_message)
    return {
        "pid": pid,
        "success": False,
        "error_type": last_error_type or "testcase",
        "message": last_message or "testcase generation failed",
    }


def main() -> int:
    args = parse_args()
    args.llm_j = max(1, int(args.llm_j))
    args.run_j = max(1, int(args.run_j))
    args.llm_semaphore = threading.BoundedSemaphore(args.llm_j)
    args.run_semaphore = threading.BoundedSemaphore(args.run_j)
    args.worker_j = max(1, args.llm_j + args.run_j)
    debug_print(
        f"[CONFIG] input={args.input} output={args.output} result_output={args.result_output} "
        f"llm_j={args.llm_j} run_j={args.run_j} workers={args.worker_j} "
        f"compile_timeout={args.compile_timeout} run_timeout={args.run_timeout}"
    )

    log_dir = Path(args.log_dir)
    Path(args.debug_tmp_dir).mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(args.session_dir).mkdir(parents=True, exist_ok=True)

    seed_rows = read_jsonl(Path(args.input))
    completed_pids = load_pid_set(Path(args.output))
    pending_rows = [
        row
        for row in seed_rows
        if str(row.get("pid", "")).strip()
        and str(row.get("pid", "")).strip() not in completed_pids
    ]
    if args.n is not None:
        pending_rows = pending_rows[: max(0, args.n)]
    debug_print(f"[PENDING] total={len(pending_rows)}")

    with ThreadPoolExecutor(max_workers=args.worker_j) as executor:
        future_map = {
            executor.submit(process_one_pid, row=row, args=args): row for row in pending_rows
        }
        completed = 0
        for future in as_completed(future_map):
            result = future.result()
            log_result(result)
            if result.get("success"):
                append_jsonl(Path(args.output), result["testcase_row"])
                append_jsonl(Path(args.result_output), result["result_row"])
            completed += 1
            debug_print(f"[PROGRESS] completed={completed}/{len(pending_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
