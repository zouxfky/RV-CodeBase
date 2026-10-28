"""In-place JSONL row store with stage-based resume and atomic flush.

Used by seed/1.2, seed/1.4 and workload/2.1-2.3 — every stage script reads the whole
table, processes pending rows, and periodically rewrites the file atomically.
A file lock guards against running two stages concurrently against the same
file.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def atomic_write_jsonl(path: Path, rows: list[dict]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"another process is already writing {path.name} "
                f"(lock file: {lock_path})"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


class JsonlStore:
    """Holds all rows of a JSONL file in memory, periodically flushes to disk.

    Concurrency model:
      - One process holds the OS-level file lock for the whole script run.
      - In-process writes from worker threads go through `update_row`, which
        is protected by an internal lock.
      - `flush_if_due` is called from the producer thread after each completed
        item; it rewrites the file atomically every `flush_every` updates.
    """

    def __init__(self, path: Path, flush_every: int = 50) -> None:
        self.path = path
        self.flush_every = max(1, flush_every)
        self._rows: list[dict] = read_jsonl(path)
        self._index: dict[str, int] = {}
        for i, row in enumerate(self._rows):
            pid = str(row.get("pid", "")).strip()
            if pid:
                self._index[pid] = i
        self._lock = Lock()
        self._dirty_count = 0

    def __len__(self) -> int:
        return len(self._rows)

    def rows(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._rows]

    def get(self, pid: str) -> dict | None:
        with self._lock:
            i = self._index.get(pid)
            if i is None:
                return None
            return dict(self._rows[i])

    def update_row(self, pid: str, patch: dict) -> None:
        with self._lock:
            i = self._index.get(pid)
            if i is None:
                raise KeyError(f"pid not found: {pid}")
            self._rows[i] = {**self._rows[i], **patch}
            self._dirty_count += 1

    def flush_if_due(self) -> bool:
        with self._lock:
            if self._dirty_count < self.flush_every:
                return False
            rows_snapshot = list(self._rows)
            self._dirty_count = 0
        atomic_write_jsonl(self.path, rows_snapshot)
        return True

    def flush(self) -> None:
        with self._lock:
            rows_snapshot = list(self._rows)
            self._dirty_count = 0
        atomic_write_jsonl(self.path, rows_snapshot)


__all__ = [
    "JsonlStore",
    "atomic_write_jsonl",
    "file_lock",
    "read_jsonl",
]
