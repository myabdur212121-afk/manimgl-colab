"""Rich notebook error reports for failed renders (compact and full modes)."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from . import paths

ANSI_PATTERN = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TRACEBACK_FRAME_PATTERN = re.compile(
    r'^\s*File "(?P<filename>.+?)", line (?P<line>\d+), in (?P<function>.+?)\s*$',
    re.MULTILINE,
)
EXCEPTION_LINE_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit)):\s*(?P<message>.*)$",
    re.MULTILINE,
)


class ManimGLRenderError(RuntimeError):
    """A short notebook-facing exception; the detailed report is shown in HTML."""

    def _render_traceback_(self) -> list[str]:
        return [str(self)]


def strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", text).replace("\r", "\n")


def _fallback_report(raw_output: str) -> dict[str, Any]:
    clean_output = strip_ansi(raw_output)
    exception_matches = list(EXCEPTION_LINE_PATTERN.finditer(clean_output))
    frame_matches = list(TRACEBACK_FRAME_PATTERN.finditer(clean_output))

    if exception_matches:
        final_match = exception_matches[-1]
        exception_type = final_match.group("type").split(".")[-1]
        message = final_match.group("message")
    else:
        exception_type = "ManimGLRenderError"
        message = "The renderer exited without a structured Python exception."

    frames = [
        {
            "filename": match.group("filename"),
            "lineno": int(match.group("line")),
            "function": match.group("function"),
            "line": "",
            "colno": None,
            "end_colno": None,
            "end_lineno": None,
        }
        for match in frame_matches
    ]
    return {
        "version": 0,
        "exception": {
            "type": exception_type,
            "qualified_type": exception_type,
            "message": message,
            "frames": frames,
            "syntax_frame": None,
            "relation": None,
            "cause": None,
        },
    }


def load_error_report(raw_output: str) -> dict[str, Any]:
    if paths.ERROR_REPORT.exists():
        try:
            return json.loads(paths.ERROR_REPORT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return _fallback_report(raw_output)


def _exception_chain(exception: dict[str, Any]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    cause = exception.get("cause")
    if isinstance(cause, dict):
        chain.extend(_exception_chain(cause))
    chain.append(exception)
    return chain


def _is_user_frame(frame: dict[str, Any]) -> bool:
    filename = str(frame.get("filename", ""))
    try:
        return Path(filename).resolve() == paths.SCENE_FILE.resolve()
    except OSError:
        return filename.endswith(paths.SCENE_FILE.name)


def _read_source_lines(frame: dict[str, Any]) -> list[str]:
    filename = str(frame.get("filename", ""))
    try:
        return Path(filename).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        line = str(frame.get("line", ""))
        return [line] if line else []


def _highlight_code(code: str, frame: dict[str, Any], is_error_line: bool) -> str:
    if not is_error_line:
        return html.escape(code)
    colno = frame.get("colno")
    end_colno = frame.get("end_colno")
    if not isinstance(colno, int) or not isinstance(end_colno, int):
        return html.escape(code)
    if colno < 0 or end_colno <= colno or colno >= len(code):
        return html.escape(code)
    end_colno = min(end_colno, len(code))
    return (
        html.escape(code[:colno])
        + '<span style="text-decoration:underline 3px #ff5f56; font-weight:700;">'
        + html.escape(code[colno:end_colno])
        + "</span>"
        + html.escape(code[end_colno:])
    )


def _source_context_html(frame: dict[str, Any], *, extra_lines: int = 3) -> str:
    lineno = int(frame.get("lineno") or 1)
    source_lines = _read_source_lines(frame)

    if source_lines:
        start = max(1, lineno - extra_lines)
        end = min(len(source_lines), lineno + extra_lines)
    else:
        start = lineno
        end = lineno

    rows: list[str] = []
    for number in range(start, end + 1):
        if source_lines and 1 <= number <= len(source_lines):
            code = source_lines[number - 1]
        else:
            code = str(frame.get("line", "")) if number == lineno else ""
        is_error = number == lineno
        marker = "❱" if is_error else " "
        background = "#584b16" if is_error else "transparent"
        border = "3px solid #ffd43b" if is_error else "3px solid transparent"
        code_html = _highlight_code(code, frame, is_error)
        rows.append(
            f'<div style="display:flex; background:{background}; border-left:{border};">'
            f'<span style="width:2em; color:#ffd43b; user-select:none;">{marker}</span>'
            f'<span style="width:3.5em; color:#8b949e; text-align:right; padding-right:1em; '
            f'user-select:none;">{number}</span>'
            f'<span style="white-space:pre; color:#f0f3f6;">{code_html or " "}</span>'
            "</div>"
        )
    return (
        '<div style="background:#0d1117; padding:10px 8px; overflow-x:auto; '
        'font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">'
        + "".join(rows)
        + "</div>"
    )


def _frame_panel_html(
    frame: dict[str, Any],
    *,
    title: str | None = None,
) -> str:
    filename = str(frame.get("filename", "unknown file"))
    lineno = int(frame.get("lineno") or 0)
    function = str(frame.get("function", "<unknown>"))
    user_frame = _is_user_frame(frame)

    if title is None:
        title = "Your scene" if user_frame else "ManimGL backend"

    border_color = "#ffd43b" if user_frame else "#586069"
    title_color = "#ffd43b" if user_frame else "#79c0ff"
    context = _source_context_html(frame, extra_lines=3 if user_frame else 2)

    return f"""
    <div style="border:1px solid {border_color}; border-radius:8px; margin:10px 0;
                overflow:hidden; background:#161b22;">
      <div style="padding:9px 12px; border-bottom:1px solid {border_color};">
        <strong style="color:{title_color};">{html.escape(title)}</strong><br>
        <span style="color:#c9d1d9; font-family:monospace;">
          {html.escape(filename)}:{lineno} in {html.escape(function)}
        </span>
      </div>
      {context}
    </div>
    """


def _select_compact_frame(exception: dict[str, Any]) -> dict[str, Any] | None:
    syntax_frame = exception.get("syntax_frame")
    if isinstance(syntax_frame, dict):
        return syntax_frame
    frames = [frame for frame in exception.get("frames", []) if isinstance(frame, dict)]
    user_frames = [frame for frame in frames if _is_user_frame(frame)]
    if user_frames:
        return user_frames[-1]
    return frames[-1] if frames else None


def display_error_report(
    report: dict[str, Any],
    raw_output: str,
    *,
    full_mode: bool,
    scene_name: str,
) -> tuple[str, str]:
    from IPython.display import HTML, display

    final_exception = report.get("exception") or {}
    chain = _exception_chain(final_exception)
    exception_type = str(final_exception.get("type") or "ManimGLRenderError")
    message = str(final_exception.get("message") or "Unknown rendering failure")
    clean_raw = strip_ansi(raw_output).strip()

    sections: list[str] = []
    mode_label = "FULL BACKEND TRACEBACK" if full_mode else "COMPACT ERROR"
    sections.append(
        f"""
        <div style="border:2px solid #f85149; border-radius:10px; overflow:hidden;
                    margin:12px 0; background:#0d1117; color:#f0f3f6;">
          <div style="background:#5a1d1d; padding:12px 14px;">
            <strong style="font-size:17px;">{html.escape(exception_type)} in {html.escape(scene_name)}</strong>
            <span style="float:right; color:#ffb3ad; font-size:12px;">{mode_label}</span>
          </div>
          <div style="padding:12px 14px; color:#ffb3ad; font-family:monospace;">
            {html.escape(message)}
          </div>
        </div>
        """
    )

    if full_mode:
        frame_number = 0
        for chain_index, exception in enumerate(chain, start=1):
            if len(chain) > 1:
                sections.append(
                    f'<div style="color:#d2a8ff; margin-top:14px; font-weight:700;">'
                    f'Exception chain {chain_index}: {html.escape(str(exception.get("type", "Exception")))}'
                    "</div>"
                )
            syntax_frame = exception.get("syntax_frame")
            frames = [frame for frame in exception.get("frames", []) if isinstance(frame, dict)]
            if isinstance(syntax_frame, dict):
                frames.append(syntax_frame)
            for frame in frames[-80:]:
                filename = str(frame.get("filename", ""))
                if filename.endswith(("/error_runner.py", "/runner.py")):
                    continue
                frame_number += 1
                sections.append(
                    _frame_panel_html(
                        frame,
                        title=f"Frame {frame_number} — "
                        + ("Your scene" if _is_user_frame(frame) else "ManimGL backend"),
                    )
                )
    else:
        compact_frame = _select_compact_frame(final_exception)
        if compact_frame is not None:
            sections.append(_frame_panel_html(compact_frame, title="Error in your scene"))
        else:
            sections.append(
                '<div style="padding:12px; color:#ffa198; background:#161b22; '
                'border:1px solid #f85149; border-radius:8px;">'
                "No Python source frame was available. Open raw output below."
                "</div>"
            )

    if clean_raw:
        sections.append(
            f"""
            <details style="margin:14px 0; background:#161b22; border:1px solid #30363d;
                            border-radius:8px; padding:10px 12px;">
              <summary style="cursor:pointer; color:#79c0ff; font-weight:700;">
                Complete raw ManimGL / LaTeX / FFmpeg output
              </summary>
              <pre style="white-space:pre-wrap; overflow-x:auto; color:#c9d1d9;
                          font-size:12px; line-height:1.45;">{html.escape(clean_raw)}</pre>
            </details>
            """
        )

    # LaTeX hint: the most common avoidable failure.
    lowered = (message + " " + clean_raw[-2000:]).lower()
    if "latex" in lowered or "dvisvgm" in lowered or "tex " in lowered:
        sections.append(
            '<div style="margin-top:10px; padding:10px 14px; border-left:5px solid #79c0ff;'
            ' background:#0d1b2a; color:#a5d6ff; font:13px/1.5 monospace;">'
            "Hint: Tex/TexText needs LaTeX, which is optional. Run "
            "<b>mc.install_latex()</b> (slim) or <b>mc.install_latex(slim=False)</b> (full)."
            "</div>"
        )

    sections.append(
        f"""
        <div style="margin-top:14px; padding:12px 14px; border-left:5px solid #f85149;
                    background:#2d1214; color:#ffb3ad; font:700 14px/1.5 monospace;">
          {html.escape(exception_type)}: {html.escape(message)}
        </div>
        """
    )

    display(HTML("".join(sections)))
    return exception_type, message
