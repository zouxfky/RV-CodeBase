from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    parser.add_argument("--remote-host", default="root@sg2044")
    parser.add_argument("--remote-hosts", default="root@sg2044:4,root@milkv1:1,root@milkv2:1,root@milkv3:1")
    parser.add_argument("--remote-root", default="/tmp/rv_opt")
    parser.add_argument(
        "--compile-cmd",
        default="g++ -std=c++17 -O3 -march=rv64gcv -mabi=lp64d",
    )
    parser.add_argument("--compile-timeout", type=int, default=120)
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--ssh-timeout", type=int, default=900)
    parser.add_argument("--remote-probe-timeout", type=int, default=8)
    parser.add_argument("--output-limit-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("-j", "--jobs", type=int, default=None)
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
        self.batch_bar = None
        self.total_bar = tqdm(
            total=total,
            desc="total",
            unit="pid",
            position=0,
            dynamic_ncols=True,
            leave=True,
        )

    def start_batch(self, *, batch_index: int, batch_total: int, steps: int, size: int) -> None:
        self.close_batch()
        self.batch_bar = tqdm(
            total=steps,
            desc=f"batch {batch_index}/{batch_total}",
            unit="step",
            position=1,
            dynamic_ncols=True,
            leave=False,
        )
        self.batch_bar.set_postfix(size=size, refresh=True)

    def batch_step(self, message: str) -> None:
        if self.batch_bar is None:
            return
        self.batch_bar.update(1)
        self.batch_bar.set_postfix_str(message, refresh=True)

    def close_batch(self) -> None:
        if self.batch_bar is None:
            return
        self.batch_bar.close()
        self.batch_bar = None

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
        self.close_batch()
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


def parse_remote_hosts(value: str, *, fallback_host: str) -> list[tuple[str, int, int | None]]:
    text = str(value or "").strip()
    if not text:
        return [(str(fallback_host), 1, None)]
    hosts: list[tuple[str, int, int | None]] = []
    for raw_item in text.split(","):
        item = raw_item.strip()
        if not item:
            continue
        parts = item.rsplit(":", 2)
        max_slots: int | None = None
        if len(parts) == 3:
            host, weight_text, max_slots_text = parts
            host = host.strip()
            try:
                max_slots = int(max_slots_text)
            except ValueError as exc:
                raise ValueError(f"invalid remote host max slots: {item}") from exc
            if max_slots <= 0:
                raise ValueError(f"remote host max slots must be positive: {item}")
        elif len(parts) == 2:
            host, weight_text = parts
            host = host.strip()
            try:
                weight = int(weight_text)
            except ValueError as exc:
                raise ValueError(f"invalid remote host weight: {item}") from exc
        else:
            host = item
            weight = 1
        if len(parts) == 3:
            try:
                weight = int(weight_text)
            except ValueError as exc:
                raise ValueError(f"invalid remote host weight: {item}") from exc
        if not host:
            raise ValueError(f"invalid remote host entry: {item}")
        if weight <= 0:
            raise ValueError(f"remote host weight must be positive: {item}")
        hosts.append((host, weight, max_slots))
    if not hosts:
        return [(str(fallback_host), 1, None)]
    return hosts


def allocate_weighted_slots(hosts: list[tuple[str, int, int | None]], total_slots: int) -> dict[str, int]:
    total_slots = max(1, int(total_slots))
    if len(hosts) == 1:
        host, _, max_slots = hosts[0]
        return {host: min(total_slots, max_slots) if max_slots is not None else total_slots}

    allocations = {host: 0 for host, _, _ in hosts}
    for _ in range(total_slots):
        candidates = [
            (host, weight, max_slots)
            for host, weight, max_slots in hosts
            if max_slots is None or allocations[host] < max_slots
        ]
        if not candidates:
            break
        host, _, _ = min(
            candidates,
            key=lambda item: (allocations[item[0]] / item[1], allocations[item[0]], item[0]),
        )
        allocations[host] += 1
    return {host: slots for host, slots in allocations.items() if slots > 0}


def probe_remote_host(host: str, *, timeout: int) -> tuple[str, bool, str]:
    client = _remote.RemoteClient(host=host, connect_timeout=max(1, int(timeout)))
    try:
        client.connect()
        return host, True, ""
    except Exception as exc:
        return host, False, truncate_message(str(exc), max_chars=200)
    finally:
        client.close()


def filter_available_remote_slots(remote_slots: dict[str, int], *, timeout: int) -> dict[str, int]:
    if not remote_slots:
        return {}

    available: dict[str, int] = {}
    disabled: list[tuple[str, int, str]] = []
    with ThreadPoolExecutor(max_workers=len(remote_slots)) as executor:
        futures = [
            executor.submit(probe_remote_host, host, timeout=timeout)
            for host in remote_slots
        ]
        for future in futures:
            host, ok, message = future.result()
            slots = int(remote_slots[host])
            if ok:
                available[host] = slots
            else:
                disabled.append((host, slots, message))

    if disabled:
        disabled_text = ", ".join(
            f"{host}({slots} slots): {message or 'unavailable'}"
            for host, slots, message in disabled
        )
        print(f"禁用不可用远端: {disabled_text}", flush=True)
    return available


def main() -> int:
    args = parse_args()
    args.max_rounds = max(1, min(3, int(args.max_rounds)))
    jobs = int(args.jobs) if args.jobs is not None else 1
    jobs = max(1, jobs)
    remote_hosts = parse_remote_hosts(args.remote_hosts, fallback_host=args.remote_host)
    planned_remote_slots = allocate_weighted_slots(remote_hosts, jobs)

    print(
        "优化流程启动 "
        f"seed={args.seed} result_output={args.result_output} "
        f"remote_hosts={planned_remote_slots} max_rounds={args.max_rounds} "
        f"jobs={jobs}",
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

    print("探测远端可用性 ...", flush=True)
    remote_slots = filter_available_remote_slots(
        planned_remote_slots,
        timeout=int(args.remote_probe_timeout),
    )
    if not remote_slots:
        print("没有可用远端，退出。", flush=True)
        return 1
    if remote_slots != planned_remote_slots:
        print(f"可用远端: {remote_slots}", flush=True)

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
    pass_count = 0
    fail_count = 0
    completed_rows: list[dict] = []
    logger = ProgressLogger(total=len(pending))
    batch_size = max(1, sum(int(slots) for slots in remote_slots.values()))
    if batch_size != jobs:
        print(f"实际并发 pid 数量: {batch_size}", flush=True)

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

    def build_input_failure_row(pid: str, exc: Exception) -> dict:
        return _records.build_result_row(
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

    def build_unhandled_failure_row(pid: str, exc: Exception) -> dict:
        return _records.build_result_row(
            pid=pid,
            status="fail",
            stage="run",
            round=0,
            best=0,
            speedup=0.0,
            baseline=0.0,
            optimized=0.0,
            sf=0,
            code="",
            message=sanitize_message(stage="run", message=str(exc)),
            history=[],
        )

    def load_state(pid: str) -> OptimizeState | dict:
        try:
            context = _records.build_optimize_context_from_rows(
                pid=pid,
                seed_row=seed_rows.get(pid),
                output_row=output_rows.get(pid),
                testcase_row=testcase_rows.get(pid),
            )
            return OptimizeState(pid=pid, context=context, max_rounds=max_rounds)
        except Exception as exc:
            return build_input_failure_row(pid, exc)

    def prepare_remote_job(state: OptimizeState, *, attempt: int) -> dict:
        job_dir = DEBUG_API.build_local_job_dir(
            tmp_dir=Path(args.tmp_dir),
            pid=state.pid,
            attempt=attempt,
        )
        static_dir = DEBUG_API.build_local_static_dir(
            tmp_dir=Path(args.tmp_dir),
            pid=state.pid,
        )
        payload = _bench.build_remote_job_payload(
            pid=state.pid,
            baseline_code=state.context["baseline_code"],
            optimized_code=state.current_code,
            main_program=state.context["main_program"],
            testcases=state.context["testcases"],
            global_sf_n=int(state.context["global_sf_n"]),
            compile_cmd=args.compile_cmd,
            compile_timeout=args.compile_timeout,
            run_timeout=args.run_timeout,
        )
        payload["wall_timeout"] = max(1, int(args.ssh_timeout) - 5)
        payload["output_limit_bytes"] = max(0, int(args.output_limit_bytes))
        DEBUG_API.write_remote_static_job_files(static_dir=static_dir, payload=payload)
        DEBUG_API.write_remote_optimized_file(job_dir=job_dir, optimized_code=state.current_code)
        return {
            "pid": state.pid,
            "attempt": attempt,
            "local_job_dir": job_dir,
            "local_static_dir": static_dir,
        }

    def run_debug_batch(host: str, states: list[OptimizeState], *, attempt: int) -> dict[str, dict]:
        jobs_payload = [
            prepare_remote_job(state, attempt=attempt)
            for state in states
        ]
        try:
            remote_results = _remote.run_remote_jobs_batch(
                host=host,
                remote_root=args.remote_root,
                jobs=jobs_payload,
                timeout=int(args.ssh_timeout),
            )
        except Exception as exc:
            return {
                state.pid: {
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
                for state in states
            }

        debug_results: dict[str, dict] = {}
        state_by_job_name = {
            str(job["remote_job_name"]): state
            for job, state in zip(jobs_payload, states)
            if "remote_job_name" in job
        }
        for job_name, state in state_by_job_name.items():
            remote_result = remote_results.get(job_name)
            if remote_result is None:
                debug_results[state.pid] = {
                    "status": "fail",
                    "stage": "remote",
                    "error_type": "remote_runner",
                    "message": "missing batch result",
                    "global_sf_n": state.context.get("global_sf_n"),
                    "baseline_time_ms": 0.0,
                    "optimized_time_ms": 0.0,
                    "speedup_ratio": 0.0,
                    "baseline_times_ms": [],
                    "optimized_times_ms": [],
                    "cases": [],
                }
            else:
                debug_results[state.pid] = _bench.summarize_remote_result(remote_result)
        return debug_results

    def apply_llm_failure(state: OptimizeState, *, attempt: int, exc: Exception) -> None:
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

    def apply_debug_result(state: OptimizeState, *, attempt: int, debug: dict) -> bool:
        state.last_debug = sanitize_debug(debug)
        summary = round_summary(attempt=attempt, debug=state.last_debug)
        if str(state.last_debug.get("status", "")) == "pass":
            speedup = float(state.last_debug.get("speedup_ratio") or 0.0)
            logger.ok(state.pid, attempt=attempt, step="校验", message=f"speedup_ratio={speedup:.6f}")
        else:
            logger.fail(
                state.pid,
                attempt=attempt,
                step="校验",
                message=str(state.last_debug.get("message", "")),
            )
        candidate_record = {
            "round": attempt,
            "code": state.current_code,
            "debug_result": state.last_debug,
            "summary": summary,
        }
        state.previous_candidates.append(candidate_record)
        state.best_candidate = select_best_candidate(
            best_candidate=state.best_candidate,
            candidate_record=candidate_record,
        )
        write_state_session(state=state, args=args)
        return attempt >= state.max_rounds or is_unrecoverable_debug_failure(state.last_debug)

    def process_batch(batch_pids: list[str], *, batch_index: int, batch_total: int) -> None:
        logger.start_batch(
            batch_index=batch_index,
            batch_total=batch_total,
            steps=max_rounds * 2,
            size=len(batch_pids),
        )
        active: list[OptimizeState] = []
        try:
            for pid in batch_pids:
                loaded = load_state(pid)
                if isinstance(loaded, OptimizeState):
                    active.append(loaded)
                else:
                    finish_row(loaded)

            for attempt in range(1, max_rounds + 1):
                round_states = [state for state in active if state.next_attempt == attempt]
                if not round_states:
                    logger.batch_step(f"round={attempt} LLM 跳过")
                    logger.batch_step(f"round={attempt} 校验 跳过")
                    continue

                with ThreadPoolExecutor(max_workers=len(round_states)) as llm_executor:
                    future_to_state = {}
                    for state in round_states:
                        state.rounds_done = attempt
                        step = llm_step_name(state=state, attempt=attempt)
                        logger.start(state.pid, attempt=attempt, step=step)
                        future = llm_executor.submit(llm_attempt, state=state, args=args, attempt=attempt)
                        future_to_state[future] = state

                    llm_ok: list[OptimizeState] = []
                    for future in as_completed(future_to_state):
                        state = future_to_state[future]
                        step = llm_step_name(state=state, attempt=attempt)
                        try:
                            llm_result = future.result()
                            state.messages = llm_result["messages"]
                            state.current_code = llm_result["code"]
                            write_state_session(state=state, args=args)
                            logger.ok(state.pid, attempt=attempt, step=step)
                            llm_ok.append(state)
                        except Exception as exc:
                            logger.fail(state.pid, attempt=attempt, step=step, message=str(exc))
                            apply_llm_failure(state, attempt=attempt, exc=exc)
                            finish_row(build_final_row(state))
                            active.remove(state)
                logger.batch_step(f"round={attempt} LLM 完成 ok={len(llm_ok)} fail={len(round_states) - len(llm_ok)}")

                if not llm_ok:
                    logger.batch_step(f"round={attempt} 校验 跳过")
                    continue

                host_groups: dict[str, list[OptimizeState]] = {}
                offset = 0
                for host, slots in remote_slots.items():
                    group = llm_ok[offset:offset + int(slots)]
                    offset += int(slots)
                    if group:
                        host_groups[host] = group
                if offset < len(llm_ok):
                    raise RuntimeError("batch has more states than available remote slots")

                for state in llm_ok:
                    logger.start(state.pid, attempt=attempt, step="校验")

                debug_by_pid: dict[str, dict] = {}
                with ThreadPoolExecutor(max_workers=len(host_groups)) as debug_executor:
                    future_to_host = {
                        debug_executor.submit(run_debug_batch, host, group, attempt=attempt): host
                        for host, group in host_groups.items()
                    }
                    for future in as_completed(future_to_host):
                        host = future_to_host[future]
                        try:
                            debug_by_pid.update(future.result())
                        except Exception as exc:
                            for state in host_groups[host]:
                                debug_by_pid[state.pid] = {
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

                verify_pass = 0
                verify_fail = 0
                for state in list(llm_ok):
                    debug = debug_by_pid.get(state.pid)
                    if debug is None:
                        debug = {
                            "status": "fail",
                            "stage": "remote",
                            "error_type": "remote_runner",
                            "message": "missing debug result",
                            "global_sf_n": state.context.get("global_sf_n"),
                            "baseline_time_ms": 0.0,
                            "optimized_time_ms": 0.0,
                            "speedup_ratio": 0.0,
                            "baseline_times_ms": [],
                            "optimized_times_ms": [],
                            "cases": [],
                        }
                    if str(debug.get("status", "")).strip() == "pass":
                        verify_pass += 1
                    else:
                        verify_fail += 1
                    should_stop = apply_debug_result(state, attempt=attempt, debug=debug)
                    if should_stop:
                        finish_row(build_final_row(state))
                        active.remove(state)
                    else:
                        state.next_attempt = attempt + 1
                logger.batch_step(f"round={attempt} 校验 完成 pass={verify_pass} fail={verify_fail}")

            for state in list(active):
                finish_row(build_final_row(state))
        finally:
            logger.close_batch()

    try:
        for start in range(0, len(pending), batch_size):
            batch_pids = pending[start:start + batch_size]
            try:
                process_batch(batch_pids)
            except Exception as exc:
                for pid in batch_pids:
                    if pid not in {str(row.get("pid", "")) for row in completed_rows}:
                        finish_row(build_unhandled_failure_row(pid, exc))
    finally:
        logger.close()
    _remote.close_remote_clients()
    print_failure_summary(completed_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
