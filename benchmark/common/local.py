import json
import concurrent.futures
import heapq
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
OPTIMIZE_DIR = REPO_DIR / "optimize"
REMOTE_RUNNER_PATH = REPO_DIR / "optimize" / "_remote.sh"
_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")

if str(OPTIMIZE_DIR) not in sys.path:
    sys.path.insert(0, str(OPTIMIZE_DIR))

import _session  # noqa: E402


def safe_name(value: str) -> str:
    text = _SAFE_PATTERN.sub("__", str(value).strip())
    return text or "empty"


def run_local_job(*, job_dir: Path, timeout: int) -> dict:
    if not REMOTE_RUNNER_PATH.exists():
        raise ValueError(f"missing local runner: {REMOTE_RUNNER_PATH}")
    shutil.copy2(REMOTE_RUNNER_PATH, job_dir / "_remote.sh")
    result_path = job_dir / "result.json"
    completed = subprocess.run(
        ["sh", "./_remote.sh", "result.json"],
        cwd=str(job_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1, int(timeout)),
    )
    if completed.returncode != 0 and not result_path.exists():
        stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout_text = completed.stdout.decode("utf-8", errors="replace").strip()
        message = stderr_text or stdout_text or f"local runner failed with {completed.returncode}"
        raise RuntimeError(message)
    if not result_path.exists():
        raise RuntimeError("local runner exited without result.json")
    data = json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("local result must be a JSON object")
    return data


@dataclass
class BenchmarkState:
    row: dict
    sample_id: str
    max_rounds: int
    messages: list[dict] = field(default_factory=list)
    previous_candidates: list[dict] = field(default_factory=list)
    best_candidate: dict | None = None
    current_code: str = ""
    last_debug: dict | None = None
    next_attempt: int = 1
    rounds_done: int = 0


def queue_priority(attempt: int) -> tuple[int, int]:
    if attempt <= 1:
        return (1, 0)
    return (0, -attempt)


def llm_phase(state: BenchmarkState, attempt: int) -> str:
    if attempt == 1:
        return "generate"
    if state.last_debug is not None and str(state.last_debug.get("status", "")) != "pass":
        return "repair"
    return "improve"


def round_summary(*, attempt: int, debug: dict) -> dict:
    return {
        "round": attempt,
        "status": "pass" if str(debug.get("status", "")).strip() == "pass" else "fail",
        "stage": str(debug.get("stage", "")),
        "error_type": str(debug.get("error_type", "")),
        "speedup": float(debug.get("speedup_ratio") or 0.0),
        "baseline": float(debug.get("baseline_time_ms") or 0.0),
        "optimized": float(debug.get("optimized_time_ms") or 0.0),
        "message": str(debug.get("message", ""))[:500],
    }


def write_state_session(*, state: BenchmarkState, args) -> None:
    _session.write_session(
        session_dir=Path(args.session_dir),
        pid=state.sample_id,
        messages=state.messages,
        previous_candidates=[
            dict(candidate.get("summary", {"round": candidate.get("round")}))
            for candidate in state.previous_candidates
        ],
    )


def collect_rounds_history(state: BenchmarkState) -> list[dict]:
    history: list[dict] = []
    for candidate in state.previous_candidates:
        summary = candidate.get("summary")
        if isinstance(summary, dict):
            history.append(dict(summary))
        else:
            history.append({"round": candidate.get("round")})
    return history


