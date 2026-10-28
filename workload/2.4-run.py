import argparse
from contextlib import contextmanager
import importlib.util
import json
import itertools
import random
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from tqdm import tqdm


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from _log import bind_pid_log_path, clear_pid_log_path, debug_print, set_log_enabled

def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IO_API = load_script_module("workload_io_api", CURRENT_DIR / "_io.py")
SESSION_API = load_script_module("workload_session_api", CURRENT_DIR / "_session.py")
GENERATE_API = load_script_module("workload_harness_api", CURRENT_DIR / "_harness.py")
DEBUG_API = load_script_module("workload_measure_api", CURRENT_DIR / "_measure.py")
PARSER_API = load_script_module("workload_parser_api", CURRENT_DIR / "_parser.py")

append_jsonl = IO_API.append_jsonl
iter_jsonl = IO_API.iter_jsonl
load_pid_set = IO_API.load_pid_set
write_session = SESSION_API.write_session
validate_testcase_shape = PARSER_API.validate_testcase_shape


ROOT_DIR = CURRENT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
TMP_DIR = ROOT_DIR / "tmp"
DEFAULT_INPUT_PATH = DATA_DIR / "seed.jsonl"
DEFAULT_OUTPUT_PATH = DATA_DIR / "testcase.jsonl"
DEFAULT_RESULT_PATH = DATA_DIR / "output.jsonl"
DEFAULT_LOG_DIR = TMP_DIR / "workload_logs"
DEFAULT_DEBUG_TMP_DIR = TMP_DIR / "workload_debug"
DEFAULT_SESSION_DIR = TMP_DIR / "workload_sessions"
DEFAULT_CONFIG_PATH = ROOT_DIR / "llm_config.env"
MAX_WORKERS = 32
RANDOM_SHUFFLE_BUFFER_SIZE = 1024

LLM_PRIORITY = {
    "repair_testcase": 0,
    "repair_program": 1,
    "generate_testcase": 2,
    "generate_program": 3,
}

class LLMPriorityLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self.condition = threading.Condition()
        self.running = 0
        self.waiters: list[dict] = []
        self.next_seq = 0

    @contextmanager
    def slot(self, *, priority_name: str, pid: str, attempt: int):
        if priority_name not in LLM_PRIORITY:
            raise ValueError(f"unknown llm priority: {priority_name}")

        waiter = {
            "priority": LLM_PRIORITY[priority_name],
            "priority_name": priority_name,
            "pid": pid,
            "attempt": attempt,
            "seq": -1,
        }
        with self.condition:
            waiter["seq"] = self.next_seq
            self.next_seq += 1
            self.waiters.append(waiter)
            while True:
                head = min(self.waiters, key=lambda item: (item["priority"], item["seq"]))
                if head is waiter and self.running < self.limit:
                    self.waiters.remove(waiter)
                    self.running += 1
                    break
                self.condition.wait()
        try:
            yield
        finally:
            with self.condition:
                self.running -= 1
                self.condition.notify_all()


def build_testcase_repair_payload(*, testcase: list[dict], result_row: dict) -> tuple[list[dict], str]:
    passed_indices: list[int] = []
    failed_indices: list[int] = []
    compact_results: list[dict] = []
    for case in result_row.get("results", []):
        try:
            testcase_index = int(case.get("testcase_index", 0))
        except Exception:
            testcase_index = 0
        if testcase_index <= 0:
            continue
        if case.get("status") == "pass":
            passed_indices.append(testcase_index)
        elif case.get("status") == "fail":
            failed_indices.append(testcase_index)
        compact_results.append(
            {
                "testcase_index": case.get("testcase_index"),
                "status": case.get("status"),
                "time": case.get("time"),
                "message": case.get("message", ""),
            }
        )

    repair_context = {
        "pid": result_row.get("pid"),
        "global_sf_n": result_row.get("global_sf_n", 0),
        "pass_count": result_row.get("pass_count", 0),
        "fail_count": result_row.get("fail_count", 0),
        "passed_testcase_indices": passed_indices,
        "failed_testcase_indices": failed_indices,
        "results": compact_results,
    }
    return list(testcase), json.dumps(repair_context, ensure_ascii=False, indent=2)


