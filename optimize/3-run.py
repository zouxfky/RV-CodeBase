from __future__ import annotations

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

import _records
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
    parser.add_argument(
        "--compile-cmd",
        default="g++ -std=c++17 -O3 -march=rv64gcv -mabi=lp64d",
    )
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--wall-timeout", type=int, default=900)
    parser.add_argument("--output-limit-bytes", type=int, default=10 * 1024 * 1024)
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
    if str(debug.get("status", "")).strip() != "pass":
        return best_candidate
    if best_candidate is None:
        return candidate_record
    if float(debug.get("speedup_ratio") or 0.0) > float(best_candidate["debug_result"].get("speedup_ratio") or 0.0):
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
    counts = Counter(str(row.get("stage", "")) for row in failures)
    for stage, count in counts.most_common():
        print(f"  {count}x stage={stage or '-'}", file=sys.stderr)

    print("\nFailed rows:", file=sys.stderr)
    for row in failures:
        pid = str(row.get("pid", ""))
        rounds = row.get("round", "")
        stage = str(row.get("stage", ""))
        message = truncate_message(str(row.get("message", "")))
        print(
            f"  {pid} rounds={rounds} stage={stage or '-'} "
            f"message={message}",
            file=sys.stderr,
        )


class ProgressLogger:
    def __init__(self, *, total: int) -> None:
        self.pass_count = 0
        self.fail_count = 0
        self.total_bar = tqdm(
            total=total,
            desc="total",
            unit="pid",
            position=0,
            dynamic_ncols=True,
            leave=True,
        )

    def start(self, pid: str, *, attempt: int, step: str) -> None:
        return

    def ok(self, pid: str, *, attempt: int, step: str, message: str = "") -> None:
        return

    def fail(self, pid: str, *, attempt: int, step: str, message: str) -> None:
        return

    def finish(self, row: dict) -> None:
        if str(row.get("status", "")).strip() == "success":
            self.pass_count += 1
        else:
            self.fail_count += 1
        self.total_bar.update(1)
        self.total_bar.set_postfix(
            pass_count=self.pass_count,
            fail_count=self.fail_count,
            refresh=True,
        )

    def close(self) -> None:
        self.total_bar.close()


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


def llm_step_name(*, state: OptimizeState, attempt: int) -> str:
    if attempt == 1:
        return "LLM生成"
    if state.last_debug is not None and str(state.last_debug.get("status", "")) != "pass":
        return "LLM修复"
    return "LLM提升"


def normalize_stage(stage: str) -> str:
    value = str(stage).strip()
    if value == "exec":
        return "remote"
    if value in {"input", "llm", "remote", "compile", "run", "correctness", "performance"}:
        return value
    return value or "performance"


def sanitize_message(*, stage: str, message: str, max_chars: int = 500) -> str:
    clean_stage = normalize_stage(stage)
    text = str(message).replace("\r", "").strip()
    if clean_stage == "correctness":
        if "float mismatch" in text:
            first_line = next((line.strip() for line in text.splitlines() if "float mismatch" in line), "")
            return f"correctness: {truncate_message(first_line or 'float mismatch', max_chars=max_chars)}"
        return "correctness: output mismatch"
    if clean_stage == "run":
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped in {"stdout:", "stderr:"}:
                continue
            lines.append(stripped)
        text = " ".join(lines) or "process exited with non-zero status"
    if not text:
        return ""
    if clean_stage and not text.startswith(f"{clean_stage}:"):
        text = f"{clean_stage}: {text}"
    return truncate_message(text, max_chars=max_chars)


def sanitize_debug(debug: dict) -> dict:
    stage = normalize_stage(str(debug.get("stage", "")))
    return {
        "status": str(debug.get("status", "")).strip() or "fail",
        "stage": stage,
        "message": sanitize_message(stage=stage, message=str(debug.get("message", ""))),
        "global_sf_n": debug.get("global_sf_n"),
        "baseline_time_ms": float(debug.get("baseline_time_ms") or 0.0),
        "optimized_time_ms": float(debug.get("optimized_time_ms") or 0.0),
        "speedup_ratio": float(debug.get("speedup_ratio") or 0.0),
    }


