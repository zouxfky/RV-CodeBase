import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import importlib.util
import itertools
import json
import random
import subprocess
import sys
from pathlib import Path
import threading
from tqdm import tqdm


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))


def load_script_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IO_API = load_script_module("test_io_api_codex", CURRENT_DIR / "_io.py")

iter_jsonl = IO_API.iter_jsonl
load_pid_set = IO_API.load_pid_set
read_jsonl = IO_API.read_jsonl
write_jsonl = IO_API.write_jsonl


ROOT_DIR = CURRENT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
TMP_DIR = ROOT_DIR / "tmp"
PROMPTS_DIR = ROOT_DIR / "prompts"

DEFAULT_INPUT_PATH = DATA_DIR / "seed.jsonl"
DEFAULT_SEED_OUTPUT_PATH = DATA_DIR / "seed2.jsonl"
DEFAULT_TESTCASE_OUTPUT_PATH = DATA_DIR / "testcase2.jsonl"
DEFAULT_RESULT_PATH = DATA_DIR / "output2.jsonl"
DEFAULT_PROMPT_PATH = PROMPTS_DIR / "2-codex-sf-scale.md"
DEFAULT_TMP_DIR = TMP_DIR / "codex_sf_exec"
RANDOM_SHUFFLE_BUFFER_SIZE = 1024
MAX_WORKERS = 32
JSONL_LOCKS: dict[Path, threading.Lock] = {}
JSONL_LOCKS_GUARD = threading.Lock()


def load_prompt_text(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"missing prompt file: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"empty prompt file: {path}")
    return text


def render_prompt(template: str, **kwargs: str) -> str:
    rendered = template
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR.resolve()))
    except Exception:
        return str(path)


def iter_pending_rows(
    input_path: Path,
    *,
    completed_pids: set[str],
    randomize: bool,
):
    def iter_filtered():
        for row in iter_jsonl(input_path):
            pid = str(row.get("pid", "")).strip()
            if pid and pid not in completed_pids:
                yield row

    if not randomize:
        yield from iter_filtered()
        return

    buffer: list[dict] = []
    for row in iter_filtered():
        buffer.append(row)
        if len(buffer) >= RANDOM_SHUFFLE_BUFFER_SIZE:
            random.shuffle(buffer)
            while buffer:
                yield buffer.pop()
    if buffer:
        random.shuffle(buffer)
        while buffer:
            yield buffer.pop()


def count_pending_rows(
    input_path: Path,
    *,
    completed_pids: set[str],
    limit: int | None,
    randomize: bool,
) -> int:
    count = 0
    for _ in iter_pending_rows(
        input_path,
        completed_pids=completed_pids,
        randomize=randomize,
    ):
        count += 1
        if limit is not None and count >= max(0, limit):
            break
    return count


def build_exec_failure_row(*, pid: str, message: str) -> dict:
    return {
        "pid": pid,
        "status": "fail",
        "stage": "sf_scale",
        "error_type": "exec",
        "message": message,
        "program_rounds": 0,
        "testcase_rounds": 0,
        "global_sf_n": None,
        "pass_count": None,
        "fail_count": None,
        "results": [],
    }


def build_tmp_paths(*, pid: str, tmp_dir: Path) -> dict[str, Path]:
    return {
        "seed": tmp_dir / f"{pid}.seed.json",
        "output": tmp_dir / f"{pid}.output.json",
        "testcase": tmp_dir / f"{pid}.testcase.json",
        "last": tmp_dir / f"{pid}.last.txt",
    }


def read_single_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def get_jsonl_lock(path: Path) -> threading.Lock:
    key = path.resolve()
    with JSONL_LOCKS_GUARD:
        lock = JSONL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            JSONL_LOCKS[key] = lock
        return lock


def replace_jsonl_row(path: Path, *, pid: str, row: dict) -> None:
    lock = get_jsonl_lock(path)
    with lock:
        rows = read_jsonl(path)
        replaced = False
        for idx, current in enumerate(rows):
            current_pid = str(current.get("pid", "")).strip()
            if current_pid == pid:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        write_jsonl(path, rows)


def merge_pid_outputs(
    *,
    pid: str,
    seed_output_path: Path,
    testcase_output_path: Path,
    result_output_path: Path,
    tmp_paths: dict[str, Path],
    exec_message: str,
) -> dict:
    if not tmp_paths["output"].exists():
        result_row = build_exec_failure_row(pid=pid, message=exec_message)
        replace_jsonl_row(result_output_path, pid=pid, row=result_row)
        return result_row

    result_row = read_single_json(tmp_paths["output"])
    if str(result_row.get("pid", "")).strip() != pid:
        raise ValueError(f"result pid mismatch for {pid}")
    replace_jsonl_row(result_output_path, pid=pid, row=result_row)

    if tmp_paths["seed"].exists():
        seed_row = read_single_json(tmp_paths["seed"])
        if str(seed_row.get("pid", "")).strip() != pid:
            raise ValueError(f"seed pid mismatch for {pid}")
        replace_jsonl_row(seed_output_path, pid=pid, row=seed_row)
    elif str(result_row.get("status", "")).strip() == "success":
        raise ValueError(f"missing seed tmp output for successful pid {pid}")

    if str(result_row.get("status", "")).strip() == "success":
        if not tmp_paths["testcase"].exists():
            raise ValueError(f"missing testcase tmp output for successful pid {pid}")
        testcase_row = read_single_json(tmp_paths["testcase"])
        if str(testcase_row.get("pid", "")).strip() != pid:
            raise ValueError(f"testcase pid mismatch for {pid}")
        replace_jsonl_row(testcase_output_path, pid=pid, row=testcase_row)

    return result_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--seed-output", default=str(DEFAULT_SEED_OUTPUT_PATH))
    parser.add_argument(
        "--testcase-output",
        "--output",
        dest="testcase_output",
        default=str(DEFAULT_TESTCASE_OUTPUT_PATH),
    )
    parser.add_argument("--result-output", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT_PATH))
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--tmp-dir", default=str(DEFAULT_TMP_DIR))
    parser.add_argument("--random", action="store_true")
    parser.add_argument("-n", type=int, default=None)
    parser.add_argument("-j", type=int, default=1)
    return parser.parse_args()


