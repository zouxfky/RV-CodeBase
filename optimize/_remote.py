from __future__ import annotations

import atexit
import hashlib
import json
import re
import socket
import shlex
import shutil
import threading
import time
from pathlib import Path
from typing import Any

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - depends on the runtime environment.
    paramiko = None
    _PARAMIKO_IMPORT_ERROR = exc
else:
    _PARAMIKO_IMPORT_ERROR = None


CURRENT_DIR = Path(__file__).resolve().parent
REMOTE_RUNNER_PATH = CURRENT_DIR / "_remote.sh"
_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_THREAD_LOCAL = threading.local()
_CLIENTS: set["RemoteClient"] = set()
_CLIENTS_LOCK = threading.Lock()


def safe_name(value: str) -> str:
    text = _SAFE_PATTERN.sub("__", str(value).strip())
    return text or "empty"


def validate_remote_root(remote_root: str) -> str:
    root = str(remote_root).rstrip("/")
    if not root.startswith("/tmp/"):
        raise ValueError("remote_root must be under /tmp")
    return root


def remote_job_name(*, pid: str, attempt: int) -> str:
    return f"{safe_name(pid)}.round_{attempt}.{int(time.time() * 1000)}"


def directory_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        with child.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _load_ssh_config(host: str) -> dict[str, Any]:
    if paramiko is None:
        raise RuntimeError("paramiko is required for remote execution; install dependencies from requirements.txt")

    config_path = Path.home() / ".ssh" / "config"
    if not config_path.exists():
        return {"hostname": host}
    ssh_config = paramiko.SSHConfig()
    with config_path.open("r", encoding="utf-8") as config_file:
        ssh_config.parse(config_file)
    return ssh_config.lookup(host)


def parse_ssh_target(target: str) -> tuple[str | None, str]:
    value = str(target).strip()
    if not value:
        raise ValueError("remote host is empty")
    if "@" not in value:
        return None, value
    username, host = value.rsplit("@", 1)
    if not username or not host:
        raise ValueError(f"invalid remote host: {target}")
    return username, host


class RemoteClient:
    def __init__(self, *, host: str, connect_timeout: int = 30) -> None:
        if paramiko is None:
            raise RuntimeError("paramiko is required for remote execution; install dependencies from requirements.txt") from _PARAMIKO_IMPORT_ERROR
        self.host = host
        self.connect_timeout = connect_timeout
        self.client: Any | None = None
        self.sftp: Any | None = None

    def connect(self) -> None:
        target_user, target_host = parse_ssh_target(self.host)
        config = _load_ssh_config(target_host)
        hostname = str(config.get("hostname") or target_host)
        username = target_user or config.get("user")
        port = int(config.get("port") or 22)
        identity_files = config.get("identityfile")
        if isinstance(identity_files, str):
            identity_files = [identity_files]
        if identity_files:
            identity_files = [str(Path(path).expanduser()) for path in identity_files]

        sock = None
        proxy_command = config.get("proxycommand")
        if proxy_command:
            sock = paramiko.ProxyCommand(str(proxy_command))

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=hostname,
            port=port,
            username=username,
            key_filename=identity_files,
            timeout=self.connect_timeout,
            banner_timeout=self.connect_timeout,
            auth_timeout=self.connect_timeout,
            allow_agent=True,
            look_for_keys=True,
            sock=sock,
        )
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        self.client = client
        self.sftp = client.open_sftp()

    def close(self) -> None:
        sftp, client = self.sftp, self.client
        self.sftp = None
        self.client = None
        if sftp is not None:
            try:
                sftp.close()
            except OSError:
                pass
        if client is not None:
            try:
                client.close()
            except OSError:
                pass

    def is_alive(self) -> bool:
        if self.client is None:
            return False
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def ensure_connected(self) -> None:
        if self.is_alive() and self.sftp is not None:
            return
        self.close()
        self.connect()

    def mkdir_p(self, remote_dir: str) -> None:
        self.ensure_connected()
        assert self.sftp is not None
        parts = [part for part in remote_dir.split("/") if part]
        current = ""
        for part in parts:
            current += "/" + part
            try:
                self.sftp.stat(current)
            except OSError:
                try:
                    self.sftp.mkdir(current)
                except OSError:
                    self.sftp.stat(current)

    def put_dir(self, local_dir: Path, remote_dir: str) -> None:
        if not local_dir.is_dir():
            raise ValueError(f"local job dir does not exist: {local_dir}")
        self.ensure_connected()
        assert self.sftp is not None
        self.mkdir_p(remote_dir)
        for child in local_dir.iterdir():
            remote_child = f"{remote_dir.rstrip('/')}/{child.name}"
            if child.is_dir():
                self.put_dir(child, remote_child)
            else:
                self.sftp.put(str(child), remote_child)

    def exec(self, command: str, *, timeout: int) -> tuple[int, str, str]:
        self.ensure_connected()
        assert self.client is not None
        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("ssh transport is not active")

        channel = transport.open_session(timeout=self.connect_timeout)
        channel.set_combine_stderr(False)
        channel.exec_command(command)
        deadline = time.monotonic() + timeout
        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        try:
            while True:
                if channel.recv_ready():
                    stdout_parts.append(channel.recv(65536))
                if channel.recv_stderr_ready():
                    stderr_parts.append(channel.recv_stderr(65536))
                if channel.exit_status_ready():
                    break
                if time.monotonic() > deadline:
                    channel.close()
                    raise TimeoutError(f"remote command timed out after {timeout}s")
                time.sleep(0.05)

            while channel.recv_ready():
                stdout_parts.append(channel.recv(65536))
            while channel.recv_stderr_ready():
                stderr_parts.append(channel.recv_stderr(65536))
            returncode = channel.recv_exit_status()
        except (OSError, socket.timeout):
            self.close()
            raise
        finally:
            channel.close()

        stdout = b"".join(stdout_parts).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_parts).decode("utf-8", errors="replace")
        return returncode, stdout, stderr