def round_summary(*, attempt: int, debug: dict) -> dict:
    clean = sanitize_debug(debug)
    return {
        "round": attempt,
        "status": "pass" if clean["status"] == "pass" else "fail",
        "speedup": float(clean["speedup_ratio"]),
        "baseline": float(clean["baseline_time_ms"]),
        "optimized": float(clean["optimized_time_ms"]),
        "message": clean["message"],
    }


def is_unrecoverable_debug_failure(debug: dict) -> bool:
    if str(debug.get("status", "")).strip() == "pass":
        return False
    stage = str(debug.get("stage", "")).strip()
    error_type = str(debug.get("error_type", "")).strip()
    return stage == "remote" or error_type in {
        "baseline_compile",
        "remote_exec",
        "remote_runner",
    }


def write_state_session(*, state: OptimizeState, args: argparse.Namespace) -> None:
    _session.write_session(
        session_dir=Path(args.session_dir),
        pid=state.pid,
        messages=state.messages,
        previous_candidates=[
            dict(candidate.get("summary", {"round": candidate.get("round")}))
            for candidate in state.previous_candidates
        ],
    )


def build_final_row(state: OptimizeState) -> dict:
    history = [
        dict(candidate.get("summary", {}))
        for candidate in state.previous_candidates
        if isinstance(candidate.get("summary"), dict)
    ]
    if state.best_candidate is not None:
        debug = sanitize_debug(state.best_candidate["debug_result"])
        best_round = int(state.best_candidate["round"])
        speedup = float(debug["speedup_ratio"])
        message = (
            f"best={best_round} speedup={speedup:.6f}"
            if speedup > 1.0
            else "correctness passed, but no speedup > 1.0"
        )
        return _records.build_result_row(
            pid=state.pid,
            status="success",
            stage="performance",
            round=state.rounds_done,
            best=best_round,
            speedup=speedup,
            baseline=float(debug["baseline_time_ms"]),
            optimized=float(debug["optimized_time_ms"]),
            sf=int(state.context["global_sf_n"]),
            code=state.best_candidate["code"],
            message=message,
            history=history,
        )

    debug = sanitize_debug(state.last_debug or {})
    if str(debug.get("status", "")) == "pass":
        speedup = float(debug.get("speedup_ratio") or 0.0)
        return _records.build_result_row(
            pid=state.pid,
            status="success",
            stage="performance",
            round=state.rounds_done,
            best=state.rounds_done,
            speedup=speedup,
            baseline=float(debug.get("baseline_time_ms") or 0.0),
            optimized=float(debug.get("optimized_time_ms") or 0.0),
            sf=int(state.context["global_sf_n"]),
            code=state.current_code,
            message=(
                f"best={state.rounds_done} speedup={speedup:.6f}"
                if speedup > 1.0
                else "correctness passed, but no speedup > 1.0"
            ),
            history=history,
        )
    stage = normalize_stage(str(debug.get("stage", "performance")))
    message = sanitize_message(stage=stage, message=str(debug.get("message", "no correctness-passing candidate found")))
    return _records.build_result_row(
        pid=state.pid,
        status="fail",
        stage=stage,
        round=state.rounds_done,
        best=0,
        speedup=0.0,
        baseline=0.0,
        optimized=0.0,
        sf=int(state.context.get("global_sf_n") or 0),
        code="",
        message=message,
        history=history,
    )


def queue_priority(attempt: int) -> tuple[int, int]:
    if attempt <= 1:
        return (1, 0)
    return (0, -attempt)


def debug_attempt(*, state: OptimizeState, args: argparse.Namespace, attempt: int) -> dict:
    return DEBUG_API.debug_candidate(
        pid=state.pid,
        context=state.context,
        optimized_code=state.current_code,
        attempt=attempt,
        tmp_dir=Path(args.tmp_dir),
        compile_cmd=args.compile_cmd,
        compile_timeout=args.compile_timeout,
        run_timeout=args.run_timeout,
        wall_timeout=args.wall_timeout,
        output_limit_bytes=args.output_limit_bytes,
    )


