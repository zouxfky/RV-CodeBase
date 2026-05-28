import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from tqdm import tqdm
except ModuleNotFoundError as exc:
    raise SystemExit(
        "missing dependency: tqdm\n"
        "install it with: python3 -m pip install tqdm"
    ) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _jsonl_store import JsonlStore, file_lock


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SEED_PATH = ROOT_DIR / "data" / "seed.jsonl"
DEFAULT_TMP_DIR = ROOT_DIR / "tmp" / "verify"
CODE_BLOCK_PATTERN = re.compile(r"^```[^\n]*\n(?P<code>.*)\n```$", re.DOTALL)
PID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
SOLVE_PATTERN = re.compile(r"\bvoid\s+solve\s*\(")
MAIN_PATTERN = re.compile(r"\b(?:int|auto|void|signed\s+int)\s+main\s*\(")

PENDING_STAGES = {"transformed", "repaired"}


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
        description="Compile-check transformed C++ code in seed.jsonl in place."
    )
    parser.add_argument(
        "--seed",
        dest="seed_path",
        default=str(DEFAULT_SEED_PATH),
        help="path to seed.jsonl (in-place updated)",
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
    return parser.parse_args()


def extract_code_block(text: str) -> str:
    text = text.strip()
    match = CODE_BLOCK_PATTERN.match(text)
    if match:
        return match.group("code")
    return text


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


def build_verify(status: str, error_type: str, message: str) -> dict[str, str]:
    return {"status": status, "error_type": error_type, "message": message}


def compile_one(
    line_no: int,
    row: dict,
    src_dir: Path,
    obj_dir: Path,
    compiler: str,
    cpp_std: str,
    timeout: int,
) -> tuple[str, dict[str, str]]:
    pid = str(row.get("pid", "")).strip() or f"line_{line_no}"
    candidate = str(row.get("code", ""))
    code = extract_code_block(candidate)

    if not code.strip() or candidate.strip() == "ERROR":
        return pid, build_verify(
            "fail", "format", "failed format checks: code_empty"
        )

    failed_checks, _ = evaluate_format(code)
    if failed_checks:
        return pid, build_verify(
            "fail", "format", "failed format checks: " + ", ".join(failed_checks)
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
        return pid, build_verify(
            "fail",
            "compile",
            "\n".join(part.rstrip() for part in message_parts if part).strip(),
        )
    except Exception as exc:
        return pid, build_verify("fail", "compile", str(exc))

    if completed.returncode == 0:
        return pid, build_verify("pass", "", "")

    message = (completed.stderr or completed.stdout or "").strip()
    if not message:
        message = f"compiler exited with code {completed.returncode}"
    return pid, build_verify("fail", "compile", message)


def main() -> int:
    args = parse_args()
    seed_path = Path(args.seed_path)
    tmp_dir = Path(args.tmp_dir)
    src_dir = tmp_dir / "src"
    obj_dir = tmp_dir / "obj"

    if not seed_path.exists():
        raise FileNotFoundError(f"seed file not found: {seed_path}")

    src_dir.mkdir(parents=True, exist_ok=True)
    obj_dir.mkdir(parents=True, exist_ok=True)

    with file_lock(seed_path):
        store = JsonlStore(seed_path, flush_every=50)
        all_rows = store.rows()
        pending: list[tuple[int, dict]] = []
        for line_no, row in enumerate(all_rows, start=1):
            pid = str(row.get("pid", "")).strip()
            if not pid:
                continue
            stage = str(row.get("stage", "")).strip()
            if stage not in PENDING_STAGES:
                continue
            pending.append((line_no, row))

        if args.limit > 0:
            pending = pending[: args.limit]

        if not pending:
            print("no pending rows")
            return 0

        pass_count = 0
        fail_count = 0

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
                    pid, verify = future.result()
                    new_stage = "verified_pass" if verify["status"] == "pass" else "verified_fail"
                    store.update_row(pid, {"verify": verify, "stage": new_stage})

                    if verify["status"] == "pass":
                        pass_count += 1
                    else:
                        fail_count += 1

                    pbar.set_postfix(pass_count=pass_count, fail_count=fail_count)
                    pbar.update(1)
                    store.flush_if_due()

        store.flush()

    print("done")
    print(f"new_pass={pass_count}")
    print(f"new_fail={fail_count}")
    print(f"total_written={pass_count + fail_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
