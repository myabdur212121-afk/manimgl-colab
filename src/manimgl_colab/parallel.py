"""Experimental parallel rendering: split animations across worker processes.

ManimGL renders strictly sequentially. ``--jobs N`` splits the scene's
animations into N contiguous ranges (ManimGL's ``-n start,end`` — start
inclusive, end exclusive), renders each range in its own process, and then
losslessly concatenates the parts with ffmpeg (stream copy, no re-encode).

Honest trade-offs (documented, not hidden):
- Each worker still computes the scene from the beginning (skipped
  animations are computed without rendering), so speed-up < N.
- The scene must be deterministic (random content without a fixed seed
  can produce visible seams between chunks).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import paths
from .progress import ProgressState, run_streaming


def _count_animations(
    scene_name: str, environment: dict[str, str], use_warm: bool = False,
) -> int:
    """Dry-run the scene (skip_animations) inside the engine and count plays."""
    command = [
        str(paths.ENV_PYTHON), str(paths.PACKAGE_DIR / "count_runner.py"),
        str(paths.SCENE_FILE), scene_name,
    ]
    output = ""
    if use_warm:
        try:
            from . import warmup

            _, output = warmup.run_via_warm(
                command, environment, lambda state: None,
            )
        except Exception:  # noqa: BLE001 — fall back to the cold pass
            output = ""
    if "NUM_PLAYS:" not in output:
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True,
            timeout=600,
        )
        output = (result.stdout or "") + (result.stderr or "")
    for line in reversed(output.splitlines()):
        if line.startswith("NUM_PLAYS:"):
            return int(line.split(":", 1)[1])
    raise RuntimeError(
        "Could not count the scene's animations for --jobs:\n" + output[-2000:]
    )


def _chunk_ranges(total: int, jobs: int) -> list[tuple[int, int]]:
    jobs = max(1, min(jobs, total))
    base, remainder = divmod(total, jobs)
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(jobs):
        size = base + (1 if index < remainder else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def render_parallel(
    *,
    scene_name: str,
    base_command: list[str],
    environment: dict[str, str],
    jobs: int,
    on_update,
    use_warm: bool = False,
) -> tuple[int, str, int, str]:
    """Render in ``jobs`` processes.

    Returns (returncode, log, num_plays, start_mode). With ``use_warm`` the
    counting pass and every chunk fork from the warm worker (zero import
    cost each); any chunk that cannot go warm falls back to cold alone.
    """
    if use_warm:
        from . import warmup

        use_warm = warmup.ensure_backend(environment)
    total_plays = _count_animations(scene_name, environment, use_warm)
    ranges = _chunk_ranges(total_plays, jobs)
    jobs = len(ranges)

    work_root = paths.ROOT / "manimgl_parallel"
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True)

    states: list[ProgressState] = [ProgressState() for _ in ranges]
    warm_misses: list[bool] = [False] * len(ranges)
    results: list[tuple[int, str] | None] = [None] * len(ranges)
    threads: list[threading.Thread] = []

    def worker(index: int, animation_range: tuple[int, int]) -> None:
        chunk_dir = work_root / f"chunk{index}"
        chunk_dir.mkdir()
        command = list(base_command)
        video_dir_position = command.index("--video_dir") + 1
        command[video_dir_position] = str(chunk_dir)
        command += ["-n", f"{animation_range[0]},{animation_range[1]}"]

        def chunk_update(state: ProgressState) -> None:
            states[index] = state
            aggregate = ProgressState()
            aggregate.phase = "rendering"
            aggregate.frames_done = sum(s.frames_done or 0 for s in states)
            totals = [s.frames_total for s in states]
            if all(t is not None for t in totals):
                aggregate.frames_total = sum(t for t in totals if t)
                if aggregate.frames_total:
                    aggregate.percent = (
                        100.0 * aggregate.frames_done / aggregate.frames_total
                    )
            aggregate.rate = sum(s.rate or 0.0 for s in states) or None
            aggregate.renderer = next(
                (s.renderer for s in states if s.renderer), None
            )
            active = sum(1 for s in states if s.phase == "rendering")
            aggregate.anim_label = f"{jobs} workers · {active} active"
            on_update(aggregate)

        if use_warm:
            try:
                from . import warmup

                results[index] = warmup.run_via_warm(
                    command, environment, chunk_update,
                )
                return
            except Exception:  # noqa: BLE001 — this chunk alone goes cold
                warm_misses[index] = True
        results[index] = run_streaming(command, environment, chunk_update)

    for index, animation_range in enumerate(ranges):
        thread = threading.Thread(target=worker, args=(index, animation_range))
        thread.start()
        threads.append(thread)
        time.sleep(0.3)  # stagger process start-up
    for thread in threads:
        thread.join()

    if not use_warm:
        start_mode = "cold"
    elif any(warm_misses):
        start_mode = "warm (partial)"
    else:
        start_mode = "warm"

    logs = []
    for index, result in enumerate(results):
        returncode, log = result if result else (1, "worker produced no result")
        logs.append(f"===== worker {index} (anims {ranges[index]}) =====\n{log}")
        if returncode != 0:
            return returncode, "\n".join(logs), total_plays, start_mode

    # Losslessly concatenate the chunk files in order.
    parts: list[Path] = []
    for index in range(len(ranges)):
        chunk_files = sorted((work_root / f"chunk{index}").glob("*.mp4"))
        if not chunk_files:
            return (1, "\n".join(logs) + f"\nworker {index} produced no MP4",
                    total_plays, start_mode)
        parts.append(chunk_files[0])

    list_file = work_root / "concat.txt"
    list_file.write_text(
        "".join(f"file '{part}'\n" for part in parts), encoding="utf-8"
    )
    final_path = paths.VIDEO_DIR / f"{scene_name}.mp4"
    concat = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(final_path)],
        capture_output=True, text=True,
    )
    logs.append("===== ffmpeg concat =====\n" + (concat.stdout or "") + (concat.stderr or ""))
    return concat.returncode, "\n".join(logs), total_plays, start_mode