def main() -> int:
    args = parse_args()
    args.max_rounds = max(1, min(3, int(args.max_rounds)))
    llm_j = max(1, int(args.llm_j))
    run_j = max(1, int(args.run_j))

    print(
        "优化流程启动 "
        f"seed={args.seed} result_output={args.result_output} "
        f"max_rounds={args.max_rounds} llm_j={llm_j} run_j={run_j}",
        flush=True,
    )

    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)
    Path(args.session_dir).mkdir(parents=True, exist_ok=True)

    print("加载待优化 pid ...", flush=True)
    pending = list(
        _records.iter_pending_pids(
            seed_path=Path(args.seed),
            result_path=Path(args.result_output),
            limit=args.n,
            randomize=bool(args.random),
        )
    )
    print(f"待优化 pid 数量: {len(pending)}", flush=True)
    if not pending:
        print("没有待优化 pid，退出。", flush=True)
        return 0

    print("加载优化上下文索引 seed/output/testcase ...", flush=True)
    seed_rows = _records.load_pid_map(Path(args.seed))
    output_rows = _records.load_pid_map(Path(args.verify_output))
    testcase_rows = _records.load_pid_map(Path(args.testcase))
    print(
        "优化上下文索引加载完成 "
        f"seed={len(seed_rows)} output={len(output_rows)} testcase={len(testcase_rows)}",
        flush=True,
    )

    max_rounds = max(1, int(args.max_rounds))
    pending_iter = iter(pending)
    llm_queue: list[tuple[int, int, int, OptimizeState]] = []
    debug_queue: list[tuple[int, int, int, OptimizeState]] = []
    sequence = 0
    pass_count = 0
    fail_count = 0
    completed_rows: list[dict] = []
    logger = ProgressLogger(total=len(pending))

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

    def finish_row(row: dict) -> None:
        nonlocal pass_count, fail_count
        _records.replace_jsonl_row(Path(args.result_output), pid=str(row.get("pid", "")), row=row)
        completed_rows.append(row)
        status = str(row.get("status", "")).strip()
        if status == "success":
            pass_count += 1
        else:
            fail_count += 1
        logger.finish(row)

    def enqueue_next_pid() -> bool:
        try:
            pid = next(pending_iter)
        except StopIteration:
            return False
        try:
            context = _records.build_optimize_context_from_rows(
                pid=pid,
                seed_row=seed_rows.get(pid),
                output_row=output_rows.get(pid),
                testcase_row=testcase_rows.get(pid),
            )
        except Exception as exc:
            row = _records.build_result_row(
                pid=pid,
                status="fail",
                stage="input",
                round=0,
                best=0,
                speedup=0.0,
                baseline=0.0,
                optimized=0.0,
                sf=0,
                code="",
                message=str(exc),
                history=[],
            )
            finish_row(row)
            return True
        enqueue_llm(OptimizeState(pid=pid, context=context, max_rounds=max_rounds))
        return True

    def fill_new_work(*, llm_inflight: int = 0) -> None:
        while len(llm_queue) + llm_inflight < llm_j and enqueue_next_pid():
            pass

    try:
        with ThreadPoolExecutor(max_workers=llm_j) as llm_executor, ThreadPoolExecutor(max_workers=run_j) as debug_executor:
            llm_futures: dict = {}
            debug_futures: dict = {}
            exhausted = False

            def submit_llm() -> None:
                while len(llm_futures) < llm_j and llm_queue:
                    _, _, _, state = heapq.heappop(llm_queue)
                    attempt = state.next_attempt
                    state.rounds_done = attempt
                    logger.start(state.pid, attempt=attempt, step=llm_step_name(state=state, attempt=attempt))
                    future = llm_executor.submit(llm_attempt, state=state, args=args, attempt=attempt)
                    llm_futures[future] = (state, attempt)

            def submit_debug() -> None:
                while len(debug_futures) < run_j and debug_queue:
                    _, _, _, state = heapq.heappop(debug_queue)
                    attempt = state.rounds_done
                    logger.start(state.pid, attempt=attempt, step="校验")
                    future = debug_executor.submit(debug_attempt, state=state, args=args, attempt=attempt)
                    debug_futures[future] = (state, attempt)

            fill_new_work(llm_inflight=len(llm_futures))
            submit_llm()
            submit_debug()

            while not exhausted or llm_queue or debug_queue or llm_futures or debug_futures:
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
                        step = llm_step_name(state=state, attempt=attempt)
                        try:
                            llm_result = future.result()
                            state.messages = llm_result["messages"]
                            state.current_code = llm_result["code"]
                            write_state_session(state=state, args=args)
                            logger.ok(state.pid, attempt=attempt, step=step)
                            enqueue_debug(state)
                        except Exception as exc:
                            logger.fail(state.pid, attempt=attempt, step=step, message=str(exc))
                            exc_messages = getattr(exc, "messages", None)
                            if isinstance(exc_messages, list) and exc_messages:
                                state.messages = exc_messages
                                write_state_session(state=state, args=args)
                            message = sanitize_message(stage="llm", message=str(exc))
                            state.last_debug = {
                                "status": "fail",
                                "stage": "llm",
                                "message": message,
                                "global_sf_n": state.context.get("global_sf_n"),
                                "baseline_time_ms": 0.0,
                                "optimized_time_ms": 0.0,
                                "speedup_ratio": 0.0,
                            }
                            state.previous_candidates.append(
                                {
                                    "round": attempt,
                                    "code": "",
                                    "debug_result": state.last_debug,
                                    "summary": round_summary(attempt=attempt, debug=state.last_debug),
                                }
                            )
                            write_state_session(state=state, args=args)
                            finish_row(build_final_row(state))
                    else:
                        state, attempt = debug_futures.pop(future)
                        step = "校验"
                        try:
                            state.last_debug = future.result()
                        except Exception as exc:
                            state.last_debug = {
                                "status": "fail",
                                "stage": "run",
                                "error_type": "local_exec",
                                "message": str(exc),
                                "global_sf_n": state.context.get("global_sf_n"),
                                "baseline_time_ms": 0.0,
                                "optimized_time_ms": 0.0,
                                "speedup_ratio": 0.0,
                                "baseline_times_ms": [],
                                "optimized_times_ms": [],
                                "cases": [],
                            }
                        compact_debug = sanitize_debug(state.last_debug)
                        state.last_debug = compact_debug
                        summary = round_summary(attempt=attempt, debug=compact_debug)
                        if str(compact_debug.get("status", "")) == "pass":
                            speedup = float(compact_debug.get("speedup_ratio") or 0.0)
                            logger.ok(state.pid, attempt=attempt, step=step, message=f"speedup_ratio={speedup:.6f}")
                        else:
                            logger.fail(
                                state.pid,
                                attempt=attempt,
                                step=step,
                                message=str(compact_debug.get("message", "")),
                            )
                        candidate_record = {
                            "round": attempt,
                            "code": state.current_code,
                            "debug_result": compact_debug,
                            "summary": summary,
                        }
                        state.previous_candidates.append(candidate_record)
                        state.best_candidate = select_best_candidate(
                            best_candidate=state.best_candidate,
                            candidate_record=candidate_record,
                        )
                        write_state_session(state=state, args=args)
                        should_stop = (
                            attempt >= state.max_rounds
                            or is_unrecoverable_debug_failure(compact_debug)
                        )
                        if should_stop:
                            finish_row(build_final_row(state))
                        else:
                            state.next_attempt = attempt + 1
                            enqueue_llm(state)
                fill_new_work(llm_inflight=len(llm_futures))
                submit_llm()
                submit_debug()
    finally:
        logger.close()
    print_failure_summary(completed_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
