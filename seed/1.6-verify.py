import argparse
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from tqdm import tqdm
except ModuleNotFoundError as exc:
    raise SystemExit(
        "missing dependency: tqdm\n"
        "install it with: python3 -m pip install tqdm"
    ) from exc


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = ROOT_DIR / "data" / "merge_dedupe_classify_transform.jsonl"
DEFAULT_REPAIR_INPUT_PATH = ROOT_DIR / "data" / "merge_dedupe_classify_transform_repair.jsonl"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "verify.jsonl"
DEFAULT_TMP_DIR = ROOT_DIR / "tmp" / "verify"
CODE_BLOCK_PATTERN = re.compile(r"^```[^\n]*\n(?P<code>.*)\n```$", re.DOTALL)
PID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
SOLVE_PATTERN = re.compile(r"\bvoid\s+solve\s*\(")
MAIN_PATTERN = re.compile(r"\b(?:int|auto|void|signed\s+int)\s+main\s*\(")


def detect_default_compiler() -> str:
    candidates = [
        "g++-15",
        "g++-14",
        "g++-13",
        "g++-12",
        "g++-11",
        "g++-10",
        "g++",
    ]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "g++"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile-check transformed C++ code from a JSONL file."
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        default=str(DEFAULT_INPUT_PATH),
        help="path to the JSONL file to compile-check",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="path to verify.jsonl output",
    )
    parser.add_argument(
        "--tmp-dir",
        default=str(DEFAULT_TMP_DIR),
        help="directory for temporary source/object files",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=max(1, os.cpu_count() or 1),
        help="number of parallel compile jobs",
    )
    parser.add_argument(
        "--compiler",
        default=detect_default_compiler(),
        help="C++ compiler executable",
    )
    parser.add_argument(
        "--std",
        default="c++17",
        help="C++ standard passed to the compiler",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="timeout in seconds for each compile task",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="only verify the first N pending rows; 0 means no limit",
    )
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="use repair jsonl as input, drop failed records from verify.jsonl before resuming, and remove failed pids from repair jsonl after verification",
    )
    return parser.parse_args()


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            yield line_no, json.loads(line)


def load_verified_pids(path: Path) -> set[str]:
    if not path.exists():
        return set()

    verified: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            pid = str(row.get("pid", "")).strip()
            if pid:
                verified.add(pid)
    return verified


def prune_failed_results(path: Path) -> None:
    if not path.exists():
        return

    kept_rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("status", "")).strip() == "pass":
                kept_rows.append(row)

    with path.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def prune_repair_rows_by_failed_pids(repair_path: Path, verify_path: Path) -> None:
    if not repair_path.exists() or not verify_path.exists():
        return

    failed_pids: set[str] = set()
    with verify_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("status", "")).strip() != "fail":
                continue
            pid = str(row.get("pid", "")).strip()
            if pid:
                failed_pids.add(pid)

    if not failed_pids:
        return

    kept_rows: list[dict] = []
    with repair_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            pid = str(row.get("pid", "")).strip()
            if pid in failed_pids:
                continue
            kept_rows.append(row)

    with repair_path.open("w", encoding="utf-8") as fh:
        for row in kept_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_code(transform: str) -> str:
    text = transform.strip()
    match = CODE_BLOCK_PATTERN.match(text)
    if match:
        return match.group("code")
    return transform


def get_candidate_code(row: dict) -> str:
    repair = str(row.get("repair", "")).strip()
    if repair:
        return str(row.get("repair", ""))
    return str(row.get("transform", ""))


def sanitize_pid(pid: str) -> str:
    safe = PID_SAFE_PATTERN.sub("_", pid).strip("._")
    return safe or "unknown_pid"


def evaluate_format(code: str) -> tuple[list[str], int]:
    solve_count = len(SOLVE_PATTERN.findall(code))
    failed_checks: list[str] = []
    if solve_count != 1:
        failed_checks.append("single_void_solve")
    if "Global_SF_N" not in code:
        failed_checks.append("has_global_sf_n")
    if "Global_Result" not in code:
        failed_checks.append("has_global_result")
    if MAIN_PATTERN.search(code):
        failed_checks.append("main_removed")
    return failed_checks, solve_count