def is_too_small_message(message: str) -> bool:
    text = str(message).strip()
    return (
        " is too small at Global_SF_N=" in text
        or text.startswith("all testcase runtimes stayed at or below ")
    )


def only_too_small_failures(result_row: dict) -> bool:
    results = result_row.get("results", [])
    if not isinstance(results, list) or not results:
        return False
    saw_failure = False
    for case in results:
        if str(case.get("status", "")).strip() != "fail":
            continue
        saw_failure = True
        if not is_too_small_message(str(case.get("message", ""))):
            return False
    return saw_failure


def accept_too_small_result_row(result_row: dict) -> dict:
    normalized_results: list[dict] = []
    for case in result_row.get("results", []):
        item = dict(case)
        if str(item.get("status", "")).strip() == "fail" and is_too_small_message(str(item.get("message", ""))):
            item["status"] = "pass"
            item["message"] = ""
        normalized_results.append(item)
    return {
        **result_row,
        "pass_count": len(normalized_results),
        "fail_count": 0,
        "results": normalized_results,
    }


def build_success_result_record(
    *,
    pid: str,
    result_row: dict,
    program_rounds: int,
    testcase_rounds: int,
    message: str = "",
    error_type: str = "",
) -> dict:
    return {
        "pid": pid,
        "status": "success",
        "stage": "testcase",
        "error_type": error_type,
        "message": message,
        "program_rounds": program_rounds,
        "testcase_rounds": testcase_rounds,
        "global_sf_n": result_row.get("global_sf_n"),
        "pass_count": result_row.get("pass_count"),
        "fail_count": result_row.get("fail_count"),
        "results": list(result_row.get("results", [])),
    }


def build_failure_result_record(
    *,
    pid: str,
    stage: str,
    error_type: str,
    message: str,
    program_rounds: int,
    testcase_rounds: int,
    result_row: dict | None,
) -> dict:
    if result_row is None:
        return {
            "pid": pid,
            "status": "fail",
            "stage": stage,
            "error_type": error_type,
            "message": message,
            "program_rounds": program_rounds,
            "testcase_rounds": testcase_rounds,
            "global_sf_n": None,
            "pass_count": None,
            "fail_count": None,
            "results": [],
        }

    return {
        "pid": pid,
        "status": "fail",
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "program_rounds": program_rounds,
        "testcase_rounds": testcase_rounds,
        "global_sf_n": result_row.get("global_sf_n"),
        "pass_count": result_row.get("pass_count"),
        "fail_count": result_row.get("fail_count"),
        "results": list(result_row.get("results", [])),
    }


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
    parser.add_argument("--program-max-rounds", type=int, default=2)
    parser.add_argument("--testcase-max-rounds", type=int, default=3)
    parser.add_argument("--llm-j", type=int, default=1)
    parser.add_argument("--run-j", type=int, default=1)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--random", action="store_true")
    parser.add_argument("-n", type=int, default=None)
    return parser.parse_args()


def iter_pending_rows(
    input_path: Path,
    *,
    completed_pids: set[str],
    randomize: bool,
):
    def iter_filtered():
        for row in iter_jsonl(input_path):
            pid = str(row.get("pid", "")).strip()
            if pid and pid not in completed_pids:
                yield row

    if not randomize:
        yield from iter_filtered()
        return

    buffer: list[dict] = []
    for row in iter_filtered():
        buffer.append(row)
        if len(buffer) >= RANDOM_SHUFFLE_BUFFER_SIZE:
            random.shuffle(buffer)
            while buffer:
                yield buffer.pop()
    if buffer:
        random.shuffle(buffer)
        while buffer:
            yield buffer.pop()


def count_pending_rows(
    input_path: Path,
    *,
    completed_pids: set[str],
    limit: int | None,
    randomize: bool,
) -> int:
    count = 0
    for _ in iter_pending_rows(
        input_path,
        completed_pids=completed_pids,
        randomize=randomize,
    ):
        count += 1
        if limit is not None and count >= max(0, limit):
            break
    return count


