import json
import re
from pathlib import Path


_SAFE_PID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_pid(pid: str) -> str:
    text = _SAFE_PID_PATTERN.sub("__", str(pid).strip())
    return text or "empty_pid"


def session_path(session_dir: Path, pid: str) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / f"{_safe_pid(pid)}.json"


def write_session(
    *,
    session_dir: Path,
    pid: str,
    session_name: str,
    messages: list[dict],
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    safe_session_name = _SAFE_PID_PATTERN.sub("__", str(session_name).strip()) or "session"
    path = session_dir / f"{_safe_pid(pid)}.{safe_session_name}.json"
    payload = {
        "pid": pid,
        "session": session_name,
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
