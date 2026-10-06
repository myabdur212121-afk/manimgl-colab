"""Notebook-side manager for the warm render worker.

The worker (worker.py) keeps manimlib imported inside the isolated venv and
forks a pristine child per render — cutting per-render startup from ~4 s to
well under a second while keeping full isolation (see worker.py docstring).

Opt-in: nothing here runs unless the user calls ``mc.warm()`` (or
``%manimgl_warm on``).  Every consumer must tolerate failure: when anything
goes wrong the caller falls back to the classic cold subprocess path.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from . import paths

SOCKET_PATH = paths.RUNTIME_DIR / "warm.sock"
PID_FILE = paths.RUNTIME_DIR / "warm.pid"
WORKER_LOG = paths.RUNTIME_DIR / "warm_worker.log"
JOB_DIR = paths.RUNTIME_DIR / "warm_jobs"
WORKER_SCRIPT = paths.PACKAGE_DIR / "worker.py"

START_TIMEOUT = 240.0   # first manimlib import can be slow on cold Colab disks


class WarmError(RuntimeError):
    """Any warm-path failure; callers fall back to the cold path."""


def _gpu_state() -> Optional[dict]:
    try:
        from .backends import _load_gpu_state

        return _load_gpu_state()
    except Exception:  # noqa: BLE001
        return None


def _request(payload: dict, timeout: float = 10.0) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(SOCKET_PATH))
        client.sendall((json.dumps(payload) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode("utf-8"))
    finally:
        client.close()


def ping(timeout: float = 2.0) -> Optional[dict]:
    try:
        response = _request({"op": "ping"}, timeout=timeout)
        return response if response.get("ok") else None
    except (OSError, ValueError):
        return None


def _package_version() -> str:
    from . import __version__

    return __version__


def is_active() -> bool:
    """Worker alive AND built from the current package version."""
    info = ping()
    return bool(info) and info.get("version") == _package_version()


def start(wait: bool = True) -> dict:
    """Start (or adopt) the warm worker; returns its ping info."""
    gpu_state = _gpu_state()
    info = ping()
    if info:
        if (info.get("version") == _package_version()
                and (gpu_state is None or info.get("gpu_ready"))):
            return info
        # restart: package upgraded, or GPU became available since launch
        stop()

    if not paths.ENV_PYTHON.exists():
        raise WarmError("ManimGL is not installed. Run mc.setup() first.")

    paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    paths.RUNTIME_DIR.chmod(0o700)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_PATH.unlink()
    except OSError:
        pass

    environment = os.environ.copy()
    environment.setdefault("PYGLET_HEADLESS", "true")
    environment.setdefault("PYOPENGL_PLATFORM", "egl")
    gpu_ready = gpu_state is not None
    if gpu_ready:
        # LD_LIBRARY_PATH only takes effect at process start, so the worker
        # must be BORN with the NVIDIA library path to serve GPU renders.
        library_dir = gpu_state["library_dir"]
        environment["LD_LIBRARY_PATH"] = (
            f"{library_dir}:/usr/lib64-nvidia:"
            f"{environment.get('LD_LIBRARY_PATH', '')}"
        )

    log_handle = open(WORKER_LOG, "ab")
    process = subprocess.Popen(
        [str(paths.ENV_PYTHON), str(WORKER_SCRIPT), str(paths.RUNNER),
         str(SOCKET_PATH), _package_version(), "1" if gpu_ready else "0"],
        stdout=log_handle, stderr=log_handle,
        env=environment, start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")

    if not wait:
        return {"pid": process.pid}
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        info = ping(timeout=1.0)
        if info:
            return info
        if process.poll() is not None:
            tail = ""
            try:
                tail = WORKER_LOG.read_text(encoding="utf-8", errors="replace")[-800:]
            except OSError:
                pass
            raise WarmError(f"Warm worker exited during startup.\n{tail}")
        time.sleep(0.25)
    raise WarmError("Warm worker did not become ready in time.")


def stop() -> bool:
    """Shut the worker down; True if one was running."""
    was_running = False
    try:
        _request({"op": "shutdown"}, timeout=3.0)
        was_running = True
    except (OSError, ValueError):
        pass
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, 9)
                was_running = True
            except ProcessLookupError:
                pass
    except (OSError, ValueError):
        pass
    for stale in (SOCKET_PATH, PID_FILE):
        try:
            stale.unlink()
        except OSError:
            pass
    return was_running


def run_via_warm(
    command: list[str],
    environment: dict[str, str],
    on_update: Callable,
    *,
    verbose: bool = False,
) -> tuple[int, str]:
    """Drop-in replacement for progress.run_streaming through the worker.

    ``command`` must be the classic cold command
    ``[ENV_PYTHON, RUNNER, <args...>]`` — the same args are forwarded.
    Raises WarmError on any warm-infrastructure problem (callers fall back
    to the cold path); renderer failures return nonzero exit codes normally.
    """
    from .progress import ProgressState

    if len(command) < 3 or Path(command[1]).name != "runner.py":
        raise WarmError("Unexpected command shape for the warm path.")
    if not is_active():
        raise WarmError("Warm worker is not active.")
    if environment.get("MANIMGL_COLAB_EXPECT") == "gpu":
        info = ping()
        if not info or not info.get("gpu_ready"):
            # Worker was born before the GPU was prepared — rebirth with the
            # NVIDIA library path (start() picks it up from the GPU state).
            start()
            info = ping()
            if not info or not info.get("gpu_ready"):
                raise WarmError("Warm worker is not GPU-ready.")

    JOB_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    log_path = JOB_DIR / f"{job_id}.log"
    done_path = JOB_DIR / f"{job_id}.done"

    try:
        response = _request({
            "op": "render",
            "args": [str(part) for part in command[2:]],
            "env": dict(environment),
            "log": str(log_path),
            "done": str(done_path),
        }, timeout=15.0)
    except (OSError, ValueError) as error:
        raise WarmError(f"Warm request failed: {error}") from error
    if not response.get("ok"):
        raise WarmError(f"Warm worker refused the render: {response}")
    child_pid = int(response.get("pid") or 0)

    state = ProgressState()
    collected: list[str] = []
    buffer = ""
    position = 0
    last_alive_check = time.monotonic()

    def feed(text: str) -> None:
        nonlocal buffer
        buffer += text
        while True:
            newline = min(
                (i for i in (buffer.find("\n"), buffer.find("\r")) if i != -1),
                default=-1,
            )
            if newline == -1:
                break
            line, buffer = buffer[:newline], buffer[newline + 1:]
            if line:
                collected.append(line)
                if verbose:
                    print(line)
                if state.feed(line):
                    on_update(state)

    while True:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(position)
                fresh = handle.read()
                position = handle.tell()
            if fresh:
                feed(fresh)
        if done_path.exists():
            if buffer:
                feed("\n")
            try:
                code = int(json.loads(done_path.read_text(encoding="utf-8"))["code"])
            except (OSError, ValueError, KeyError):
                code = 1
            for scratch in (log_path, done_path):
                try:
                    scratch.unlink()
                except OSError:
                    pass
            return code, "\n".join(collected)

        now = time.monotonic()
        if now - last_alive_check > 5.0:
            last_alive_check = now
            child_dead = False
            if child_pid:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    child_dead = True
                except PermissionError:
                    pass
            if child_dead and not done_path.exists():
                time.sleep(1.0)   # grace period for the reaper thread
                if not done_path.exists():
                    raise WarmError("Warm render child vanished without result.")
        time.sleep(0.1)
