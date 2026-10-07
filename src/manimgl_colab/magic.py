"""The unified ManimCE-style ``%%manimgl`` cell magic (CPU/GPU switchable).

Render output policy (user-specified):
- while rendering → ONE live progress card (percent, animation, it/s, ETA)
- on success      → the video only (card collapses to a slim strip)
- information     → %manimgl_log (last render report) / %manimgl_status

Examples::

    %%manimgl -qm MyScene
    %%manimgl --gpu -qh --jobs 2 MyScene
    %%manimgl --cpu --draft --verbose MyScene
    %manimgl_file --gpu -qk ultimate_stress_test.py UltimateStressTest

Flags: -ql -qm -qh -qp -qk --draft | --gpu --cpu | -v LEVEL | --ERROR
       --no-prerun --verbose --jobs N --fps N -sql/-sqm/-sqh/-sqk (9:16 shorts) -s/--image --cold --display-width W | --display-height H --progress-off
"""

from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

from . import paths, ui
from .backends import get_backend, is_nvidia_renderer, nvenc_available, render_env
from .backends import set_backend, status
from .errors import (
    ManimGLRenderError,
    display_error_report,
    load_error_report,
    strip_ansi,
)
from .progress import ProgressState, run_streaming
from .transformer import register_transformer

_QUALITY_FLAGS = {
    "-ql": (["-l"], "480p"),
    "--quality=l": (["-l"], "480p"),
    "-qm": (["-m"], "720p"),
    "--quality=m": (["-m"], "720p"),
    "-qh": (["--hd"], "1080p"),
    "--quality=h": (["--hd"], "1080p"),
    "-qp": (["-r", "2560x1440"], "1440p"),
    "--quality=p": (["-r", "2560x1440"], "1440p"),
    "-qk": (["--uhd"], "4K"),
    "--quality=k": (["--uhd"], "4K"),
    # Shorts/Reels presets — the same qualities rotated to 9:16 vertical.
    "-sql": (["-r", "480x854"], "480×854 9:16"),
    "-sqm": (["-r", "720x1280"], "720×1280 9:16"),
    "-sqh": (["-r", "1080x1920"], "1080×1920 9:16"),
    "-sqk": (["-r", "2160x3840"], "2160×3840 9:16"),
}


def _parse_line(line: str) -> dict:
    tokens = shlex.split(line)
    if not tokens:
        raise ValueError("A scene class name is required. Example: %%manimgl -ql MyScene")
    scene_name = tokens[-1]
    options = tokens[:-1]

    parsed = {
        "scene_name": scene_name,
        "render_options": ["-l"],
        "quality_label": "480p",
        "log_level": "WARNING",
        "display_width": 560,
        "display_height": None,
        "display_width_set": False,
        "prerun": True,
        "verbose": False,
        "full_error": False,
        "backend_override": None,
        "jobs": 1,
        "user_vcodec": False,
        "image_only": False,
        "cold": False,
        "fps_override": None,
        "extra": [],
    }

    index = 0
    while index < len(options):
        option = options[index]
        normalized = option.lower()
        if option in _QUALITY_FLAGS:
            parsed["render_options"], parsed["quality_label"] = _QUALITY_FLAGS[option]
            parsed["render_options"] = list(parsed["render_options"])
        elif normalized == "--draft":
            parsed["render_options"] = ["-r", "640x360", "--fps", "15"]
            parsed["quality_label"] = "draft"
        elif normalized == "--cold":
            parsed["cold"] = True
        elif option in ("-s", "--image"):
            # ManimGL's own machinery: skip_animations + write_file
            # => save_last_frame (config.py:272). Renders a PNG still.
            parsed["image_only"] = True
        elif normalized == "--fps":
            if index + 1 >= len(options):
                raise ValueError("--fps must be followed by a frame rate.")
            fps = int(options[index + 1])
            if not 1 <= fps <= 120:
                raise ValueError("--fps must be between 1 and 120.")
            parsed["fps_override"] = fps
            index += 1
        elif option in ("-v", "--verbosity"):
            if index + 1 >= len(options):
                raise ValueError("-v must be followed by a log level.")
            parsed["log_level"] = options[index + 1].upper()
            index += 1
        elif option == "--display-width":
            if index + 1 >= len(options):
                raise ValueError("--display-width must be followed by a pixel width.")
            if parsed["display_height"] is not None:
                raise ValueError(
                    "Use either --display-width or --display-height, not both "
                    "(the other side is computed from the video's aspect)."
                )
            width = int(options[index + 1])
            if width < 100:
                raise ValueError("Display width must be at least 100 pixels.")
            parsed["display_width"] = width
            parsed["display_width_set"] = True
            index += 1
        elif option == "--display-height":
            if index + 1 >= len(options):
                raise ValueError("--display-height must be followed by a pixel height.")
            if parsed["display_width_set"]:
                raise ValueError(
                    "Use either --display-width or --display-height, not both "
                    "(the other side is computed from the video's aspect)."
                )
            height = int(options[index + 1])
            if height < 100:
                raise ValueError("Display height must be at least 100 pixels.")
            parsed["display_height"] = height
            index += 1
        elif option == "--jobs":
            if index + 1 >= len(options):
                raise ValueError("--jobs must be followed by a worker count.")
            parsed["jobs"] = max(1, int(options[index + 1]))
            index += 1
        elif normalized == "--gpu":
            parsed["backend_override"] = "gpu"
        elif normalized == "--cpu":
            parsed["backend_override"] = "cpu"
        elif normalized in ("--no-prerun", "--noprerun"):
            parsed["prerun"] = False
        elif normalized == "--prerun":
            parsed["prerun"] = True
        elif normalized == "--verbose":
            parsed["verbose"] = True
        elif normalized in ("--error", "--full-error"):
            parsed["full_error"] = True
        else:
            if option == "--vcodec":
                parsed["user_vcodec"] = True
            parsed["extra"].append(option)
        index += 1
    if "9:16" in parsed["quality_label"] and not parsed["display_width_set"] \
            and parsed["display_height"] is None:
        parsed["display_height"] = 480   # tall videos shouldn't swallow the notebook
    if parsed["fps_override"]:
        cleaned = list(parsed["render_options"])
        if "--fps" in cleaned:
            position = cleaned.index("--fps")
            del cleaned[position:position + 2]
        parsed["render_options"] = cleaned + ["--fps", str(parsed["fps_override"])]
        parsed["quality_label"] += f' @{parsed["fps_override"]}fps'

    return parsed


