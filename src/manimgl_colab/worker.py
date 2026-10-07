"""Warm render worker — runs INSIDE the isolated ManimGL environment.

Keeps ``manimlib`` (and its heavy import chain) loaded in a resident parent
process.  Every render request is served by ``os.fork()``: the child inherits
the warm imports for free, applies the request's environment, creates its own
fresh OpenGL context (the GL proof still happens per render, inside runner.py)
and dies when done — so render isolation is fully preserved:

- a crashing scene kills only the child; the warm parent survives
- no state leaks between renders (children always start from the pristine,
  never-rendered parent image)

Protocol (newline-delimited JSON over a unix socket):
  {"op": "ping"}                       -> {"ok": true, "version": ..., "served": n}
  {"op": "shutdown"}                   -> {"ok": true}   and the worker exits
  {"op": "render", "args": [...], "env": {...}, "log": p, "done": p,
   "script": optional path (default RUNNER_PATH)}
                                       -> {"ok": true, "pid": child_pid}
    child stdout+stderr -> log file; on exit {"code": c} is written to done.

Standard library only.
argv: worker.py RUNNER_PATH SOCKET_PATH VERSION BACKEND("cpu"/"gpu")

BACKEND note: importing manimlib loads glvnd's libEGL and the EGL vendor is
enumerated and CACHED per process at that moment (verified: libEGL_mesa shows
up in the parent's /proc/maps right after import).  A forked child therefore
CANNOT switch vendors via environment variables — so the worker is born with
the FULL EGL environment of one backend (NVIDIA json + driver LD path for
gpu; Mesa for cpu) and only serves renders of that backend.  Switching
backends triggers a one-time worker rebirth, handled notebook-side.
"""

from __future__ import annotations

import json
import os
import runpy
import socket
import sys
import threading

RUNNER_PATH = sys.argv[1]
SOCKET_PATH = sys.argv[2]
VERSION = sys.argv[3] if len(sys.argv) > 3 else "?"
BACKEND = sys.argv[4] if len(sys.argv) > 4 else "cpu"

os.environ.setdefault("PYGLET_HEADLESS", "true")
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

# ----------------------------------------------------------------------
# The expensive part — done ONCE. Children inherit it via fork.
# IMPORTANT: importing manimlib must not create a GL context (it doesn't;
# contexts are created at Scene/window construction inside the child).
# ----------------------------------------------------------------------
import pyglet  # noqa: E402

# EXACTLY the same pyglet bootstrap as runner.py — the child re-runs
# runner.py, and the options must already match before manimlib is imported.
pyglet.options["headless"] = True
pyglet.options["headless_device"] = 0
pyglet.options["shadow_window"] = False

# manimlib parses its CLI config AT IMPORT TIME, so give it a neutral argv
# here; each child purges manimlib's own modules and re-imports them with the
# real render argv (cheap — the heavy dependency tree below stays loaded).
_REAL_ARGV = list(sys.argv)
sys.argv = ["manimgl"]
import manimlib  # noqa: E402,F401  (the ~2-4 s import, paid once)
import manimlib.__main__  # noqa: E402,F401
sys.argv = _REAL_ARGV

SERVED = 0


def _child_render(request: dict) -> None:
    """Runs in the forked child: fresh env, own log file, then runner.py."""
    log_fd = os.open(request["log"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)

    environment = dict(request.get("env") or {})
    if environment:
        os.environ.clear()
        os.environ.update(environment)
    os.environ["MANIMGL_WARM_CHILD"] = "1"

    # Purge manimlib's own modules: its config/window state was captured at
    # parent import time; re-importing (deps stay warm) re-reads THIS argv.
    for module_name in [m for m in sys.modules if m.split(".")[0] == "manimlib"]:
        del sys.modules[module_name]

    script = request.get("script") or RUNNER_PATH
    sys.argv = [script] + list(request.get("args") or [])
    code = 0
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exit_error:
        raw = exit_error.code
        code = raw if isinstance(raw, int) else (0 if raw is None else 1)
    except BaseException:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _reap_and_report(pid: int, done_path: str) -> None:
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        code = os.WEXITSTATUS(status)
    else:
        code = 128 + (os.WTERMSIG(status) if os.WIFSIGNALED(status) else 1)
    tmp_path = done_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"code": code}, handle)
    os.replace(tmp_path, done_path)


def main() -> None:
    global SERVED
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(8)

    while True:
        connection, _ = server.accept()
        try:
            connection.settimeout(10)
            data = b""
            while not data.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
            request = json.loads(data.decode("utf-8"))
            operation = request.get("op")

            if operation == "ping":
                connection.sendall((json.dumps({
                    "ok": True, "version": VERSION, "served": SERVED,
                    "pid": os.getpid(), "backend": BACKEND,
                }) + "\n").encode())
            elif operation == "shutdown":
                connection.sendall(b'{"ok": true}\n')
                connection.close()
                break
            elif operation == "render":
                pid = os.fork()
                if pid == 0:
                    server.close()
                    connection.close()
                    _child_render(request)   # never returns
                SERVED += 1
                threading.Thread(
                    target=_reap_and_report,
                    args=(pid, request["done"]),
                    daemon=True,
                ).start()
                connection.sendall((json.dumps({
                    "ok": True, "pid": pid,
                }) + "\n").encode())
            else:
                connection.sendall(b'{"ok": false, "error": "unknown op"}\n')
        except Exception:  # noqa: BLE001 — the server must keep running
            pass
        finally:
            try:
                connection.close()
            except OSError:
                pass

    server.close()
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass


if __name__ == "__main__":
    main()
