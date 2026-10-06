"""Professional notebook output components for manimgl-colab.

Design rules (user-specified):
- While rendering: ONLY a live progress card.
- After success:  ONLY the video (progress card collapses to a slim strip).
- All information lives behind %manimgl_log / %manimgl_status — never
  printed as loose text.
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any, Optional

from . import paths

# ----------------------------------------------------------------------
# Shared state: everything %manimgl_log / %manimgl_status needs.
# ----------------------------------------------------------------------
LAST_RENDER: dict[str, Any] = {}
LOG_FILE = paths.ROOT / "manimgl_last_log.txt"


def remember_render(info: dict[str, Any], raw_log: str) -> None:
    LAST_RENDER.clear()
    LAST_RENDER.update(info)
    try:
        LOG_FILE.write_text(raw_log, encoding="utf-8")
    except OSError:
        pass


# ----------------------------------------------------------------------
# Style primitives
# ----------------------------------------------------------------------
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"


def esc(value: Any) -> str:
    return html.escape(str(value))


def backend_badge(backend: str, renderer: Optional[str] = None) -> str:
    if backend == "gpu":
        color, label = GREEN, "GPU"
    else:
        color, label = ACCENT, "CPU"
    renderer_part = (
        f'<span style="color:{DIM}; font-weight:400;"> · {esc(renderer)}</span>'
        if renderer else ""
    )
    return (
        f'<span style="border:1px solid {color}; color:{color}; border-radius:12px;'
        f' padding:1px 10px; font:600 11px/{1.6} {MONO};">{label}</span>'
        f'<span style="font:11px/{1.6} {MONO};">{renderer_part}</span>'
    )


def _bar(percent: Optional[float]) -> str:
    if percent is None:
        # Indeterminate: animated stripes.
        return (
            '<div style="height:6px; border-radius:3px; overflow:hidden;'
            f' background:{BORDER};">'
            '<div style="height:100%; width:100%;'
            f' background:repeating-linear-gradient(45deg,{ACCENT} 0 10px,transparent 10px 20px);'
            ' animation:mgl-slide 1s linear infinite;"></div></div>'
            "<style>@keyframes mgl-slide{from{background-position:0 0}"
            "to{background-position:28px 0}}</style>"
        )
    percent = max(0.0, min(100.0, percent))
    return (
        f'<div style="height:6px; border-radius:3px; background:{BORDER};">'
        f'<div style="height:100%; width:{percent:.1f}%; border-radius:3px;'
        f' background:linear-gradient(90deg,{ACCENT},{GREEN});"></div></div>'
    )


def progress_card(
    *,
    scene: str,
    backend: str,
    quality: str,
    renderer: Optional[str],
    phase: str,
    percent: Optional[float],
    frames_done: Optional[int],
    frames_total: Optional[int],
    rate: Optional[float],
    eta: Optional[str],
    elapsed: float,
    anim_label: Optional[str],
    encoder: Optional[str] = None,
    gpu_line: Optional[str] = None,
) -> str:
    """The single live card shown while rendering."""
    pieces: list[str] = []
    if anim_label:
        pieces.append(esc(anim_label))
    if frames_done is not None:
        total_part = f"/{frames_total}" if frames_total else ""
        pieces.append(f"{frames_done}{total_part} frames")
    if rate is not None:
        pieces.append(f"{rate:.1f} it/s")
    if eta:
        pieces.append(f"ETA {esc(eta)}")
    pieces.append(f"elapsed {elapsed:.0f}s")
    if encoder:
        pieces.append(esc(encoder))
    if gpu_line:
        pieces.append(f'<span style="color:{ACCENT};">{esc(gpu_line)}</span>')
    footer = f' <span style="color:{DIM};">·</span> '.join(
        f'<span style="color:{DIM};">{piece}</span>' for piece in pieces
    )
    percent_label = f"{percent:.0f}%" if percent is not None else phase

    return f"""
    <div style="border:1px solid {BORDER}; border-radius:10px; background:{BG};
                padding:12px 16px; margin:6px 0; max-width:640px; font-family:{MONO};">
      <div style="display:flex; justify-content:space-between; align-items:center;
                  margin-bottom:8px;">
        <span style="color:{TEXT}; font-weight:600; font-size:13px;">
          ▶ {esc(scene)} &nbsp;{backend_badge(backend, renderer)}
        </span>
        <span style="color:{DIM}; font-size:12px;">{esc(quality)} · {esc(percent_label)}</span>
      </div>
      {_bar(percent)}
      <div style="margin-top:7px; font-size:11.5px;">{footer}</div>
    </div>
    """


def finished_strip(
    *,
    scene: str,
    backend: str,
    renderer: Optional[str],
    seconds: float,
    size_mb: float,
    note: Optional[str] = None,
) -> str:
    """Slim one-line success strip replacing the progress card."""
    note_part = f"{esc(note)} · " if note else ""
    return f"""
    <div style="border:1px solid {BORDER}; border-left:3px solid {GREEN};
                border-radius:8px; background:{BG}; padding:7px 14px; margin:6px 0;
                max-width:640px; font:12px/1.6 {MONO}; color:{DIM};
                display:flex; justify-content:space-between;">
      <span><span style="color:{GREEN};">✔</span>
        <span style="color:{TEXT};"> {esc(scene)}</span>
        &nbsp;{backend_badge(backend, renderer)}</span>
      <span>{note_part}{seconds:.1f}s · {size_mb:.2f} MB · details: %manimgl_log</span>
    </div>
    """


def failed_strip(scene: str, seconds: float) -> str:
    return f"""
    <div style="border:1px solid {BORDER}; border-left:3px solid {RED};
                border-radius:8px; background:{BG}; padding:7px 14px; margin:6px 0;
                max-width:640px; font:12px/1.6 {MONO}; color:{DIM};">
      <span style="color:{RED};">✖</span>
      <span style="color:{TEXT};"> {esc(scene)}</span> — failed after {seconds:.1f}s
    </div>
    """


def _row(key: str, value: str) -> str:
    return (
        f'<tr><td style="padding:3px 18px 3px 0; color:{DIM}; white-space:nowrap;">'
        f"{esc(key)}</td>"
        f'<td style="padding:3px 0; color:{TEXT};">{value}</td></tr>'
    )


def summary_card(info: dict[str, Any], raw_log: str | None = None) -> str:
    """Professional render report for %manimgl_log."""
    if not info:
        return (
            f'<div style="color:{DIM}; font-family:{MONO}; font-size:13px;">'
            "No render has completed in this session yet.</div>"
        )
    rows = [
        _row("Scene", f"<b>{esc(info.get('scene', '?'))}</b>"),
        _row("Backend", backend_badge(info.get("backend", "cpu"), info.get("renderer"))),
        _row("OpenGL", esc(info.get("opengl", "—"))),
        _row("Quality", esc(info.get("quality", "—"))),
        _row("Encoder", esc(info.get("encoder", "libx264"))
             + (f' <span style="color:{YELLOW};">(fallback from h264_nvenc)</span>'
                if info.get("encoder_fallback") else "")),
        _row("Frames", esc(info.get("frames", "—"))),
        _row("Render time", f"{info.get('seconds', 0):.2f} s"),
        _row("File size", f"{info.get('size_mb', 0):.2f} MB"),
        _row("Output", f'<code style="font-size:12px;">{esc(info.get("path", "—"))}</code>'),
        _row("Type", "PNG image (static)" if info.get("output_type") == "image" else "MP4 video"),
        _row("Workers", esc(info.get("jobs", 1))),
    ]
    if info.get("gpu_peak"):
        rows.append(_row("GPU peak", esc(info["gpu_peak"])))
    log_section = ""
    if raw_log is None and LOG_FILE.exists():
        try:
            raw_log = LOG_FILE.read_text(encoding="utf-8")
        except OSError:
            raw_log = None
    if raw_log:
        log_section = f"""
        <details style="margin-top:10px;">
          <summary style="cursor:pointer; color:{ACCENT}; font-size:12px;">
            Full renderer log</summary>
          <pre style="white-space:pre-wrap; color:{DIM}; font-size:11px;
                      max-height:360px; overflow:auto; background:{PANEL};
                      border:1px solid {BORDER}; border-radius:6px;
                      padding:10px;">{esc(raw_log)}</pre>
        </details>
        """
    return f"""
    <div style="border:1px solid {BORDER}; border-radius:10px; background:{BG};
                padding:14px 18px; margin:6px 0; max-width:640px;
                font:13px/1.5 {MONO};">
      <div style="color:{TEXT}; font-weight:600; margin-bottom:8px;">
        Render report</div>
      <table style="border-collapse:collapse; font-size:12.5px;">{''.join(rows)}</table>
      {log_section}
    </div>
    """


def status_card(report: dict[str, Any]) -> str:
    """Professional card for %manimgl_status."""
    renderer = str(report.get("renderer", "")) or None
    rows = [
        _row("Default backend", backend_badge(str(report.get("backend", "cpu")), renderer)),
        _row("OpenGL", esc(report.get("opengl", "—"))),
        _row("Engine", "installed ✓" if report.get("engine_installed") else "missing ✗"),
        _row("NVENC encoder", "available ✓" if report.get("nvenc") else "not available"),
        _row("LaTeX", "installed ✓" if report.get("latex") else
             "not installed (mc.install_latex())"),
        _row("Videos", f'<code style="font-size:12px;">{esc(report.get("video_dir", ""))}</code>'),
        _row("Version", esc(report.get("version", "?"))),
    ]
    return f"""
    <div style="border:1px solid {BORDER}; border-radius:10px; background:{BG};
                padding:14px 18px; margin:6px 0; max-width:640px;
                font:13px/1.5 {MONO};">
      <div style="color:{TEXT}; font-weight:600; margin-bottom:8px;">
        manimgl-colab status</div>
      <table style="border-collapse:collapse; font-size:12.5px;">{''.join(rows)}</table>
    </div>
    """


class LiveDisplay:
    """Thin wrapper around an IPython display handle with throttling."""

    def __init__(self, min_interval: float = 0.25):
        from IPython.display import HTML, display

        self._html = HTML
        self._handle = display(HTML(""), display_id=True)
        self._last = 0.0
        self._min_interval = min_interval

    def update(self, content: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < self._min_interval:
            return
        self._last = now
        try:
            self._handle.update(self._html(content))
        except Exception:
            pass