def process_one_pid(
    *,
    row: dict,
    args: argparse.Namespace,
) -> dict:
    pid = str(row.get("pid", "")).strip()
    code = str(row.get("code", ""))
    log_dir = Path(args.log_dir)
    if pid:
        bind_pid_log_path(pid, log_dir / f"{pid}.log")
    debug_print(f"[PID_START] pid={pid or '<empty>'}")
    if not pid or not code.strip():
        return {
            "pid": pid or "<empty>",
            "success": False,
            "error_type": "input",
            "message": "missing pid or code",
        }

    debug_tmp_dir = Path(args.debug_tmp_dir)
    session_dir = Path(args.session_dir)
    config_path = Path(args.config)

    program_messages: list[dict] = []
    testcase_messages: list[dict] = []
    program = ""
    program_bin_path: Path | None = None
    testcase: list[dict] = []
    last_error_type = ""
    last_message = ""
    program_rounds = 0
    testcase_rounds = 0
    last_testcase_result_row: dict | None = None

    write_session(session_dir=session_dir, pid=pid, session_name="program", messages=program_messages)

    for attempt in range(1, args.program_max_rounds + 1):
        program_rounds = attempt
        try:
            if not program:
                debug_print(f"[PROGRAM_GENERATE] pid={pid} attempt={attempt} start")
                with args.llm_limiter.slot(
                    priority_name="generate_program",
                    pid=pid,
                    attempt=attempt,
                ):
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
                with args.llm_limiter.slot(
                    priority_name="repair_program",
                    pid=pid,
                    attempt=attempt,
                ):
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
            debug_print(f"[PROGRAM_EXCEPTION_DETAIL] pid={pid} attempt={attempt} message={last_message}")
    else:
        return {
            "pid": pid,
            "success": False,
            "result_row": build_failure_result_record(
                pid=pid,
                stage="program",
                error_type=last_error_type or "program",
                message=last_message or "program generation failed",
                program_rounds=program_rounds,
                testcase_rounds=testcase_rounds,
                result_row=None,
            ),
        }

    write_session(session_dir=session_dir, pid=pid, session_name="testcase", messages=testcase_messages)

    for attempt in range(1, args.testcase_max_rounds + 1):
        testcase_rounds = attempt
        try:
            had_existing_testcase = bool(testcase)
            if not testcase:
                debug_print(f"[TESTCASE_GENERATE] pid={pid} attempt={attempt} start")
                with args.llm_limiter.slot(
                    priority_name="generate_testcase",
                    pid=pid,
                    attempt=attempt,
                ):
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
                with args.llm_limiter.slot(
                    priority_name="repair_testcase",
                    pid=pid,
                    attempt=attempt,
                ):
                    result = GENERATE_API.repair_testcase(
                        config_path=config_path,
                        pid=pid,
                        code=code,
                        program=program,
                        testcase=testcase,
                        error=last_message,
                        messages=testcase_messages,
                        log_dir=log_dir,
                        attempt=attempt,
                    )
            testcase_messages = result["messages"]
            repaired_testcase = result["testcase"]
            repair_failed = validate_testcase_shape(repaired_testcase)
            if repair_failed:
                raise ValueError(
                    "failed testcase repair checks: " + ", ".join(repair_failed)
                )
            testcase = repaired_testcase
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
            last_testcase_result_row = result_row
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
                    "result_row": build_success_result_record(
                        pid=pid,
                        result_row=result_row,
                        program_rounds=program_rounds,
                        testcase_rounds=testcase_rounds,
                    ),
                }
            if (
                attempt == args.testcase_max_rounds
                and had_existing_testcase
                and only_too_small_failures(result_row)
            ):
                accepted_result_row = accept_too_small_result_row(result_row)
                debug_print(
                    f"[TESTCASE_CHECK_ACCEPT_TOO_SMALL] pid={pid} attempt={attempt}"
                )
                return {
                    "pid": pid,
                    "success": True,
                    "testcase_row": {
                        "pid": pid,
                        "program": program,
                        "testcase": testcase,
                    },
                    "result_row": build_success_result_record(
                        pid=pid,
                        result_row=accepted_result_row,
                        program_rounds=program_rounds,
                        testcase_rounds=testcase_rounds,
                        message="accepted only-too-small failures on final testcase round",
                        error_type="accepted_too_small",
                    ),
                }
            last_error_type = "debug"
            _, last_message = build_testcase_repair_payload(
                testcase=testcase,
                result_row=result_row,
            )
            debug_print(
                f"[TESTCASE_CHECK_FAIL] pid={pid} attempt={attempt} fail_count={fail_count}"
            )
        except Exception as exc:
            last_error_type = "testcase"
            last_message = str(exc)
            debug_print(f"[TESTCASE_EXCEPTION] pid={pid} attempt={attempt}")
            debug_print(f"[TESTCASE_EXCEPTION_DETAIL] pid={pid} attempt={attempt} message={last_message}")
    return {
        "pid": pid,
        "success": False,
        "result_row": build_failure_result_record(
            pid=pid,
            stage="testcase",
            error_type=last_error_type or "testcase",
            message=last_message or "testcase generation failed",
            program_rounds=program_rounds,
            testcase_rounds=testcase_rounds,
            result_row=last_testcase_result_row,
        ),
    }


