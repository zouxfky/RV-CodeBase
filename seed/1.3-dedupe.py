import json
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
MERGE_PATH = DATA_DIR / "merge.jsonl"
COMPLETED_PATH = DATA_DIR / "match.jsonl"
OUTPUT_PATH = DATA_DIR / "merge_dedupe.jsonl"


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x: str) -> str:
        parent = self.parent[x]
        if parent != x:
            self.parent[x] = self.find(parent)
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        self.add(a)
        self.add(b)
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def score_row(row: dict) -> tuple[int, int, str]:
    pid = str(row.get("pid", "")).strip()
    quertion_len = len(str(row.get("quertion", "")).strip())
    solution_len = len(str(row.get("solution", "")).strip())
    return (quertion_len, solution_len, pid)


def main() -> int:
    rows = read_jsonl(MERGE_PATH)
    rows_by_pid = {
        str(row.get("pid", "")).strip(): row
        for row in rows
        if str(row.get("pid", "")).strip()
    }
    alive_pids = set(rows_by_pid.keys())

    uf = UnionFind()
    for pid in alive_pids:
        uf.add(pid)

    true_edge_count = 0
    if COMPLETED_PATH.exists():
        for item in read_jsonl(COMPLETED_PATH):
            source_pid = str(item.get("source_pid", "")).strip()
            if source_pid not in alive_pids:
                continue
            for target in item.get("target", []):
                if target.get("result") is not True:
                    continue
                target_pid = str(target.get("pid", "")).strip()
                if target_pid not in alive_pids or target_pid == source_pid:
                    continue
                uf.union(source_pid, target_pid)
                true_edge_count += 1

    components: dict[str, set[str]] = {}
    for pid in alive_pids:
        root = uf.find(pid)
        components.setdefault(root, set()).add(pid)

    delete_pids: set[str] = set()
    duplicate_groups = 0
    for component in components.values():
        if len(component) <= 1:
            continue
        duplicate_groups += 1
        keep_pid = max(component, key=lambda pid: score_row(rows_by_pid[pid]))
        for pid in component:
            if pid != keep_pid:
                delete_pids.add(pid)

    kept_rows = [
        row for row in rows
        if str(row.get("pid", "")).strip() not in delete_pids
    ]

    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"input_rows={len(rows)}")
    print(f"true_edges={true_edge_count}")
    print(f"duplicate_groups={duplicate_groups}")
    print(f"deleted_rows={len(delete_pids)}")
    print(f"output_rows={len(kept_rows)}")
    print(f"output_path={OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
