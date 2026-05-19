import atexit
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


class RemoteClient:
    def __init__(self, *, host: str, connect_timeout: int = 30) -> None:
        if paramiko is None:
            raise RuntimeError("paramiko is required for remote execution; install dependencies from requirements.txt") from _PARAMIKO_IMPORT_ERROR
        self.host = host
        self.connect_timeout = connect_timeout
        self.client: Any | None = None
        self.sftp: Any | None = None

    def connect(self) -> None:
        config = _load_ssh_config(self.host)
        hostname = str(config.get("hostname") or self.host)
        username = config.get("user")
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