def get_thread_remote_client(*, host: str, connect_timeout: int = 30) -> RemoteClient:
    client = getattr(_THREAD_LOCAL, "remote_client", None)
    if client is None or client.host != host:
        if client is not None:
            client.close()
        client = RemoteClient(host=host, connect_timeout=connect_timeout)
        _THREAD_LOCAL.remote_client = client
        with _CLIENTS_LOCK:
            _CLIENTS.add(client)
    client.ensure_connected()
    return client


def close_remote_clients() -> None:
    with _CLIENTS_LOCK:
        clients = list(_CLIENTS)
    for client in clients:
        client.close()


atexit.register(close_remote_clients)


def run_remote_job(
    *,
    host: str,
    remote_root: str,
    local_job_dir: Path,
    pid: str,
    attempt: int,
    timeout: int,
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
        client = get_thread_remote_client(host=host, connect_timeout=min(30, max(1, timeout)))
        cleanup_stage_command = f"rm -rf {shlex.quote(remote_stage_dir)}"
        returncode, stdout, stderr = client.exec(cleanup_stage_command, timeout=min(30, max(1, timeout)))
        if returncode != 0:
            raise RuntimeError(stderr.strip() or stdout.strip() or f"remote stage cleanup failed with {returncode}")
        client.put_dir(upload_dir, remote_stage_dir)
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
        returncode, stdout, stderr = client.exec(remote_command, timeout=timeout)
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


def run_remote_jobs_batch(
    *,
    host: str,
    remote_root: str,
    jobs: list[dict],
    timeout: int,
) -> dict[str, dict]:
    if not REMOTE_RUNNER_PATH.exists():
        raise ValueError(f"missing remote runner: {REMOTE_RUNNER_PATH}")
    if not jobs:
        return {}

    batch_name = f"batch.{int(time.time() * 1000)}.{threading.get_ident()}"
    batch_upload = Path(jobs[0]["local_job_dir"]).parent / batch_name
    if batch_upload.exists():
        shutil.rmtree(batch_upload)
    batch_upload.mkdir(parents=True, exist_ok=True)

    job_names: list[str] = []
    try:
        root = validate_remote_root(remote_root)
        static_root = f"{root}/_static"
        client = get_thread_remote_client(host=host, connect_timeout=min(30, max(1, timeout)))

        for job in jobs:
            local_job_dir = Path(job["local_job_dir"])
            local_static_dir = Path(job["local_static_dir"])
            local_job_dir.mkdir(parents=True, exist_ok=True)
            if not local_static_dir.is_dir():
                raise ValueError(f"missing local static dir: {local_static_dir}")
            shutil.copy2(REMOTE_RUNNER_PATH, local_static_dir / "_remote.sh")
            static_hash = directory_hash(local_static_dir)[:16]
            static_name = f"{safe_name(str(job['pid']))}.{static_hash}"
            remote_static_dir = f"{static_root}/{static_name}"
            returncode, _, _ = client.exec(
                f"test -f {shlex.quote(remote_static_dir + '/.ready')}",
                timeout=min(30, max(1, timeout)),
            )
            if returncode != 0:
                remote_static_stage = f"/tmp/static.{static_name}.{int(time.time() * 1000)}"
                cleanup_static_stage = f"rm -rf {shlex.quote(remote_static_stage)}"
                client.exec(cleanup_static_stage, timeout=min(30, max(1, timeout)))
                client.put_dir(local_static_dir, remote_static_stage)
                install_static = (
                    f"mkdir -p {shlex.quote(static_root)}; "
                    f"rm -rf {shlex.quote(remote_static_dir)}; "
                    f"mv {shlex.quote(remote_static_stage)} {shlex.quote(remote_static_dir)}; "
                    f"touch {shlex.quote(remote_static_dir + '/.ready')}"
                )
                returncode, stdout, stderr = client.exec(install_static, timeout=min(60, max(1, timeout)))
                if returncode != 0:
                    raise RuntimeError(stderr.strip() or stdout.strip() or f"remote static install failed with {returncode}")

            job_name = remote_job_name(pid=str(job["pid"]), attempt=int(job["attempt"]))
            job["remote_job_name"] = job_name
            job["remote_static_name"] = static_name
            job_names.append(job_name)
            optimized_src = local_job_dir / "optimized.cpp"
            if not optimized_src.is_file():
                raise ValueError(f"missing optimized.cpp: {optimized_src}")
            job_upload_dir = batch_upload / job_name
            job_upload_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(optimized_src, job_upload_dir / "optimized.cpp")

        manifest_lines = [
            f"{job['remote_job_name']}\t{job['remote_static_name']}"
            for job in jobs
        ]
        (batch_upload / "manifest.tsv").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        remote_stage_dir = f"/tmp/{batch_name}"
        remote_dir = f"{root}/{batch_name}"

        cleanup_stage_command = f"rm -rf {shlex.quote(remote_stage_dir)}"
        returncode, stdout, stderr = client.exec(cleanup_stage_command, timeout=min(30, max(1, timeout)))
        if returncode != 0:
            raise RuntimeError(stderr.strip() or stdout.strip() or f"remote batch stage cleanup failed with {returncode}")

        client.put_dir(batch_upload, remote_stage_dir)
        names_text = " ".join(shlex.quote(name) for name in job_names)
        move_command = (
            f"mkdir -p {shlex.quote(root)}; "
            f"rm -rf {shlex.quote(remote_dir)}; "
            f"mv {shlex.quote(remote_stage_dir)} {shlex.quote(remote_dir)}; "
        )
        cleanup_command = (
            f"rm -rf {shlex.quote(remote_dir)}; "
            f"rm -rf {shlex.quote(remote_stage_dir)}"
        )
        fallback_json = shlex.quote(
            '{"pid":"","status":"fail","stage":"remote","error_type":"remote_runner","message":"remote runner exited without result.json","global_sf_n":null,"baseline_time_ms":0.0,"optimized_time_ms":0.0,"speedup_ratio":0.0,"baseline_times_ms":[],"optimized_times_ms":[],"cases":[]}\n'
        )
        remote_command = (
            "set -u; "
            + move_command
            + f"cd {shlex.quote(remote_dir)}; "
            + f"static_root={shlex.quote(static_root)}; "
            + "while IFS='	' read -r job static_name; do "
            + "[ -z \"$job\" ] && continue; "
            + "rm -rf \"$job.run\"; "
            + "cp -a \"$static_root/$static_name\" \"$job.run\"; "
            + "cp \"$job/optimized.cpp\" \"$job.run/optimized.cpp\"; "
            + "(cd \"$job.run\" && chmod +x _remote.sh && ./_remote.sh result.json || true; "
            + "if [ ! -f result.json ]; then printf "
            + fallback_json
            + " > result.json; fi) & "
            + "done < manifest.tsv; "
            + "wait; "
            + f"jobs='{names_text}'; "
            + "for job in $jobs; do "
            + "printf '%s\\t' \"$job\"; "
            + "cat \"$job.run/result.json\" 2>/dev/null || printf "
            + fallback_json
            + "; "
            + "printf '\\n'; "
            + "done; "
            + "cd /tmp; "
            + cleanup_command
            + "; exit 0"
        )
        returncode, stdout, stderr = client.exec(remote_command, timeout=timeout)
        if returncode != 0:
            raise RuntimeError(stderr.strip() or stdout.strip() or f"remote batch runner failed with {returncode}")

        results: dict[str, dict] = {}
        for line in stdout.splitlines():
            if not line.strip():
                continue
            if "\t" not in line:
                continue
            job_name, text = line.split("\t", 1)
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("remote batch result must contain JSON objects")
            results[job_name] = data
        return results
    finally:
        if batch_upload.exists():
            shutil.rmtree(batch_upload)