def run_benchmark_pipeline(
    *,
    pending: list[dict],
    args,
    output_path: Path,
    replace_result_row,
    build_success_row,
    build_failure_row,
    select_best_candidate,
    generate_candidate,
    repair_candidate,
    improve_candidate,
    debug_candidate,
    log_sample,
) -> None:
    max_rounds = max(1, min(3, int(args.max_rounds)))
    llm_j = max(1, int(args.llm_j))
    run_j = max(1, int(args.run_j))
    print(f"concurrency: llm_j={llm_j} run_j={run_j}", file=sys.stderr)
    Path(args.session_dir).mkdir(parents=True, exist_ok=True)

    pending_iter = iter(pending)
    llm_queue: list[tuple[int, int, int, BenchmarkState]] = []
    debug_queue: list[tuple[int, int, int, BenchmarkState]] = []
    sequence = 0
    completed_count = 0

    def enqueue_llm(state: BenchmarkState) -> None:
        nonlocal sequence
        priority = queue_priority(state.next_attempt)
        heapq.heappush(llm_queue, (*priority, sequence, state))
        sequence += 1

    def enqueue_debug(state: BenchmarkState) -> None:
        nonlocal sequence
        priority = queue_priority(state.rounds_done)
        heapq.heappush(debug_queue, (*priority, sequence, state))
        sequence += 1

    def finish_row(state: BenchmarkState, row: dict) -> None:
        nonlocal completed_count
        completed_count += 1
        replace_result_row(output_path, row)
        print(
            f"[done {completed_count}/{len(pending)}] {state.sample_id} -> {row.get('status')}",
            file=sys.stderr,
        )

    def build_final_row(state: BenchmarkState) -> dict:
        history = collect_rounds_history(state)
        if state.best_candidate is not None:
            return build_success_row(
                sample_id=state.sample_id,
                rounds=state.rounds_done,
                best_round=int(state.best_candidate["round"]),
                code=str(state.best_candidate["code"]),
                debug_result=state.best_candidate["debug_result"],
                message="",
                rounds_history=history,
            )
        if state.last_debug is not None and str(state.last_debug.get("status", "")) == "pass":
            return build_success_row(
                sample_id=state.sample_id,
                rounds=state.rounds_done,
                best_round=state.rounds_done,
                code=state.current_code,
                debug_result=state.last_debug,
                message=(
                    f"no valid speedup > 1.0 found; latest speedup_ratio="
                    f"{float(state.last_debug.get('speedup_ratio') or 0.0):.6f}"
                ),
                rounds_history=history,
            )
        return build_failure_row(
            sample_id=state.sample_id,
            rounds=state.rounds_done,
            stage=str((state.last_debug or {}).get("stage", "performance")),
            error_type=str((state.last_debug or {}).get("error_type", "no_speedup")),
            message=str((state.last_debug or {}).get("message", "no valid speedup > 1.0 found")),
            code=state.current_code,
            debug_result=state.last_debug,
            rounds_history=history,
        )

    def enqueue_next_sample() -> bool:
        try:
            row = next(pending_iter)
        except StopIteration:
            return False
        sample_id = str(row["id"])
        log_sample(sample_id, "start optimization")
        enqueue_llm(BenchmarkState(row=row, sample_id=sample_id, max_rounds=max_rounds))
        return True

    def fill_new_work(*, llm_inflight: int = 0) -> None:
        while len(llm_queue) + llm_inflight < llm_j and enqueue_next_sample():
            pass

    def run_llm(state: BenchmarkState, attempt: int) -> dict:
        phase = llm_phase(state, attempt)
        log_sample(state.sample_id, f"round {attempt}: calling LLM {phase}")
        if phase == "generate":
            return generate_candidate(
                config_path=Path(args.config),
                row=state.row,
                messages=state.messages,
                attempt=attempt,
            )
        if phase == "repair":
            return repair_candidate(
                config_path=Path(args.config),
                row=state.row,
                debug_result=state.last_debug or {},
                messages=state.messages,
                attempt=attempt,
            )
        return improve_candidate(
            config_path=Path(args.config),
            row=state.row,
            debug_result=state.last_debug or {},
            messages=state.messages,
            attempt=attempt,
        )

    def run_debug(state: BenchmarkState, attempt: int) -> dict:
        log_sample(state.sample_id, f"round {attempt}: start local validation")
        return debug_candidate(
            row=state.row,
            optimized_code=state.current_code,
            attempt=attempt,
            tmp_dir=Path(args.tmp_dir),
            compile_cmd=args.compile_cmd,
            compile_timeout=args.compile_timeout,
            run_timeout=args.run_timeout,
            wall_timeout=args.wall_timeout,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=llm_j) as llm_executor, concurrent.futures.ThreadPoolExecutor(max_workers=run_j) as debug_executor:
        llm_futures: dict[concurrent.futures.Future, tuple[BenchmarkState, int]] = {}
        debug_futures: dict[concurrent.futures.Future, tuple[BenchmarkState, int]] = {}
        exhausted = False

        def submit_llm() -> None:
            while len(llm_futures) < llm_j and llm_queue:
                _, _, _, state = heapq.heappop(llm_queue)
                attempt = state.next_attempt
                state.rounds_done = attempt
                future = llm_executor.submit(run_llm, state, attempt)
                llm_futures[future] = (state, attempt)

        def submit_debug() -> None:
            while len(debug_futures) < run_j and debug_queue:
                _, _, _, state = heapq.heappop(debug_queue)
                attempt = state.rounds_done
                future = debug_executor.submit(run_debug, state, attempt)
                debug_futures[future] = (state, attempt)

        fill_new_work()
        submit_llm()
        submit_debug()

        while not exhausted or llm_queue or debug_queue or llm_futures or debug_futures:
            if not llm_queue and not llm_futures:
                exhausted = not enqueue_next_sample()
            submit_llm()
            submit_debug()

            active = set(llm_futures) | set(debug_futures)
            if not active:
                continue
            done, _ = concurrent.futures.wait(active, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                if future in llm_futures:
                    state, attempt = llm_futures.pop(future)
                    try:
                        llm_result = future.result()
                        state.current_code = llm_result["code"]
                        state.messages = llm_result["messages"]
                        write_state_session(state=state, args=args)
                        log_sample(state.sample_id, f"round {attempt}: LLM returned candidate ({len(state.current_code)} chars)")
                        enqueue_debug(state)
                    except Exception as exc:
                        log_sample(state.sample_id, f"round {attempt}: LLM failed: {exc}")
                        exc_messages = getattr(exc, "messages", None)
                        if isinstance(exc_messages, list) and exc_messages:
                            state.messages = exc_messages
                        state.last_debug = {
                            "status": "fail",
                            "stage": "llm",
                            "error_type": "llm_generate",
                            "message": str(exc),
                            "global_sf_n": 1,
                            "baseline_time_ms": 0.0,
                            "optimized_time_ms": 0.0,
                            "speedup_ratio": 0.0,
                            "baseline_times_ms": [],
                            "optimized_times_ms": [],
                            "cases": [],
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
                        finish_row(
                            state,
                            build_failure_row(
                                sample_id=state.sample_id,
                                rounds=attempt,
                                stage="llm",
                                error_type="llm_generate",
                                message=str(exc),
                                code=state.current_code,
                                debug_result=state.last_debug,
                                rounds_history=collect_rounds_history(state),
                            ),
                        )
                else:
                    state, attempt = debug_futures.pop(future)
                    try:
                        state.last_debug = future.result()
                    except Exception as exc:
                        state.last_debug = {
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
                    log_sample(
                        state.sample_id,
                        "round "
                        + str(attempt)
                        + ": validation result "
                        + f"status={state.last_debug.get('status')} stage={state.last_debug.get('stage')} "
                        + f"error={state.last_debug.get('error_type') or '-'} "
                        + f"speedup={float(state.last_debug.get('speedup_ratio') or 0.0):.6f}",
                    )
                    candidate_record = {
                        "round": attempt,
                        "code": state.current_code,
                        "debug_result": state.last_debug,
                        "summary": round_summary(attempt=attempt, debug=state.last_debug),
                    }
                    state.previous_candidates.append(candidate_record)
                    state.best_candidate = select_best_candidate(
                        state.best_candidate,
                        candidate_record,
                    )
                    write_state_session(state=state, args=args)
                    if attempt >= state.max_rounds:
                        finish_row(state, build_final_row(state))
                    else:
                        state.next_attempt = attempt + 1
                        enqueue_llm(state)
            fill_new_work(llm_inflight=len(llm_futures))
            submit_llm()
            submit_debug()
