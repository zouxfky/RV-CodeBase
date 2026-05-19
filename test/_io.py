import json
from pathlib import Path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_raw_log(
    log_dir: Path,
    pid: str,
    phase: str,
    attempt: int,
    text: str,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{pid}.{phase}.{attempt}.log"
    path.write_text(text, encoding="utf-8")
    return path


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