def build_result(
    pid: str,
    status: str,
    error_type: str,
    message: str,
) -> dict[str, str]:
    return {
        "pid": pid,
        "status": status,
        "error_type": error_type,
        "message": message,
    }


def compile_one(
    line_no: int,
    row: dict,
    src_dir: Path,
    obj_dir: Path,
    compiler: str,
    cpp_std: str,
    timeout: int,
) -> dict[str, str]:
    pid = str(row.get("pid", "")).strip() or f"line_{line_no}"
    candidate = get_candidate_code(row)
    code = extract_code(candidate)

    if not code.strip() or candidate.strip() == "ERROR":
        return build_result(
            pid=pid,
            status="fail",
            error_type="format",
            message="failed format checks: transform_empty",
        )

    failed_checks, _ = evaluate_format(code)
    if failed_checks:
        return build_result(
            pid=pid,
            status="fail",
            error_type="format",
            message="failed format checks: " + ", ".join(failed_checks),
        )

    safe_pid = sanitize_pid(pid)
    src_path = src_dir / f"{line_no:06d}_{safe_pid}.cpp"
    obj_path = obj_dir / f"{line_no:06d}_{safe_pid}.o"
    src_path.write_text(code, encoding="utf-8")

    cmd = [
        compiler,
        "-std=" + cpp_std,
        "-O2",
        "-pipe",
        "-c",
        str(src_path),
        "-o",
        str(obj_path),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        message_parts = []
        if exc.stdout:
            message_parts.append(exc.stdout)
        if exc.stderr:
            message_parts.append(exc.stderr)
        message_parts.append(f"compile timeout after {timeout}s")
        return build_result(
            pid=pid,
            status="fail",
            error_type="compile",
            message="\n".join(part.rstrip() for part in message_parts if part).strip(),
        )
    except Exception as exc:
        return build_result(
            pid=pid,
            status="fail",
            error_type="compile",
            message=str(exc),
        )

    if completed.returncode == 0:
        return build_result(
            pid=pid,
            status="pass",
            error_type="",
            message="",
        )

    message = (completed.stderr or completed.stdout or "").strip()
    if not message:
        message = f"compiler exited with code {completed.returncode}"
    return build_result(
        pid=pid,
        status="fail",
        error_type="compile",
        message=message,
    )


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_path)
    if args.repeat:
        input_path = DEFAULT_REPAIR_INPUT_PATH
    output_path = Path(args.output)
    tmp_dir = Path(args.tmp_dir)
    src_dir = tmp_dir / "src"
    obj_dir = tmp_dir / "obj"

    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    obj_dir.mkdir(parents=True, exist_ok=True)

    if args.repeat:
        prune_failed_results(output_path)

    verified_pids = load_verified_pids(output_path)
    pending: list[tuple[int, dict]] = []
    total_rows = 0

    for line_no, row in iter_jsonl(input_path):
        total_rows += 1
        pid = str(row.get("pid", "")).strip()
        if pid in verified_pids:
            continue
        pending.append((line_no, row))

    if args.limit > 0:
        pending = pending[: args.limit]

    if not pending:
        return 0

    pass_count = 0
    fail_count = 0

    with output_path.open("a", encoding="utf-8") as out_fh:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
            future_map = {
                executor.submit(
                    compile_one,
                    line_no,
                    row,
                    src_dir,
                    obj_dir,
                    args.compiler,
                    args.std,
                    args.timeout,
                ): (line_no, row)
                for line_no, row in pending
            }

            with tqdm(total=len(pending), desc="compile", unit="file") as pbar:
                for future in as_completed(future_map):
                    result = future.result()
                    out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_fh.flush()

                    if result["status"] == "pass":
                        pass_count += 1
                    else:
                        fail_count += 1

                    pbar.set_postfix(pass_count=pass_count, fail_count=fail_count)
                    pbar.update(1)

    print("done")
    print(f"new_pass={pass_count}")
    print(f"new_fail={fail_count}")
    print(f"total_written={pass_count + fail_count}")

    if args.repeat:
        prune_repair_rows_by_failed_pids(DEFAULT_REPAIR_INPUT_PATH, output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
