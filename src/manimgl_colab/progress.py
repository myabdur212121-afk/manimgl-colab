"""Live progress streaming: parse ManimGL's tqdm output in real time.

ManimGL's file writer runs a tqdm progress display:
  with --prerun :  "Scene.mp4 3 FadeIn:  45%|####  | 418/929 [00:12<00:15, 41.9it/s]"
  without       :  "Scene.mp4 3 FadeIn: : 418it [00:12, 41.94it/s]"

tqdm refreshes with carriage returns, so the subprocess stream is read in
raw chunks (os.read) and split on both \\r and \\n.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Callable, Optional

TQDM_TOTAL = re.compile(
    r"(?P<desc>[^\r\n|]*?):?\s*(?P<pct>\d+)%\|[^|]*\|\s*"
    r"(?P<done>\d+)/(?P<total>\d+)\s*"
    r"\[(?P<elapsed>[\d:]+)<(?P<eta>[\d:?]+),\s*(?P<rate>[\d.]+)\s*it/s"
)
TQDM_PARTIAL = re.compile(
    r"(?P<desc>[^\r\n|]*?):?\s*:?\s*(?P<done>\d+)it\s*"
    r"\[(?P<elapsed>[\d:]+),\s*(?P<rate>[\d.]+)\s*it/s"
)
DESC = re.compile(r"(?P<file>\S+\.mp4)\s+(?P<index>\d+)\s*(?P<anim>.*)")
PROOF = re.compile(r"\[manimgl-colab\] GL_RENDERER: (?P<renderer>.+)")
VERSION_LINE = re.compile(r"ManimGL v[\d.]+")


class ProgressState:
    """Latest parsed snapshot of the renderer's progress."""

    def __init__(self) -> None:
        self.percent: Optional[float] = None
        self.frames_done: Optional[int] = None
        self.frames_total: Optional[int] = None
        self.rate: Optional[float] = None
        self.eta: Optional[str] = None
        self.anim_label: Optional[str] = None
        self.renderer: Optional[str] = None
        self.phase: str = "starting"

    def feed(self, fragment: str) -> bool:
        """Parse one \\r/\\n-delimited fragment; True when anything changed."""
        changed = False

        proof = PROOF.search(fragment)
        if proof:
            self.renderer = proof.group("renderer").strip()
            changed = True

        match = TQDM_TOTAL.search(fragment)
        if match:
            self.percent = float(match.group("pct"))
            self.frames_done = int(match.group("done"))
            self.frames_total = int(match.group("total"))
            self.rate = float(match.group("rate"))
            self.eta = match.group("eta")
            self.phase = "rendering"
            changed = True
        else:
            match = TQDM_PARTIAL.search(fragment)
            if match:
                self.frames_done = int(match.group("done"))
                self.rate = float(match.group("rate"))
                self.phase = "rendering"
                changed = True

        if match:
            description = DESC.search(match.group("desc").strip())
            if description:
                anim = description.group("anim").strip().rstrip(":").strip()
                index = description.group("index")
                self.anim_label = f"anim {index}" + (f" · {anim}" if anim else "")
        elif VERSION_LINE.search(fragment) and self.phase == "starting":
            self.phase = "preparing"
            changed = True
        return changed


def run_streaming(
    command: list[str],
    environment: dict[str, str],
    on_update: Callable[[ProgressState], None],
    *,
    verbose: bool = False,
    poll_interval: float = 0.05,
) -> tuple[int, str]:
    """Run the renderer, feeding parsed progress to ``on_update`` live."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    assert process.stdout is not None
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)

    state = ProgressState()
    log_parts: list[str] = []
    pending = ""

    def drain() -> bool:
        nonlocal pending
        got_data = False
        while True:
            try:
                chunk = os.read(descriptor, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            got_data = True
            text = chunk.decode("utf-8", errors="replace")
            log_parts.append(text)
            if verbose:
                print(text.replace("\r", "\n"), end="", flush=True)
            pending += text
            fragments = re.split(r"[\r\n]", pending)
            pending = fragments.pop() if fragments else ""
            changed = False
            for fragment in fragments:
                if fragment.strip():
                    changed |= state.feed(fragment)
            # Also try the trailing partial fragment (tqdm often has no newline).
            if pending.strip():
                changed |= state.feed(pending)
            if changed:
                on_update(state)
        return got_data

    while process.poll() is None:
        if not drain():
            time.sleep(poll_interval)
    drain()
    if pending.strip():
        state.feed(pending)
        on_update(state)

    return process.wait(), "".join(log_parts)


class GPUMonitor:
    """Samples real GPU utilization (not just VRAM) via nvidia-smi.

    Runs a daemon thread polling once per second.  ``line`` is a short
    human string for the live progress card; ``peak_util`` / ``peak_vram``
    are kept for the post-render log card.  Safe no-op when nvidia-smi is
    unavailable.
    """

    _QUERY = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,utilization.encoder,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]

    def __init__(self) -> None:
        self.line: str | None = None
        self.peak_util: int = 0
        self.peak_encoder: int = 0
        self.peak_vram: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        import subprocess

        result = subprocess.run(
            self._QUERY, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return
        parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(",")]
        util, encoder, used, total = (
            int(float(parts[0])), int(float(parts[1])),
            float(parts[2]) / 1024, float(parts[3]) / 1024,
        )
        self.peak_util = max(self.peak_util, util)
        self.peak_encoder = max(self.peak_encoder, encoder)
        self.peak_vram = max(self.peak_vram, used)
        self.line = (
            f"GPU {util}% · enc {encoder}% · VRAM {used:.1f}/{total:.0f} GB"
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except Exception:  # noqa: BLE001 — monitoring must never break renders
                self.line = None
                return
            self._stop.wait(1.0)

    def start(self) -> "GPUMonitor":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
