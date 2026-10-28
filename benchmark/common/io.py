import json
from pathlib import Path


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def write_jsonl(path, rows):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path, row):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()


def write_json(path, value):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def method_paths(suite_dir, method, ext):
    """<suite>/baseline/<method>/<ext>.jsonl (code), <suite>/results/<method>/<ext>.jsonl (metrics)."""
    suite_dir = Path(suite_dir)
    return (suite_dir / "baseline" / method / f"{ext}.jsonl",
            suite_dir / "results" / method / f"{ext}.jsonl")


def export_run(work_path, code_path, result_path, extension):
    """Split a runner's work file into the code file and the result file, merging by id."""
    def merge(path, new):
        old = {r["id"]: r for r in read_jsonl(path)} if Path(path).exists() else {}
        old.update({r["id"]: r for r in new})
        write_jsonl(path, sorted(old.values(), key=lambda r: str(r["id"])))

    rows = read_jsonl(work_path) if Path(work_path).exists() else []
    if code_path is not None:
        merge(code_path, [{"id": r["id"], "extension": extension, "code": r["code"]} for r in rows if r.get("code")])
    merge(result_path, [{k: v for k, v in r.items() if k != "code"} for r in rows])


def load_run(code_path, result_path):
    """Result rows with `code` filled in from the code file."""
    code = {r["id"]: r["code"] for r in read_jsonl(code_path)} if Path(code_path).exists() else {}
    return [dict(r, code=code.get(r["id"], "")) for r in read_jsonl(result_path)]
