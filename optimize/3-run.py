import argparse
from collections import Counter
from dataclasses import dataclass, field
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import heapq
import importlib.util
from pathlib import Path
import sys

from tqdm import tqdm


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
OUT_DIR = ROOT_DIR / "out"
TMP_DIR = ROOT_DIR / "tmp"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import _bench
import _records
import _remote
import _session


DEFAULT_SEED_PATH = OUT_DIR / "seed.jsonl"
DEFAULT_VERIFY_PATH = OUT_DIR / "output.jsonl"
DEFAULT_TESTCASE_PATH = OUT_DIR / "testcase.jsonl"
DEFAULT_RESULT_PATH = OUT_DIR / "rv2.jsonl"
DEFAULT_CONFIG_PATH = ROOT_DIR / "llm_config.env"
DEFAULT_TMP_DIR = TMP_DIR / "rv_opt"
DEFAULT_SESSION_DIR = TMP_DIR / "rv_opt_sessions"


def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATE_API = load_script_module("optimize_generate_api", CURRENT_DIR / "3.1-generate.py")
DEBUG_API = load_script_module("optimize_debug_api", CURRENT_DIR / "3.2-debug.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", "--input", dest="seed", default=str(DEFAULT_SEED_PATH))
    parser.add_argument("--verify-output", default=str(DEFAULT_VERIFY_PATH))
    parser.add_argument("--testcase", default=str(DEFAULT_TESTCASE_PATH))
    parser.add_argument("--result-output", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--tmp-dir", default=str(DEFAULT_TMP_DIR))
    parser.add_argument("--session-dir", default=str(DEFAULT_SESSION_DIR))
    parser.add_argument("--remote-host", default="sg2044")
    parser.add_argument("--remote-root", default="/tmp/rv_opt")
    parser.add_argument(
        "--compile-cmd",
        default="g++ -std=c++17 -O3 -march=rv64gcv -mabi=lp64d",
    )
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=240)
    parser.add_argument("--ssh-timeout", type=int, default=900)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--llm-j", type=int, default=1)
    parser.add_argument("--run-j", type=int, default=1)
    parser.add_argument("--random", action="store_true")
    parser.add_argument("-n", type=int, default=None)
    return parser.parse_args()


def select_best_candidate(
    *,
    best_candidate: dict | None,
    candidate_record: dict,
) -> dict | None:
    debug = candidate_record["debug_result"]
    if not _bench.is_successful_speedup(debug):
        return best_candidate
    if best_candidate is None:
        return candidate_record
    if float(debug["speedup_ratio"]) > float(best_candidate["debug_result"]["speedup_ratio"]):
        return candidate_record
    return best_candidate