def run_codex_once(
    *,
    pid: str,
    prompt_text: str,
    args: argparse.Namespace,
) -> tuple[int, str]:
    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_paths = build_tmp_paths(pid=pid, tmp_dir=tmp_dir)
    for path in tmp_paths.values():
        if path.exists():
            path.unlink()

    cmd = [
        args.codex_bin,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-C",
        str(ROOT_DIR),
        "-o",
        str(tmp_paths["last"]),
    ]
    if args.model.strip():
        cmd.extend(["-m", args.model.strip()])

    completed = subprocess.run(
        cmd,
        input=prompt_text,
        text=True,
        timeout=args.timeout,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    last_message = ""
    if tmp_paths["last"].exists():
        last_message = tmp_paths["last"].read_text(encoding="utf-8").strip()
    stderr_text = (completed.stderr or "").strip()
    message = (
        last_message
        or stderr_text
        or f"codex exec exited with code {completed.returncode}"
    )
    return completed.returncode, message


def process_one_pid(
    *,
    row: dict,
    prompt_template: str,
    args: argparse.Namespace,
) -> dict:
    pid = str(row.get("pid", "")).strip()
    prompt_text = render_prompt(
        prompt_template,
        pid=pid,
        input_path=display_path(Path(args.input)),
        seed_output_path=display_path(Path(args.seed_output)),
        testcase_output_path=display_path(Path(args.testcase_output)),
        result_output_path=display_path(Path(args.result_output)),
        tmp_dir=display_path(Path(args.tmp_dir)),
    )
    exec_message = ""
    try:
        _, exec_message = run_codex_once(
            pid=pid,
            prompt_text=prompt_text,
            args=args,
        )
    except subprocess.TimeoutExpired:
        exec_message = f"codex exec timeout after {args.timeout}s"
    return {
        "pid": pid,
        "exec_message": exec_message,
        "tmp_paths": build_tmp_paths(pid=pid, tmp_dir=Path(args.tmp_dir)),
    }


def main() -> int:
    args = parse_args()
    args.j = max(1, int(args.j))

    input_path = Path(args.input)
    seed_output_path = Path(args.seed_output)
    testcase_output_path = Path(args.testcase_output)
    result_output_path = Path(args.result_output)
    prompt_path = Path(args.prompt)

    prompt_template = load_prompt_text(prompt_path)

    completed_pids = load_pid_set(result_output_path)
    pending_total = count_pending_rows(
        input_path,
        completed_pids=completed_pids,
        limit=args.n,
        randomize=args.random,
    )
    if pending_total <= 0:
        return 0

    pending_iter = iter_pending_rows(
        input_path,
        completed_pids=completed_pids,
        randomize=args.random,
    )
    if args.n is not None:
        pending_iter = itertools.islice(pending_iter, max(0, args.n))

    worker_j = max(1, min(MAX_WORKERS, pending_total, args.j))
    pass_count = 0
    fail_count = 0
    with ThreadPoolExecutor(max_workers=worker_j) as executor:
        future_set: set = set()
        future_pid_map: dict = {}

        def submit_next() -> bool:
            try:
                row = next(pending_iter)
            except StopIteration:
                return False
            pid = str(row.get("pid", "")).strip()
            future = executor.submit(
                process_one_pid,
                row=row,
                prompt_template=prompt_template,
                args=args,
            )
            future_set.add(future)
            future_pid_map[future] = pid
            return True

        for _ in range(worker_j):
            if not submit_next():
                break

        with tqdm(total=pending_total, desc="pid", unit="pid") as progress:
            progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
            while future_set:
                done, _ = wait(future_set, return_when=FIRST_COMPLETED)
                for future in done:
                    future_set.remove(future)
                    pid = future_pid_map.pop(future, "") or "<unknown>"
                    try:
                        item = future.result()
                        pid = str(item.get("pid", "")).strip()
                        result_row = merge_pid_outputs(
                            pid=pid,
                            seed_output_path=seed_output_path,
                            testcase_output_path=testcase_output_path,
                            result_output_path=result_output_path,
                            tmp_paths=item["tmp_paths"],
                            exec_message=str(item.get("exec_message", "")).strip(),
                        )
                    except Exception as exc:
                        result_row = build_exec_failure_row(
                            pid=pid,
                            message=f"codex merge failed: {exc}",
                        )
                        if pid != "<unknown>":
                            replace_jsonl_row(result_output_path, pid=pid, row=result_row)
                    if str(result_row.get("status", "")).strip() == "success":
                        pass_count += 1
                    else:
                        fail_count += 1
                    completed_pids.add(pid)
                    progress.set_postfix(pass_count=pass_count, fail_count=fail_count)
                    progress.update(1)
                    submit_next()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
