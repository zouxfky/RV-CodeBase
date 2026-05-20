from __future__ import annotations

import json
import re
from pathlib import Path


_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def safe_pid(pid: str) -> str:
    text = _SAFE_PATTERN.sub("__", str(pid).strip())
    return text or "empty_pid"


def session_path(*, session_dir: Path, pid: str) -> Path:
    return session_dir / f"{safe_pid(pid)}.json"


def write_session(
    *,
    session_dir: Path,
    pid: str,
    messages: list[dict],
    previous_candidates: list[dict] | None = None,
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_path(session_dir=session_dir, pid=pid)
    payload = {
        "pid": pid,
        "messages": messages,
        "previous_candidates": previous_candidates or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_session(*, session_dir: Path, pid: str) -> list[dict]:
    path = session_path(session_dir=session_dir, pid=pid)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return []
    return messages