def truncate_message(message: str, *, max_chars: int = 500) -> str:
    text = str(message).replace("\r", "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def is_failure_row(row: dict) -> bool:
    return str(row.get("status", "")).strip() == "fail"


def print_failure_summary(rows: list[dict]) -> None:
    failures = [row for row in rows if is_failure_row(row)]
    if not failures:
        return

    print("\nFailure summary:", file=sys.stderr)
    counts = Counter(
        (str(row.get("stage", "")), str(row.get("error_type", "")))
        for row in failures
    )
    for (stage, error_type), count in counts.most_common():
        print(f"  {count}x stage={stage or '-'} error_type={error_type or '-'}", file=sys.stderr)

    print("\nFailed rows:", file=sys.stderr)
    for row in failures:
        pid = str(row.get("pid", ""))
        rounds = row.get("rounds", "")
        stage = str(row.get("stage", ""))
        error_type = str(row.get("error_type", ""))
        message = truncate_message(str(row.get("message", "")))
        print(
            f"  {pid} rounds={rounds} stage={stage or '-'} "
            f"error_type={error_type or '-'} message={message}",
            file=sys.stderr,
        )


@dataclass
class OptimizeState:
    pid: str
    context: dict
    max_rounds: int
    messages: list[dict] = field(default_factory=list)
    previous_candidates: list[dict] = field(default_factory=list)
    best_candidate: dict | None = None
    current_code: str = ""
    last_debug: dict | None = None
    next_attempt: int = 1
    rounds_done: int = 0


def llm_attempt(*, state: OptimizeState, args: argparse.Namespace, attempt: int) -> dict:
    if attempt == 1:
        return GENERATE_API.generate_candidate(
            config_path=Path(args.config),
            pid=state.pid,
            context=state.context,
            messages=state.messages,
            attempt=attempt,
        )
    if state.last_debug is not None and str(state.last_debug.get("status", "")) != "pass":
        return GENERATE_API.repair_candidate(
            config_path=Path(args.config),
            pid=state.pid,
            debug_result=state.last_debug,
            messages=state.messages,
            attempt=attempt,
        )
    return GENERATE_API.improve_candidate(
        config_path=Path(args.config),
        pid=state.pid,
        debug_result=state.last_debug or {},
        messages=state.messages,
        attempt=attempt,
    )


def debug_attempt(*, state: OptimizeState, args: argparse.Namespace, attempt: int) -> dict:
    return DEBUG_API.debug_candidate(
        pid=state.pid,
        context=state.context,
        optimized_code=state.current_code,
        attempt=attempt,
        host=args.remote_host,
        remote_root=args.remote_root,
        tmp_dir=Path(args.tmp_dir),
        compile_cmd=args.compile_cmd,
        compile_timeout=args.compile_timeout,
        run_timeout=args.run_timeout,
        ssh_timeout=args.ssh_timeout,
    )


def write_state_session(*, state: OptimizeState, args: argparse.Namespace) -> None:
    _session.write_session(
        session_dir=Path(args.session_dir),
        pid=state.pid,
        messages=state.messages,
        previous_candidates=state.previous_candidates,
    )


def build_final_row(state: OptimizeState) -> dict:
    if state.best_candidate is not None:
        debug = state.best_candidate["debug_result"]
        return _records.build_success_row(
            pid=state.pid,
            rounds=state.rounds_done,
            best_round=int(state.best_candidate["round"]),
            best_speedup_ratio=float(debug["speedup_ratio"]),
            baseline_time_ms=float(debug["baseline_time_ms"]),
            optimized_time_ms=float(debug["optimized_time_ms"]),
            global_sf_n=int(state.context["global_sf_n"]),
            code=state.best_candidate["code"],
            message="",
            debug_row=debug,
        )

    debug = state.last_debug or {}
    if str(debug.get("status", "")) == "pass":
        return _records.build_success_row(
            pid=state.pid,
            rounds=state.rounds_done,
            best_round=state.rounds_done,
            best_speedup_ratio=float(debug.get("speedup_ratio") or 0.0),
            baseline_time_ms=float(debug.get("baseline_time_ms") or 0.0),
            optimized_time_ms=float(debug.get("optimized_time_ms") or 0.0),
            global_sf_n=int(state.context["global_sf_n"]),
            code=state.current_code,
            message=(
                f"no valid speedup > 1.0 found; latest speedup_ratio="
                f"{float(debug.get('speedup_ratio') or 0.0):.6f}"
            ),
            debug_row=debug,
        )
    return _records.build_failure_row(
        pid=state.pid,
        rounds=state.rounds_done,
        stage=str(debug.get("stage", "performance")),
        error_type=str(debug.get("error_type", "no_speedup")),
        message=str(debug.get("message", "no valid speedup > 1.0 found")),
        debug_row=debug,
    )


def queue_priority(attempt: int) -> tuple[int, int]:
    if attempt <= 1:
        return (1, 0)
    return (0, -attempt)


def main() -> int:
    args = parse_args()
    args.max_rounds = max(1, min(3, int(args.max_rounds)))
    llm_j = max(1, int(args.llm_j))
    run_j = max(1, int(args.run_j))

    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)
    Path(args.session_dir).mkdir(parents=True, exist_ok=True)

    pending = list(
        _records.iter_pending_pids(
            seed_path=Path(args.seed),
            result_path=Path(args.result_output),
            limit=args.n,
            randomize=bool(args.random),
        )
    )
    if not pending:
        return 0

    max_rounds = max(1, int(args.max_rounds))
    pending_iter = iter(pending)
    llm_queue: list[tuple[int, int, int, OptimizeState]] = []
    debug_queue: list[tuple[int, int, int, OptimizeState]] = []
    sequence = 0
    pass_count = 0
    fail_count = 0
    completed_rows: list[dict] = []
    immediate_completions = 0

    def enqueue_llm(state: OptimizeState) -> None:
        nonlocal sequence
        priority = queue_priority(state.next_attempt)
        heapq.heappush(llm_queue, (*priority, sequence, state))
        sequence += 1

    def enqueue_debug(state: OptimizeState) -> None:
        nonlocal sequence
        priority = queue_priority(state.rounds_done)
        heapq.heappush(debug_queue, (*priority, sequence, state))
        sequence += 1

    def enqueue_next_pid() -> bool:
        nonlocal immediate_completions
        try:
            pid = next(pending_iter)
        except StopIteration:
            return False
        try:
            context = _records.load_optimize_context(
                pid=pid,
                seed_path=Path(args.seed),
                output_path=Path(args.verify_output),
                testcase_path=Path(args.testcase),
            )
        except Exception as exc:
            row = _records.build_failure_row(
                pid=pid,
                rounds=0,
                stage="input",
                error_type="input",
                message=str(exc),
            )
            finish_row(row)
            immediate_completions += 1
            return True
        enqueue_llm(OptimizeState(pid=pid, context=context, max_rounds=max_rounds))
        return True

    def finish_row(row: dict) -> None:
        nonlocal pass_count, fail_count
        _records.replace_jsonl_row(Path(args.result_output), pid=str(row.get("pid", "")), row=row)
        completed_rows.append(row)
        status = str(row.get("status", "")).strip()
        if status == "success":
            pass_count += 1
        else:
            fail_count += 1

    def fill_new_work() -> None:
        while len(llm_queue) < llm_j and enqueue_next_pid():
            pass

    with ThreadPoolExecutor(max_workers=llm_j) as llm_executor, ThreadPoolExecutor(max_workers=run_j) as debug_executor:
        llm_futures: dict = {}
        debug_futures: dict = {}
        exhausted = False

        def submit_llm() -> None:
            while len(llm_futures) < llm_j and llm_queue:
                _, _, _, state = heapq.heappop(llm_queue)
                attempt = state.next_attempt
                state.rounds_done = attempt
                future = llm_executor.submit(llm_attempt, state=state, args=args, attempt=attempt)
                llm_futures[future] = (state, attempt)

        def submit_debug() -> None:
            while len(debug_futures) < run_j and debug_queue:
                _, _, _, state = heapq.heappop(debug_queue)
                attempt = state.rounds_done
                future = debug_executor.submit(debug_attempt, state=state, args=args, attempt=attempt)
                debug_futures[future] = (state, attempt)

        with tqdm(total=len(pending), desc="pid", unit="pid") as progress:
            progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
            fill_new_work()
            if immediate_completions:
                progress.update(immediate_completions)
                immediate_completions = 0
            submit_llm()
            submit_debug()

            while (
                not exhausted
                or llm_queue
                or debug_queue
                or llm_futures
                or debug_futures
            ):
                if not llm_queue and not llm_futures:
                    exhausted = not enqueue_next_pid()
                submit_llm()
                submit_debug()

                active = set(llm_futures) | set(debug_futures)
                if not active:
                    continue
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    if future in llm_futures:
                        state, attempt = llm_futures.pop(future)
                        try:
                            llm_result = future.result()
                            state.messages = llm_result["messages"]
                            state.current_code = llm_result["code"]
                            write_state_session(state=state, args=args)
                            enqueue_debug(state)
                        except Exception as exc:
                            exc_messages = getattr(exc, "messages", None)
                            if isinstance(exc_messages, list) and exc_messages:
                                state.messages = exc_messages
                                write_state_session(state=state, args=args)
                            row = _records.build_failure_row(
                                pid=state.pid,
                                rounds=attempt,
                                stage="llm",
                                error_type="llm",
                                message=str(exc),
                            )
                            finish_row(row)
                            progress.update(1)
                    else:
                        state, attempt = debug_futures.pop(future)
                        try:
                            state.last_debug = future.result()
                        except Exception as exc:
                            state.last_debug = {
                                "status": "fail",
                                "stage": "remote",
                                "error_type": "remote_exec",
                                "message": str(exc),
                                "global_sf_n": state.context.get("global_sf_n"),
                                "baseline_time_ms": 0.0,
                                "optimized_time_ms": 0.0,
                                "speedup_ratio": 0.0,
                                "baseline_times_ms": [],
                                "optimized_times_ms": [],
                                "cases": [],
                            }
                        compact_debug = _bench.compact_debug_result(state.last_debug)
                        candidate_record = {
                            "round": attempt,
                            "code": state.current_code,
                            "debug_result": compact_debug,
                        }
                        state.previous_candidates.append(candidate_record)
                        state.best_candidate = select_best_candidate(
                            best_candidate=state.best_candidate,
                            candidate_record=candidate_record,
                        )
                        write_state_session(state=state, args=args)
                        should_stop = (
                            attempt >= state.max_rounds
                            or str(compact_debug.get("error_type", "")) == "baseline_compile"
                        )
                        if should_stop:
                            row = build_final_row(state)
                            finish_row(row)
                            progress.update(1)
                        else:
                            state.next_attempt = attempt + 1
                            enqueue_llm(state)
                    progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
                fill_new_work()
                if immediate_completions:
                    progress.update(immediate_completions)
                    immediate_completions = 0
                submit_llm()
                submit_debug()
    _remote.close_remote_clients()
    print_failure_summary(completed_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
