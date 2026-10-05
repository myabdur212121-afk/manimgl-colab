"""Small subprocess helpers shared by the installer and backends."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    quiet: bool = False,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> str:
    """Run a command, optionally capture its output, and fail loudly."""
    if not quiet:
        print("$ " + " ".join(str(part) for part in command), flush=True)
    result = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if check and result.returncode != 0:
        output = (result.stdout or "").strip()
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: "
            + " ".join(str(part) for part in command)
            + (f"\n{output[-4000:]}" if output else "")
        )
    return result.stdout or ""


def apt(args: list[str], *, quiet: bool = False, cwd: Path | None = None) -> str:
    """Run apt-get, adding sudo automatically when not root (e.g. sandboxes)."""
    prefix: list[str] = []
    if hasattr(os, "geteuid") and os.geteuid() != 0 and shutil.which("sudo"):
        prefix = ["sudo"]
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return run(prefix + ["apt-get", *args], quiet=quiet, capture=True, cwd=cwd, env=env)
