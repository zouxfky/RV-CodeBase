import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
REMOTE_RUNNER_PATH = CURRENT_DIR / "_remote.sh"
_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str) -> str:
    text = _SAFE_PATTERN.sub("__", str(value).strip())
    return text or "empty"


def run_command(cmd: list[str], *, timeout: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def validate_remote_root(remote_root: str) -> str:
    root = str(remote_root).rstrip("/")
    if not root.startswith("/tmp/"):
        raise ValueError("remote_root must be under /tmp")
    return root


def remote_job_name(*, pid: str, attempt: int) -> str:
    return f"{safe_name(pid)}.round_{attempt}.{int(time.time() * 1000)}"


def scp_dir_to_remote(
    *,
    host: str,
    local_dir: Path,
    remote_parent_dir: str,
    timeout: int,
    ssh_password: str = "",
) -> None:
    if not local_dir.is_dir():
        raise ValueError(f"local job dir does not exist: {local_dir}")
    cmd = ["scp", "-r", str(local_dir), f"{host}:{remote_parent_dir}/"]
    if ssh_password:
        cmd = ["sshpass", "-p", ssh_password] + cmd
    returncode, stdout, stderr = run_command(
        cmd,
        timeout=timeout,
    )
    if returncode != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or f"scp upload failed: {local_dir}")


def run_remote_job(
    *,
    host: str,
    remote_root: str,
    local_job_dir: Path,
    pid: str,
    attempt: int,
    timeout: int,
    ssh_password: str = "",
) -> dict:
    if not REMOTE_RUNNER_PATH.exists():
        raise ValueError(f"missing remote runner: {REMOTE_RUNNER_PATH}")

    local_job_dir.mkdir(parents=True, exist_ok=True)
    local_runner = local_job_dir / "_remote.sh"
    shutil.copy2(REMOTE_RUNNER_PATH, local_runner)

    stable_name = remote_job_name(pid=pid, attempt=attempt)
    upload_dir = local_job_dir.parent / stable_name
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    shutil.copytree(local_job_dir, upload_dir)

    root = validate_remote_root(remote_root)
    remote_stage_dir = f"/tmp/{stable_name}"
    remote_dir = f"{root}/{stable_name}"
    try:
        scp_dir_to_remote(
            host=host,
            local_dir=upload_dir,
            remote_parent_dir="/tmp",
            timeout=timeout,
            ssh_password=ssh_password,
        )
        if remote_stage_dir == remote_dir:
            move_command = ""
            cleanup_command = f"rm -rf {shlex.quote(remote_dir)}"
        else:
            move_command = (
                f"mkdir -p {shlex.quote(root)}; "
                f"rm -rf {shlex.quote(remote_dir)}; "
                f"mv {shlex.quote(remote_stage_dir)} {shlex.quote(remote_dir)}; "
            )
            cleanup_command = (
                f"rm -rf {shlex.quote(remote_dir)}; "
                f"rm -rf {shlex.quote(remote_stage_dir)}"
            )
        remote_command = (
            "set -u; "
            + move_command
            + f"cd {shlex.quote(remote_dir)}; "
            "chmod +x _remote.sh; "
            "rc=0; "
            "./_remote.sh result.json || rc=$?; "
            "if [ ! -f result.json ]; then "
            + "printf "
            + shlex.quote(
                '{"pid":"%s","status":"fail","stage":"remote","error_type":"remote_runner","message":"remote runner exited without result.json","global_sf_n":null,"baseline_time_ms":0.0,"optimized_time_ms":0.0,"speedup_ratio":0.0,"baseline_times_ms":[],"optimized_times_ms":[],"cases":[]}\n'
            )
            + " "
            + shlex.quote(pid)
            + " > result.json; "
            + "fi; "
            "cat result.json; "
            "cd /tmp; "
            + cleanup_command
            + "; exit 0"
        )
        ssh_cmd = ["ssh", host, remote_command]
        if ssh_password:
            ssh_cmd = ["sshpass", "-p", ssh_password] + ssh_cmd
        returncode, stdout, stderr = run_command(
            ssh_cmd,
            timeout=timeout,
        )
        if returncode != 0:
            raise RuntimeError(stderr.strip() or stdout.strip() or f"remote shell runner failed with {returncode}")
        text = stdout.strip()
        if not text:
            raise ValueError("empty remote result")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("remote result must be a JSON object")
        return data
    finally:
        if upload_dir.exists():
            shutil.rmtree(upload_dir)
