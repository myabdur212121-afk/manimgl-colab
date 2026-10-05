"""The unified ManimCE-style ``%%manimgl`` cell magic (CPU/GPU switchable).

Examples::

    %%manimgl -ql MyScene                 # default backend (mc.backend(...))
    %%manimgl --gpu -qm MyScene           # force verified NVIDIA GPU
    %%manimgl --cpu --draft MyScene       # force honest CPU software render
    %%manimgl -v WARNING -qh --ERROR MyScene

Line magics::

    %manimgl_backend gpu        # switch default backend (strict verify)
    %manimgl_status             # live renderer proof + configuration
    %manimgl_download [Scene]   # download the newest MP4
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from . import paths
from .backends import get_backend, is_nvidia_renderer, render_env, set_backend
from .backends import status as backend_status
from .errors import (
    ManimGLRenderError,
    display_error_report,
    load_error_report,
    strip_ansi,
)

PROOF_PATTERN = re.compile(r"\[manimgl-colab\] GL_RENDERER: (?P<renderer>.+)")

_QUALITY_FLAGS = {
    "-ql": ["-l"],
    "--quality=l": ["-l"],
    "-qm": ["-m"],
    "--quality=m": ["-m"],
    "-qh": ["--hd"],
    "--quality=h": ["--hd"],
    "-qp": ["-r", "2560x1440"],
    "--quality=p": ["-r", "2560x1440"],
    "-qk": ["--uhd"],
    "--quality=k": ["--uhd"],
}


def _run_and_capture(
    command: list[str],
    environment: dict[str, str],
    *,
    stream_output: bool,
) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    output_parts: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_parts.append(line)
        if stream_output and not line.startswith("[manimgl-colab]"):
            print(line, end="", flush=True)
    return process.wait(), "".join(output_parts)


def _parse_line(line: str) -> dict:
    tokens = shlex.split(line)
    if not tokens:
        raise ValueError(
            "A scene class name is required. Example: %%manimgl -ql MyScene"
        )
    scene_name = tokens[-1]
    options = tokens[:-1]

    parsed = {
        "scene_name": scene_name,
        "render_options": ["-l"],
        "quality_label": "-ql (low, 480p)",
        "log_level": "WARNING",
        "display_width": 560,
        "prerun": False,
        "progress": False,
        "full_error": False,
        "backend_override": None,
        "extra": [],
    }

    index = 0
    while index < len(options):
        option = options[index]
        normalized = option.lower()
        if option in _QUALITY_FLAGS:
            parsed["render_options"] = list(_QUALITY_FLAGS[option])
            parsed["quality_label"] = option
        elif normalized == "--draft":
            parsed["render_options"] = ["-r", "640x360", "--fps", "15"]
            parsed["quality_label"] = "draft (640x360 @ 15 FPS)"
        elif option in ("-v", "--verbosity"):
            if index + 1 >= len(options):
                raise ValueError("-v must be followed by a log level.")
            parsed["log_level"] = options[index + 1].upper()
            index += 1
        elif option == "--display-width":
            if index + 1 >= len(options):
                raise ValueError("--display-width must be followed by a pixel width.")
            width = int(options[index + 1])
            if width < 100:
                raise ValueError("Display width must be at least 100 pixels.")
            parsed["display_width"] = width
            index += 1
        elif normalized == "--gpu":
            parsed["backend_override"] = "gpu"
        elif normalized == "--cpu":
            parsed["backend_override"] = "cpu"
        elif normalized == "--prerun":
            parsed["prerun"] = True
        elif normalized == "--progress":
            parsed["progress"] = True
        elif normalized in ("--error", "--full-error"):
            parsed["full_error"] = True
        else:
            parsed["extra"].append(option)
        index += 1
    return parsed


def register_magics() -> None:
    """Register ``%%manimgl`` plus helper line magics in Colab/IPython."""
    from IPython import get_ipython
    from IPython.display import Video, display

    ipython = get_ipython()
    if ipython is None:
        raise RuntimeError("Magics must be registered inside Google Colab or IPython.")

    last_rendered_video: Path | None = None

    def manimgl_magic(line: str, cell: str) -> None:
        nonlocal last_rendered_video

        total_start = time.perf_counter()
        parsed = _parse_line(line)
        scene_name = parsed["scene_name"]
        backend = parsed["backend_override"] or get_backend()

        if not paths.ENV_PYTHON.exists():
            raise FileNotFoundError(
                "ManimGL is not installed. Run mc.setup() first."
            )
        if backend == "gpu" and not paths.GPU_STATE.exists():
            # Strict: prepare and verify the GPU now, or fail clearly.
            set_backend("gpu")

        paths.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        paths.RUNTIME_DIR.chmod(0o700)
        paths.SCENE_FILE.write_text(cell, encoding="utf-8")

        expected_video = paths.VIDEO_DIR / f"{scene_name}.mp4"
        if expected_video.exists():
            expected_video.unlink()
        if paths.ERROR_REPORT.exists():
            paths.ERROR_REPORT.unlink()

        environment = render_env(backend)

        optional: list[str] = []
        if parsed["prerun"]:
            optional.append("--prerun")
        if parsed["progress"]:
            optional.extend(["--show_animation_progress", "--leave_progress_bars"])

        command = [
            str(paths.ENV_PYTHON),
            str(paths.RUNNER),
            str(paths.SCENE_FILE),
            scene_name,
            "-w",
            *parsed["render_options"],
            "-c",
            "#000000",
            "--video_dir",
            str(paths.VIDEO_DIR),
            "--log-level",
            parsed["log_level"],
            *optional,
            *parsed["extra"],
        ]

        backend_label = (
            "GPU — NVIDIA EGL (strict, verified)" if backend == "gpu"
            else "CPU — Mesa software (honest)"
        )
        print("=" * 68)
        print(f"ManimGL render — {scene_name}")
        print("=" * 68)
        print(f"Backend: {backend_label}")
        print(f"Quality: {parsed['quality_label']}")
        print(f"Error mode: {'FULL' if parsed['full_error'] else 'compact'}")
        print("\n[1/3] Rendering...", flush=True)

        process_start = time.perf_counter()
        stream = parsed["progress"] or parsed["log_level"] in ("INFO", "DEBUG")
        return_code, raw_output = _run_and_capture(command, environment, stream_output=stream)
        process_seconds = time.perf_counter() - process_start

        proof_match = PROOF_PATTERN.search(raw_output)
        renderer = proof_match.group("renderer").strip() if proof_match else None
        if renderer:
            verdict = "GPU ✅" if is_nvidia_renderer(renderer) else "CPU (software)"
            print(f"Proof — GL_RENDERER: {renderer}  →  {verdict}")

        if return_code != 0:
            print(f"\nRender failed after {process_seconds:.2f} seconds.", flush=True)
            report = load_error_report(raw_output)
            exception_type, message = display_error_report(
                report,
                raw_output,
                full_mode=parsed["full_error"],
                scene_name=scene_name,
            )
            raise ManimGLRenderError(f"{exception_type}: {message}") from None

        if not stream:
            clean_output = strip_ansi(raw_output)
            important = [
                output_line
                for output_line in clean_output.splitlines()
                if ("WARNING" in output_line.upper() or "ERROR" in output_line.upper())
                and not output_line.startswith("[manimgl-colab]")
            ]
            if important:
                print("\n".join(important), flush=True)

        print(f"[2/3] Render finished in {process_seconds:.2f} seconds.")
        print("[3/3] Preparing video preview...", flush=True)

        if not expected_video.exists():
            candidates = sorted(
                paths.VIDEO_DIR.glob(f"{scene_name}*.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            ) or sorted(
                paths.VIDEO_DIR.glob("*.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise FileNotFoundError("Rendering completed, but no MP4 file was found.")
            expected_video = candidates[0]

        last_rendered_video = expected_video
        size_mb = expected_video.stat().st_size / (1024 * 1024)
        attributes = (
            "controls autoplay muted loop "
            f'width="{parsed["display_width"]}" style="max-width:100%; height:auto;"'
        )
        display(Video(str(expected_video), embed=True, html_attributes=attributes))

        print("\n" + "=" * 68)
        print("Video ready")
        print("=" * 68)
        print(f"Path: {expected_video}")
        print(f"Size: {size_mb:.2f} MB")
        print(f"Backend: {backend.upper()}"
              + (f"  |  Renderer: {renderer}" if renderer else ""))
        print(f"Render time: {process_seconds:.2f} s  |  "
              f"Total: {time.perf_counter() - total_start:.2f} s")
        print(f"Download: %manimgl_download {scene_name}")

    def manimgl_backend_magic(line: str) -> None:
        """Switch the default backend: %manimgl_backend gpu | cpu"""
        choice = line.strip().lower()
        if choice not in ("cpu", "gpu"):
            print("Usage: %manimgl_backend gpu   or   %manimgl_backend cpu")
            print(f"Current default: {get_backend().upper()}")
            return
        set_backend(choice)

    def manimgl_status_magic(line: str) -> None:
        backend_status()

    def manimgl_download_magic(line: str) -> None:
        """Download the latest render, optionally selected by scene class name."""
        try:
            from google.colab import files
        except ImportError as error:
            raise RuntimeError("%manimgl_download only works inside Google Colab.") from error

        requested_scene = line.strip()
        selected: Path | None = None
        if requested_scene:
            candidates = sorted(
                paths.VIDEO_DIR.glob(f"{requested_scene}*.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                selected = candidates[0]
        elif last_rendered_video is not None and last_rendered_video.exists():
            selected = last_rendered_video
        else:
            candidates = sorted(
                paths.VIDEO_DIR.glob("*.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                selected = candidates[0]

        if selected is None or not selected.exists():
            raise FileNotFoundError(
                f"No rendered MP4 was found for '{requested_scene}'."
                if requested_scene
                else "No rendered MP4 was found. Render a scene first."
            )
        print(f"Downloading: {selected.name} "
              f"({selected.stat().st_size / (1024 * 1024):.2f} MB)")
        files.download(str(selected))

    ipython.register_magic_function(manimgl_magic, magic_kind="cell", magic_name="manimgl")
    ipython.register_magic_function(
        manimgl_backend_magic, magic_kind="line", magic_name="manimgl_backend"
    )
    ipython.register_magic_function(
        manimgl_status_magic, magic_kind="line", magic_name="manimgl_status"
    )
    ipython.register_magic_function(
        manimgl_download_magic, magic_kind="line", magic_name="manimgl_download"
    )

    from .filetools import register_file_magics

    register_file_magics()

    print("Magics registered:")
    print("  %%manimgl [-ql|-qm|-qh|-qp|-qk|--draft] [--gpu|--cpu] [--ERROR] Scene")
    print("  %manimgl_backend gpu|cpu   %manimgl_status   %manimgl_download [Scene]")
    print("  %openfile  %filebackups  %restorefile")
