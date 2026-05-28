import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _jsonl_store import atomic_write_jsonl, read_jsonl


SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
COLLECTED_PATH = DATA_DIR / "collected_seeds.jsonl"
OUTPUT_PATH = DATA_DIR / "seed.jsonl"


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


def score_row(row: dict) -> tuple[int, int, str]:
    pid = str(row.get("pid", "")).strip()
    quertion_len = len(str(row.get("quertion", "")).strip())
    solution_len = len(str(row.get("solution", "")).strip())
    return (quertion_len, solution_len, pid)


def main() -> int:
    rows = read_jsonl(COLLECTED_PATH)
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
    rows_with_match = 0
    for row in rows:
        source_pid = str(row.get("pid", "")).strip()
        if source_pid not in alive_pids:
            continue
        match = row.get("match")
        if not isinstance(match, dict):
            continue
        rows_with_match += 1
        for target in match.get("target", []) or []:
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

    kept_rows: list[dict] = []
    for row in rows:
        pid = str(row.get("pid", "")).strip()
        if not pid or pid in delete_pids:
            continue
        new_row = {k: v for k, v in row.items() if k != "match"}
        new_row["stage"] = "deduped"
        kept_rows.append(new_row)

    atomic_write_jsonl(OUTPUT_PATH, kept_rows)

    print(f"input_rows={len(rows)}")
    print(f"rows_with_match={rows_with_match}")
    print(f"true_edges={true_edge_count}")
    print(f"duplicate_groups={duplicate_groups}")
    print(f"deleted_rows={len(delete_pids)}")
    print(f"output_rows={len(kept_rows)}")
    print(f"output_path={OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