def main() -> int:
    args = parse_args()
    set_log_enabled(bool(args.log))
    args.llm_j = max(1, int(args.llm_j))
    args.run_j = max(1, int(args.run_j))
    args.llm_limiter = LLMPriorityLimiter(args.llm_j)
    args.run_semaphore = threading.BoundedSemaphore(args.run_j)

    log_dir = Path(args.log_dir)
    Path(args.debug_tmp_dir).mkdir(parents=True, exist_ok=True)
    if args.log:
        log_dir.mkdir(parents=True, exist_ok=True)
    Path(args.session_dir).mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    completed_pids = load_pid_set(Path(args.result_output)) | load_pid_set(Path(args.output))
    pending_total = count_pending_rows(
        input_path,
        completed_pids=completed_pids,
        limit=args.n,
        randomize=args.random,
    )
    if pending_total <= 0:
        debug_print("[RUN_NO_PENDING]")
        return 0
    debug_print(f"[RUN_PENDING] pending_total={pending_total}")

    pending_iter = iter_pending_rows(
        input_path,
        completed_pids=completed_pids,
        randomize=args.random,
    )
    if args.n is not None:
        pending_iter = itertools.islice(pending_iter, max(0, args.n))

    args.worker_j = max(1, min(MAX_WORKERS, pending_total))

    with ThreadPoolExecutor(max_workers=args.worker_j) as executor:
        future_set: set = set()

        def submit_next() -> bool:
            try:
                row = next(pending_iter)
            except StopIteration:
                return False
            future_set.add(executor.submit(process_one_pid, row=row, args=args))
            return True

        for _ in range(args.worker_j):
            if not submit_next():
                break

        completed = 0
        pass_count = 0
        fail_count = 0
        with tqdm(total=pending_total, desc="pid", unit="pid") as progress:
            progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
            while future_set:
                done, _ = wait(future_set, return_when=FIRST_COMPLETED)
                for future in done:
                    future_set.remove(future)
                    result = future.result()
                    if result.get("success"):
                        append_jsonl(Path(args.output), result["testcase_row"])
                        append_jsonl(Path(args.result_output), result["result_row"])
                        pass_count += 1
                        debug_print(f"[PID_DONE] pid={result.get('pid')} status=success")
                    else:
                        append_jsonl(Path(args.result_output), result["result_row"])
                        fail_count += 1
                        debug_print(
                            f"[PID_DONE] pid={result.get('pid')} status=fail "
                            f"error_type={result['result_row'].get('error_type', '')} "
                            f"message={result['result_row'].get('message', '')}"
                        )
                    clear_pid_log_path(str(result.get("pid", "")))
                    completed += 1
                    progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
                    progress.update(1)
                    submit_next()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
