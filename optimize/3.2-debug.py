import shlex
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import _bench
import _remote


def build_local_job_dir(*, tmp_dir: Path, pid: str, attempt: int) -> Path:
    safe_pid = _remote.safe_name(pid)
    return tmp_dir / safe_pid / f"round_{attempt}"


def build_local_static_dir(*, tmp_dir: Path, pid: str) -> Path:
    safe_pid = _remote.safe_name(pid)
    return tmp_dir / safe_pid / "static"


def write_remote_job_files(*, job_dir: Path, payload: dict) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "baseline.cpp").write_text(str(payload["baseline_source"]), encoding="utf-8")
    (job_dir / "optimized.cpp").write_text(str(payload["optimized_source"]), encoding="utf-8")

    case_lines: list[str] = []
    for case in payload.get("cases", []):
        testcase_index = int(case["testcase_index"])
        input_name = f"case_{testcase_index}.in"
        (job_dir / input_name).write_text(str(case["stdin"]), encoding="utf-8")
        case_lines.append(f"{testcase_index}\t{input_name}")
    (job_dir / "cases.tsv").write_text("\n".join(case_lines) + "\n", encoding="utf-8")

    config_lines = [
        f"PID={shlex.quote(str(payload['pid']))}",
        f"GLOBAL_SF_N={int(payload['global_sf_n'])}",
        f"COMPILE_CMD={shlex.quote(str(payload['compile_cmd']))}",
        f"COMPILE_TIMEOUT={int(payload['compile_timeout'])}",
        f"RUN_TIMEOUT={int(payload['run_timeout'])}",
        f"WALL_TIMEOUT={int(payload['wall_timeout'])}",
        f"FLOAT_TOLERANCE={float(payload.get('float_tolerance', 0.01))}",
        f"OUTPUT_LIMIT_BYTES={int(payload.get('output_limit_bytes', 10 * 1024 * 1024))}",
    ]
    (job_dir / "runner_config.sh").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    return job_dir / "runner_config.sh"


def write_remote_static_job_files(*, static_dir: Path, payload: dict) -> Path:
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "baseline.cpp").write_text(str(payload["baseline_source"]), encoding="utf-8")

    case_lines: list[str] = []
    for case in payload.get("cases", []):
        testcase_index = int(case["testcase_index"])
        input_name = f"case_{testcase_index}.in"
        (static_dir / input_name).write_text(str(case["stdin"]), encoding="utf-8")
        case_lines.append(f"{testcase_index}\t{input_name}")
    (static_dir / "cases.tsv").write_text("\n".join(case_lines) + "\n", encoding="utf-8")

    config_lines = [
        f"PID={shlex.quote(str(payload['pid']))}",
        f"GLOBAL_SF_N={int(payload['global_sf_n'])}",
        f"COMPILE_CMD={shlex.quote(str(payload['compile_cmd']))}",
        f"COMPILE_TIMEOUT={int(payload['compile_timeout'])}",
        f"RUN_TIMEOUT={int(payload['run_timeout'])}",
        f"WALL_TIMEOUT={int(payload['wall_timeout'])}",
        f"FLOAT_TOLERANCE={float(payload.get('float_tolerance', 0.01))}",
        f"OUTPUT_LIMIT_BYTES={int(payload.get('output_limit_bytes', 10 * 1024 * 1024))}",
    ]
    (static_dir / "runner_config.sh").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    return static_dir / "runner_config.sh"


def write_remote_optimized_file(*, job_dir: Path, optimized_code: str) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    optimized_path = job_dir / "optimized.cpp"
    optimized_path.write_text(str(optimized_code), encoding="utf-8")
    return optimized_path


def debug_candidate(
    *,
    pid: str,
    context: dict,
    optimized_code: str,
    attempt: int,
    host: str,
    remote_root: str,
    tmp_dir: Path,
    compile_cmd: str,
    compile_timeout: int,
    run_timeout: int,
    ssh_timeout: int,
    output_limit_bytes: int = 10 * 1024 * 1024,
) -> dict:
    job_dir = build_local_job_dir(tmp_dir=tmp_dir, pid=pid, attempt=attempt)
    payload = _bench.build_remote_job_payload(
        pid=pid,
        baseline_code=context["baseline_code"],
        optimized_code=optimized_code,
        main_program=context["main_program"],
        testcases=context["testcases"],
        global_sf_n=int(context["global_sf_n"]),
        compile_cmd=compile_cmd,
        compile_timeout=compile_timeout,
        run_timeout=run_timeout,
    )
    payload["wall_timeout"] = max(1, int(ssh_timeout) - 5)
    payload["output_limit_bytes"] = max(0, int(output_limit_bytes))
    write_remote_job_files(job_dir=job_dir, payload=payload)
    try:
        remote_result = _remote.run_remote_job(
            host=host,
            remote_root=remote_root,
            local_job_dir=job_dir,
            pid=pid,
            attempt=attempt,
            timeout=ssh_timeout,
        )
    except Exception as exc:
        return {
            "status": "fail",
            "stage": "remote",
            "error_type": "remote_exec",
            "message": str(exc),
            "global_sf_n": context.get("global_sf_n"),
            "baseline_time_ms": 0.0,
            "optimized_time_ms": 0.0,
            "speedup_ratio": 0.0,
            "baseline_times_ms": [],
            "optimized_times_ms": [],
            "cases": [],
        }
    return _bench.summarize_remote_result(remote_result)
