from datetime import datetime
from pathlib import Path
import re
import threading


_LOCK = threading.Lock()
_PID_LOGS: dict[str, dict] = {}
_PID_PATTERN = re.compile(r"\bpid=([^\s]+)")
_ENABLED = False


def set_log_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)


def bind_pid_log_path(pid: str, path: Path | str) -> Path:
    log_path = Path(path)
    if not _ENABLED:
        return log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        existing = _PID_LOGS.pop(pid, None)
        if existing is not None:
            try:
                existing["fh"].close()
            except Exception:
                pass
        fh = log_path.open("w", encoding="utf-8")
        _PID_LOGS[pid] = {
            "path": log_path,
            "fh": fh,
        }
    return log_path


def clear_pid_log_path(pid: str) -> None:
    if not _ENABLED:
        return
    with _LOCK:
        entry = _PID_LOGS.pop(pid, None)
        if entry is None:
            return
        try:
            entry["fh"].flush()
        finally:
            entry["fh"].close()


def debug_print(message: str) -> None:
    if not _ENABLED:
        return
    match = _PID_PATTERN.search(message)
    if match is None:
        return
    pid = match.group(1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message.rstrip()}\n"
    with _LOCK:
        entry = _PID_LOGS.get(pid)
        if entry is None:
            return
        fh = entry["fh"]
        fh.write(line)
        fh.flush()
