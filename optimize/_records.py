from __future__ import annotations

import json
import random
import threading
from pathlib import Path

import _extensions


JSONL_LOCKS: dict[Path, threading.Lock] = {}
JSONL_LOCKS_GUARD = threading.Lock()
RANDOM_SHUFFLE_BUFFER_SIZE = 1024


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(iter_jsonl(path))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_pid_set(path: Path) -> set[str]:
    pids: set[str] = set()
    for row in iter_jsonl(path):
        pid = str(row.get("pid", "")).strip()
        if pid:
            pids.add(pid)
    return pids


def load_pid_map(path: Path) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for row in iter_jsonl(path):
        pid = str(row.get("pid", "")).strip()
        if pid:
            mapping[pid] = row
    return mapping


def get_jsonl_lock(path: Path) -> threading.Lock:
    key = path.resolve()
    with JSONL_LOCKS_GUARD:
        lock = JSONL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            JSONL_LOCKS[key] = lock
        return lock


def replace_jsonl_row(path: Path, *, pid: str, row: dict) -> None:
    lock = get_jsonl_lock(path)
    with lock:
        rows = read_jsonl(path)
        replaced = False
        for idx, current in enumerate(rows):
            if str(current.get("pid", "")).strip() == pid:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        write_jsonl(path, rows)


def iter_pending_pids(
    *,
    seed_path: Path,
    result_path: Path,
    limit: int | None,
    randomize: bool,
):
    completed_pids = load_pid_set(result_path)

    def iter_filtered():
        for row in iter_jsonl(seed_path):
            pid = str(row.get("pid", "")).strip()
            if pid and pid not in completed_pids:
                yield pid

    count = 0
    if not randomize:
        for pid in iter_filtered():
            if limit is not None and count >= max(0, limit):
                break
            count += 1
            yield pid
        return

    buffer: list[str] = []
    for pid in iter_filtered():
        buffer.append(pid)
        if len(buffer) >= RANDOM_SHUFFLE_BUFFER_SIZE:
            random.shuffle(buffer)
            while buffer:
                if limit is not None and count >= max(0, limit):
                    return
                count += 1
                yield buffer.pop()
    if buffer:
        random.shuffle(buffer)
        while buffer:
            if limit is not None and count >= max(0, limit):
                return
            count += 1
            yield buffer.pop()


def load_optimize_context(
    *,
    pid: str,
    seed_path: Path,
    output_path: Path,
    testcase_path: Path,
) -> dict:
    seed_row = load_pid_map(seed_path).get(pid)
    output_row = load_pid_map(output_path).get(pid)
    testcase_row = load_pid_map(testcase_path).get(pid)
    return build_optimize_context_from_rows(
        pid=pid,
        seed_row=seed_row,
        output_row=output_row,
        testcase_row=testcase_row,
    )


def build_optimize_context_from_rows(
    *,
    pid: str,
    seed_row: dict | None,
    output_row: dict | None,
    testcase_row: dict | None,
) -> dict:
    if seed_row is None:
        raise ValueError(f"missing seed row for pid={pid}")
    if output_row is None:
        raise ValueError(f"missing output row for pid={pid}")
    if testcase_row is None:
        raise ValueError(f"missing testcase row for pid={pid}")
    if str(output_row.get("status", "")).strip() != "success":
        raise ValueError(f"output row is not successful for pid={pid}")

    baseline_code = str(seed_row.get("code", ""))
    main_program = str(testcase_row.get("program", ""))
    testcases = testcase_row.get("testcase", [])
    if not baseline_code.strip():
        raise ValueError(f"missing baseline code for pid={pid}")
    if not main_program.strip():
        raise ValueError(f"missing main program for pid={pid}")
    if not isinstance(testcases, list) or not testcases:
        raise ValueError(f"missing testcase list for pid={pid}")
    try:
        global_sf_n = int(output_row.get("global_sf_n"))
    except Exception as exc:
        raise ValueError(f"invalid global_sf_n for pid={pid}") from exc
    global_sf_n = max(1, global_sf_n // 5)
    extension = _extensions.check_extension(seed_row.get("extension", ""))

    return {
        "pid": pid,
        "extension": extension,
        "baseline_code": baseline_code,
        "output_row": output_row,
        "main_program": main_program,
        "testcases": testcases,
        "global_sf_n": global_sf_n,
    }


def build_result_row(
    *,
    pid: str,
    status: str,
    stage: str,
    round: int,
    best: int,
    speedup: float,
    baseline: float,
    optimized: float,
    sf: int,
    code: str,
    message: str,
    history: list[dict],
    extension: str = "",
) -> dict:
    return {
        "pid": pid,
        "extension": extension,
        "status": status,
        "stage": stage,
        "round": round,
        "best": best,
        "speedup": speedup,
        "baseline": baseline,
        "optimized": optimized,
        "sf": sf,
        "code": code,
        "message": message,
        "history": history,
    }

def build_failure_row(
    *,
    pid: str,
    rounds: int,
    stage: str,
    error_type: str,
    message: str,
    code: str = "",
    debug_row: dict | None = None,
) -> dict:
    return build_result_row(
        pid=pid,
        status="fail",
        stage=stage,
        round=rounds,
        best=0,
        speedup=0.0,
        baseline=0.0,
        optimized=0.0,
        sf=0,
        code=code,
        message=message,
        history=[
            {
                "round": rounds,
                "status": "fail",
                "speedup": 0.0,
                "baseline": 0.0,
                "optimized": 0.0,
                "message": f"{stage}: {message}" if stage else message,
            }
        ] if rounds else [],
    )