def _ensure_scene_in_source(scene_name: str, source: str, origin: str) -> None:
    """Fail fast with a clear message when the scene class is missing."""
    if re.search(rf"class\s+{re.escape(scene_name)}\s*[(:]", source):
        return
    raise ValueError(
        f"Scene class '{scene_name}' is not defined in {origin}.\n"
        "ManimGL only renders classes DEFINED in the rendered source — "
        "imported classes are ignored.\n"
        "Fix one of these ways:\n"
        f"  1) %%manimgl ... {scene_name}  → paste the FULL scene code "
        f"(including 'class {scene_name}(Scene):') below the magic line.\n"
        f"  2) Render straight from a file on disk:\n"
        f"     %manimgl_file --gpu -qm /path/to/file.py {scene_name}"
    )


def register_magics() -> None:
    """Register ``%%manimgl`` plus helper line magics in Colab/IPython."""
    from IPython import get_ipython
    from IPython.display import HTML, Image, Video, display

    ipython = get_ipython()
    if ipython is None:
        raise RuntimeError("Magics must be registered inside Google Colab or IPython.")

    register_transformer()
    last_rendered_video: Path | None = None

    # ------------------------------------------------------------------
    # Core render pipeline (shared by %%manimgl and %manimgl_file)
    # ------------------------------------------------------------------

    def _video_is_empty(path: Path) -> bool:
        """ManimGL writes a ~261-byte frameless MP4 container when a scene
        has zero animations — detect it so we can fall back to an image."""
        try:
            if path.stat().st_size < 1024:
                return True
        except OSError:
            return True
        try:
            import subprocess
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v",
                 "-show_entries", "stream=nb_frames,duration",
                 "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            fields = probe.stdout.strip().replace("\n", ",").split(",")
            numbers = [float(f) for f in fields if f and f not in ("N/A",)]
            return not numbers or max(numbers) <= 0
        except Exception:  # noqa: BLE001 — probing must never kill a render
            return False

    def _render(parsed: dict, source_text: str) -> None:
        nonlocal last_rendered_video

        total_start = time.perf_counter()
        scene_name = parsed["scene_name"]
        backend = parsed["backend_override"] or get_backend()

        if not paths.ENV_PYTHON.exists():
            raise FileNotFoundError("ManimGL is not installed. Run mc.setup() first.")
        if backend == "gpu" and not paths.GPU_STATE.exists():
            set_backend("gpu")  # strict: verify now or fail clearly

        paths.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        paths.RUNTIME_DIR.chmod(0o700)
        # One header comment so the file's line numbers equal the user's
        # cell line numbers (the %%manimgl line occupies cell line 1) —
        # error reports then point at the lines the user actually sees.
        paths.SCENE_FILE.write_text(
            "# %%manimgl — rendered by manimgl-colab\n" + source_text,
            encoding="utf-8",
        )

        expected_video = paths.VIDEO_DIR / f"{scene_name}.mp4"
        if expected_video.exists():
            expected_video.unlink()
        if paths.ERROR_REPORT.exists():
            paths.ERROR_REPORT.unlink()

        environment = render_env(backend)

        # Encoder selection: NVENC automatically on a verified GPU backend.
        encoder = "libx264"
        encoder_args: list[str] = []
        if (not parsed["user_vcodec"] and backend == "gpu"
                and not parsed["image_only"] and nvenc_available()):
            encoder = "h264_nvenc"
            encoder_args = ["--vcodec", "h264_nvenc"]

        def build_command(extra_encoder_args: list[str]) -> list[str]:
            command = [
                str(paths.ENV_PYTHON),
                str(paths.RUNNER),
                str(paths.SCENE_FILE),
                scene_name,
                "-w",
                *parsed["render_options"],
                "-c", "#000000",
                "--video_dir", str(paths.VIDEO_DIR),
                "--log-level", parsed["log_level"],
                *extra_encoder_args,
                *parsed["extra"],
            ]
            if parsed["image_only"]:
                command.append("-s")
            elif parsed["prerun"] and parsed["jobs"] == 1:
                command.append("--prerun")
            return command

        live = ui.LiveDisplay()
        render_start = time.perf_counter()
        progress_seen = {"frames": False}
        gpu_monitor = None
        if backend == "gpu":
            from .progress import GPUMonitor

            gpu_monitor = GPUMonitor().start()
        from .progress import CPUMonitor

        cpu_monitor = CPUMonitor().start()

        def on_update(state: ProgressState) -> None:
            if state.frames_done is not None:
                progress_seen["frames"] = True
            live.update(ui.progress_card(
                scene=scene_name,
                backend=backend,
                quality=parsed["quality_label"],
                renderer=state.renderer,
                phase=state.phase,
                percent=state.percent,
                frames_done=state.frames_done,
                frames_total=state.frames_total,
                rate=state.rate,
                eta=state.eta,
                elapsed=time.perf_counter() - render_start,
                anim_label=state.anim_label,
                encoder=encoder if encoder != "libx264" else None,
                gpu_line=" · ".join(
                    part for part in (
                        gpu_monitor.line if gpu_monitor else None,
                        cpu_monitor.line,
                    ) if part
                ) or None,
            ))

        on_update(ProgressState())

        def _stream(stream_command: list) -> tuple:
            """Warm worker when available (serial renders only), else the
            classic isolated cold subprocess. Warm failures fall back."""
            if parsed["jobs"] == 1 and not parsed["cold"]:
                from .warmup import WarmError, is_active, run_via_warm

                if is_active():
                    try:
                        result = run_via_warm(
                            stream_command, environment, on_update,
                            verbose=parsed["verbose"],
                        )
                        parsed["start_mode"] = "warm"
                        return result
                    except WarmError:
                        parsed["start_mode"] = "cold (warm fallback)"
            return run_streaming(
                stream_command, environment, on_update,
                verbose=parsed["verbose"],
            )

        num_plays = None
        if parsed["jobs"] > 1:
            from .parallel import render_parallel

            return_code, raw_output, num_plays, jobs_mode = render_parallel(
                scene_name=scene_name,
                base_command=build_command(encoder_args),
                environment=environment,
                jobs=parsed["jobs"],
                on_update=on_update,
                use_warm=not parsed["cold"],
            )
            parsed["start_mode"] = jobs_mode
        else:
            return_code, raw_output = _stream(build_command(encoder_args))
            # Self-healing: when the cheap prerun pass itself crashes (some
            # scenes with point-count-changing updaters break ManimGL's skip
            # machinery), silently retry without prerun.
            if return_code != 0 and parsed["prerun"] and not progress_seen["frames"]:
                parsed["prerun"] = False
                parsed["prerun_auto_disabled"] = True
                return_code, raw_output = _stream(build_command(encoder_args))
            # NVENC can fail on exotic resolutions/driver issues: fall back once.
            if return_code != 0 and encoder == "h264_nvenc" and (
                "nvenc" in raw_output.lower() or "cuda" in raw_output.lower()
            ):
                encoder = "libx264 (fallback)"
                return_code, raw_output = _stream(build_command([]))

        if gpu_monitor is not None:
            gpu_monitor.stop()
        cpu_monitor.stop()
        process_seconds = time.perf_counter() - render_start
        proof = re.search(r"\[manimgl-colab\] GL_RENDERER: (.+)", raw_output)
        renderer = proof.group(1).strip() if proof else None
        opengl = None
        version_match = re.search(r"\[manimgl-colab\] GL_VERSION: (.+)", raw_output)
        if version_match:
            opengl = version_match.group(1).strip()

        if (return_code != 0 and parsed.get("start_mode") == "warm"
                and backend == "gpu" and "not NVIDIA" in raw_output):
            # Safety net: the warm worker's GL stack cannot deliver a real
            # NVIDIA context (vendor sealed wrong at its birth). Retire it and
            # redo this render on the proven cold path — never surface this.
            from . import warmup as _warmup

            _warmup.stop()
            parsed["start_mode"] = "cold (warm gpu fallback)"
            return_code, raw_output = run_streaming(
                build_command(encoder_args), environment, on_update,
                verbose=parsed["verbose"],
            )
            proof = re.search(r"\[manimgl-colab\] GL_RENDERER: (.+)", raw_output)
            renderer = proof.group(1).strip() if proof else None
            version_match = re.search(r"\[manimgl-colab\] GL_VERSION: (.+)", raw_output)
            opengl = version_match.group(1).strip() if version_match else None

        if return_code != 0:
            live.update(ui.failed_strip(scene_name, process_seconds), force=True)
            report = load_error_report(raw_output)
            exception_type, message = display_error_report(
                report, raw_output,
                full_mode=parsed["full_error"], scene_name=scene_name,
            )
            ui.remember_render({
                "scene": scene_name, "backend": backend, "renderer": renderer,
                "opengl": opengl, "quality": parsed["quality_label"],
                "encoder": encoder, "seconds": process_seconds,
                "failed": True, "error": f"{exception_type}: {message}",
                "jobs": parsed["jobs"],
            }, raw_output)
            raise ManimGLRenderError(f"{exception_type}: {message}") from None

        expected_image = paths.VIDEO_DIR / f"{scene_name}.png"
        static_fallback = False
        if not parsed["image_only"]:
            if not expected_video.exists():
                candidates = sorted(
                    paths.VIDEO_DIR.glob(f"{scene_name}*.mp4"),
                    key=lambda path: path.stat().st_mtime, reverse=True,
                )
                if candidates:
                    expected_video = candidates[0]
            if not expected_video.exists() or _video_is_empty(expected_video):
                # ManimCE behaviour (cairo_renderer.scene_finished): a scene
                # with zero animations renders an image instead of a movie.
                # ManimGL lacks the auto-switch, so rerun with -s ourselves.
                static_command = [
                    part for part in build_command([]) if part != "--prerun"
                ] + ["-s"]
                fallback_code, fallback_output = _stream(static_command)
                raw_output += "\n" + fallback_output
                if fallback_code != 0 or not expected_image.exists():
                    raise FileNotFoundError(
                        "Rendering completed, but no MP4 was found."
                    )
                static_fallback = True
                if expected_video.exists():
                    expected_video.unlink()   # drop the frameless container

        is_image = parsed["image_only"] or static_fallback
        output_path = expected_image if is_image else expected_video
        if is_image and not output_path.exists():
            raise FileNotFoundError("Rendering completed, but no PNG was found.")

        last_rendered_video = output_path
        size_mb = output_path.stat().st_size / (1024 * 1024)

        frame_counts = re.findall(r"(\d+)/(\d+)\s*\[", raw_output)
        frames = "1" if is_image else (frame_counts[-1][1] if frame_counts else None)

        strip_note = None
        if static_fallback:
            strip_note = "static scene → image (PNG)"
        elif parsed["image_only"]:
            strip_note = "image (PNG)"
        live.update(ui.finished_strip(
            scene=scene_name, backend=backend, renderer=renderer,
            seconds=process_seconds, size_mb=size_mb, note=strip_note,
        ), force=True)
        if is_image:
            if parsed["display_height"] is not None:
                display(Image(filename=str(output_path),
                              height=parsed["display_height"]))
            else:
                display(Image(filename=str(output_path),
                              width=parsed["display_width"]))
            if static_fallback:
                display(HTML(
                    f'<div style="color:{ui.DIM}; font:11.5px {ui.MONO};'
                    f' margin:4px 0;">💡 Static scene (no animations) — add'
                    f' <b>self.play(...)</b> or <b>self.wait(2)</b> for a video.'
                    "</div>"
                ))
        else:
            if parsed["display_height"] is not None:
                size_attr = (
                    f'height="{parsed["display_height"]}" '
                    'style="max-width:100%; width:auto;"'
                )
            else:
                size_attr = (
                    f'width="{parsed["display_width"]}" '
                    'style="max-width:100%; height:auto;"'
                )
            attributes = "controls autoplay muted loop " + size_attr
            display(Video(str(expected_video), embed=True, html_attributes=attributes))

        ui.remember_render({
            "scene": scene_name,
            "backend": backend,
            "renderer": renderer,
            "opengl": opengl,
            "quality": parsed["quality_label"],
            "encoder": encoder,
            "encoder_fallback": encoder.endswith("(fallback)"),
            "frames": frames or "—",
            "seconds": process_seconds,
            "total_seconds": time.perf_counter() - total_start,
            "size_mb": size_mb,
            "path": str(output_path),
            "output_type": "image" if is_image else "video",
            "jobs": parsed["jobs"],
            "num_plays": num_plays,
            "prerun_auto_disabled": parsed.get("prerun_auto_disabled", False),
            "start_mode": parsed.get("start_mode", "cold"),
            "cpu_peak": (
                f"{cpu_monitor.peak}%" if cpu_monitor.peak else None
            ),
            "gpu_peak": (
                f"{gpu_monitor.peak_util}% util · {gpu_monitor.peak_encoder}% enc · "
                f"{gpu_monitor.peak_vram:.1f} GB VRAM"
            ) if gpu_monitor else None,
            "gpu_verified": bool(renderer and is_nvidia_renderer(renderer)),
        }, raw_output)

    # ------------------------------------------------------------------
    # Magics
    # ------------------------------------------------------------------
    def manimgl_magic(line: str, cell: str) -> None:
        parsed = _parse_line(line)
        _ensure_scene_in_source(parsed["scene_name"], cell, "this cell")
        _render(parsed, cell)

    def manimgl_file_magic(line: str) -> None:
        """Render a scene from a .py file: %manimgl_file [flags] path.py Scene"""
        tokens = shlex.split(line)
        if len(tokens) < 2:
            display(HTML(
                f'<div style="font:12.5px/1.6 {ui.MONO}; color:{ui.DIM};">'
                "Usage: <b>%manimgl_file [flags] path/to/file.py SceneName</b><br>"
                "Example: %manimgl_file --gpu -qm ultimate_stress_test.py "
                "UltimateStressTest</div>"
            ))
            return
        scene_name = tokens[-1]
        file_token = tokens[-2]
        flags = tokens[:-2]

        candidates = [
            Path(file_token).expanduser(),
            Path.cwd() / file_token,
            paths.ROOT / file_token,
        ]
        source_path = next((c for c in candidates if c.is_file()), None)
        if source_path is None:
            raise FileNotFoundError(
                f"File not found: {file_token} "
                f"(searched: {', '.join(str(c) for c in candidates)})"
            )
        source_text = source_path.read_text(encoding="utf-8")
        _ensure_scene_in_source(scene_name, source_text, str(source_path))
        _render(_parse_line(" ".join([*flags, scene_name])), source_text)

    def manimgl_log_magic(line: str) -> None:
        """Professional report of the last render + full renderer log."""
        display(HTML(ui.summary_card(ui.LAST_RENDER)))

    def manimgl_backend_magic(line: str) -> None:
        choice = line.strip().lower()
        if choice not in ("cpu", "gpu"):
            display(HTML(
                f'<div style="font:12.5px/1.6 {ui.MONO}; color:{ui.DIM};">'
                "Usage: <b>%manimgl_backend gpu</b> or <b>%manimgl_backend cpu</b> "
                f"· current default: <b>{get_backend().upper()}</b></div>"
            ))
            return
        set_backend(choice)

    def manimgl_status_magic(line: str) -> None:
        status()

    def manimgl_warm_magic(line: str) -> None:
        from . import warmup as warm_module

        choice = line.strip().lower() or "status"

        def strip(text: str, color: str) -> None:
            display(HTML(
                f'<div style="font:12.5px/1.6 {ui.MONO}; color:{color};'
                f' border-left:3px solid {color}; padding:4px 10px;'
                f' margin:4px 0;">{text}</div>'
            ))

        if choice in ("on", "start", "true", "1"):
            info = warm_module.start()
            strip(
                f"🔥 Warm worker ready ({info.get('backend', 'cpu').upper()}) — "
                f"pid {info.get('pid')} · next renders start in &lt;1s", ui.ACCENT,
            )
        elif choice in ("off", "stop", "false", "0"):
            stopped = warm_module.stop()
            strip(
                "Warm worker stopped — renders use the classic isolated start."
                if stopped else "Warm worker was not running.", ui.DIM,
            )
        else:
            info = warm_module.ping()
            if info and info.get("version") == __import__(
                "manimgl_colab").__version__:
                strip(
                    f"🔥 Warm: ON ({info.get('backend', 'cpu').upper()}) · pid "
                    f"{info['pid']} · {info['served']} render"
                    f"{'s' if info['served'] != 1 else ''} served", ui.ACCENT,
                )
            else:
                strip(
                    "Warm: OFF · enable with <b>%manimgl_warm on</b> "
                    "(or mc.warm()) for &lt;1s render starts", ui.DIM,
                )

    def manimgl_download_magic(line: str) -> None:
        try:
            from google.colab import files
        except ImportError as error:
            raise RuntimeError("%manimgl_download only works inside Google Colab.") from error

        requested_scene = line.strip()
        selected: Path | None = None
        if requested_scene:
            candidates = sorted(
                [*paths.VIDEO_DIR.glob(f"{requested_scene}*.mp4"),
                 *paths.VIDEO_DIR.glob(f"{requested_scene}*.png")],
                key=lambda path: path.stat().st_mtime, reverse=True,
            )
            selected = candidates[0] if candidates else None
        elif last_rendered_video is not None and last_rendered_video.exists():
            selected = last_rendered_video
        else:
            candidates = sorted(
                [*paths.VIDEO_DIR.glob("*.mp4"), *paths.VIDEO_DIR.glob("*.png")],
                key=lambda path: path.stat().st_mtime, reverse=True,
            )
            selected = candidates[0] if candidates else None

        if selected is None or not selected.exists():
            raise FileNotFoundError(
                f"No rendered MP4 was found for '{requested_scene}'."
                if requested_scene
                else "No rendered MP4 was found. Render a scene first."
            )
        files.download(str(selected))

    ipython.register_magic_function(manimgl_magic, magic_kind="cell", magic_name="manimgl")
    for name, function in [
        ("manimgl_file", manimgl_file_magic),
        ("manimgl_log", manimgl_log_magic),
        ("manimgl_backend", manimgl_backend_magic),
        ("manimgl_status", manimgl_status_magic),
        ("manimgl_warm", manimgl_warm_magic),
        ("manimgl_download", manimgl_download_magic),
    ]:
        ipython.register_magic_function(function, magic_kind="line", magic_name=name)

    from .filetools import register_file_magics

    register_file_magics()

    from . import __version__

    display(HTML(
        f'<div style="border:1px solid {ui.BORDER}; border-radius:8px;'
        f' background:{ui.BG}; padding:8px 14px; max-width:640px;'
        f' font:12px/1.7 {ui.MONO}; color:{ui.DIM};">'
        f'<span style="color:{ui.TEXT}; font-weight:600;">manimgl-colab '
        f'v{__version__}</span> — magics ready<br>'
        "<b style='color:#58a6ff;'>%%manimgl</b> "
        "[-ql -qm -qh -qp -qk --draft] [--gpu --cpu] [--jobs N] [--ERROR] Scene<br>"
        "<b style='color:#58a6ff;'>%manimgl_file</b> [flags] path.py Scene · "
        "<b style='color:#58a6ff;'>%manimgl_log</b> · "
        "<b style='color:#58a6ff;'>%manimgl_status</b> · "
        "<b style='color:#58a6ff;'>%manimgl_backend</b> gpu|cpu · "
        "<b style='color:#58a6ff;'>%manimgl_download</b></div>"
    ))
