"""ManimCE/rich-style error reports for failed renders.

Visual language follows Manim Community's rich tracebacks:
- a rounded red panel titled "Traceback (most recent call last)"
- syntax-highlighted source context with line numbers and a ❱ marker
- a caret line (^^^^) under the failing expression when columns are known
- library frames collapsed by default ("… N backend frames hidden …"),
  fully expanded with the --ERROR flag
- a final bold  ErrorType: message  strip, exactly like CE's console.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from . import paths
from .ui import ACCENT, BG, BORDER, DIM, MONO, PANEL, RED, TEXT, YELLOW, esc

try:
    from pygments import highlight as _pyg_highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import PythonLexer

    _LEXER = PythonLexer(stripnl=False)
    _FORMATTER = HtmlFormatter(style="monokai", noclasses=True, nowrap=True)

    def _code_html(line: str) -> str:
        rendered = _pyg_highlight(line or " ", _LEXER, _FORMATTER)
        return rendered.rstrip("\n") or "&nbsp;"
except Exception:  # pragma: no cover - pygments is present on Colab
    def _code_html(line: str) -> str:
        return html.escape(line) or "&nbsp;"


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
    """Short notebook-facing exception; the detailed report is shown in HTML."""

    def _render_traceback_(self) -> list[str]:
        return [str(self)]


def strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", text).replace("\r", "\n")


# ----------------------------------------------------------------------
# Report loading (structured JSON from error_runner, with a fallback)
# ----------------------------------------------------------------------

def _fallback_report(raw_output: str) -> dict[str, Any]:
    clean_output = strip_ansi(raw_output)
    exception_matches = list(EXCEPTION_LINE_PATTERN.finditer(clean_output))
    frame_matches = list(TRACEBACK_FRAME_PATTERN.finditer(clean_output))

    if exception_matches:
        final = exception_matches[-1]
        exception_type = final.group("type").split(".")[-1]
        message = final.group("message")
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


# ----------------------------------------------------------------------
# Rendering (rich/ManimCE look)
# ----------------------------------------------------------------------

def _frame_location_html(frame: dict[str, Any], user_frame: bool) -> str:
    filename = str(frame.get("filename", "unknown"))
    display_name = "your cell" if user_frame else filename
    lineno = int(frame.get("lineno") or 0)
    function = str(frame.get("function", "<unknown>"))
    color = YELLOW if user_frame else ACCENT
    return (
        f'<div style="color:{color}; font-size:12px; padding:2px 0;">'
        f"{esc(display_name)}:<b>{lineno}</b> in <b>{esc(function)}</b></div>"
    )


def _caret_row(code: str, frame: dict[str, Any], gutter_width: int) -> str:
    colno = frame.get("colno")
    end_colno = frame.get("end_colno")
    if not isinstance(colno, int) or not isinstance(end_colno, int):
        return ""
    if colno < 0 or end_colno <= colno or colno >= len(code):
        return ""
    end_colno = min(end_colno, len(code))
    pad = "&nbsp;" * colno
    carets = "^" * (end_colno - colno)
    return (
        f'<div style="display:flex;">'
        f'<span style="width:{gutter_width}em;"></span>'
        f'<span style="white-space:pre; color:{RED}; font-weight:700;">'
        f"{pad}{carets}</span></div>"
    )


def _code_block(frame: dict[str, Any], *, context: int) -> str:
    lineno = int(frame.get("lineno") or 1)
    source_lines = _read_source_lines(frame)
    if source_lines:
        start = max(1, lineno - context)
        end = min(len(source_lines), lineno + context)
    else:
        start = end = lineno

    rows: list[str] = []
    for number in range(start, end + 1):
        if source_lines and 1 <= number <= len(source_lines):
            code = source_lines[number - 1]
        else:
            code = str(frame.get("line", "")) if number == lineno else ""
        is_error = number == lineno
        marker = "❱" if is_error else "&nbsp;"
        background = "rgba(248,81,73,0.13)" if is_error else "transparent"
        rows.append(
            f'<div style="display:flex; background:{background};">'
            f'<span style="width:1.4em; color:{RED};">{marker}</span>'
            f'<span style="width:3em; color:{DIM}; text-align:right;'
            f' padding-right:1em; user-select:none;">{number}</span>'
            f'<span style="white-space:pre;">{_code_html(code)}</span>'
            "</div>"
        )
        if is_error:
            caret = _caret_row(code, frame, gutter_width=5.4)
            if caret:
                rows.append(caret)
    return (
        f'<div style="background:{PANEL}; border-radius:6px; padding:8px 10px;'
        f' overflow-x:auto; font:12.5px/1.6 {MONO}; margin:4px 0 10px 0;">'
        + "".join(rows)
        + "</div>"
    )


def _frame_html(frame: dict[str, Any], *, context: int) -> str:
    user_frame = _is_user_frame(frame)
    return _frame_location_html(frame, user_frame) + _code_block(frame, context=context)


def _hidden_frames_html(count: int, frames: list[dict[str, Any]]) -> str:
    inner = "".join(_frame_html(frame, context=1) for frame in frames)
    return f"""
    <details style="margin:6px 0;">
      <summary style="cursor:pointer; color:{DIM}; font-size:12px;">
        … {count} backend frame{'s' if count != 1 else ''} hidden
        (click to expand, or rerun with --ERROR) …
      </summary>
      <div style="margin-top:6px;">{inner}</div>
    </details>
    """


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

    body: list[str] = []
    for chain_index, exception in enumerate(chain, start=1):
        if len(chain) > 1:
            relation = exception.get("relation") or "raised"
            label = ("The above exception was the direct cause of:"
                     if relation == "cause" else
                     "During handling of the above exception, another occurred:")
            if chain_index > 1:
                body.append(
                    f'<div style="color:{DIM}; font-size:12px; margin:10px 0;">'
                    f"{esc(label)}</div>"
                )

        frames = [f for f in exception.get("frames", []) if isinstance(f, dict)]
        frames = [
            f for f in frames
            if not str(f.get("filename", "")).endswith(("/error_runner.py", "/runner.py"))
        ]
        syntax_frame = exception.get("syntax_frame")
        if isinstance(syntax_frame, dict):
            frames.append(syntax_frame)

        if full_mode:
            for frame in frames[-60:]:
                body.append(_frame_html(frame, context=3))
        else:
            hidden: list[dict[str, Any]] = []

            def flush_hidden() -> None:
                if hidden:
                    body.append(_hidden_frames_html(len(hidden), list(hidden)))
                    hidden.clear()

            shown_any = False
            for frame in frames:
                if _is_user_frame(frame):
                    flush_hidden()
                    body.append(_frame_html(frame, context=3))
                    shown_any = True
                else:
                    hidden.append(frame)
            if not shown_any and hidden:
                # No user frame at all: show the deepest backend frame.
                last = hidden.pop()
                if hidden:
                    body.append(_hidden_frames_html(len(hidden), list(hidden)))
                body.append(_frame_html(last, context=3))
            else:
                flush_hidden()

    hints: list[str] = []
    lowered = (message + " " + clean_raw[-2000:]).lower()
    if "latex" in lowered or "dvisvgm" in lowered:
        hints.append(
            "Tex/TexText needs LaTeX (optional): run <b>mc.install_latex()</b> "
            "or <b>mc.install_latex(slim=False)</b>."
        )
    if exception_type == "NameError":
        hints.append("Check spelling, and make sure the object is defined in this cell.")
    hint_html = "".join(
        f'<div style="border-left:3px solid {ACCENT}; background:rgba(88,166,255,0.08);'
        f' color:{ACCENT}; padding:6px 12px; margin:8px 0; border-radius:4px;'
        f' font-size:12px;">💡 {hint}</div>'
        for hint in hints
    )

    raw_section = ""
    if clean_raw:
        raw_section = f"""
        <details style="margin-top:10px;">
          <summary style="cursor:pointer; color:{ACCENT}; font-size:12px;">
            Complete raw ManimGL / LaTeX / FFmpeg output</summary>
          <pre style="white-space:pre-wrap; color:{DIM}; font-size:11px;
                      max-height:320px; overflow:auto; background:{PANEL};
                      border:1px solid {BORDER}; border-radius:6px;
                      padding:10px;">{esc(clean_raw)}</pre>
        </details>
        """

    mode_note = "" if full_mode else (
        f'<span style="color:{DIM}; font-weight:400; font-size:11px;">'
        "&nbsp;— compact · use --ERROR for every frame</span>"
    )

    panel = f"""
    <div style="font-family:{MONO}; max-width:860px; margin:8px 0;">
      <div style="border:1px solid {RED}; border-radius:10px; background:{BG};
                  overflow:hidden;">
        <div style="padding:8px 14px; border-bottom:1px solid {RED};
                    color:{RED}; font-weight:700; font-size:13px;">
          ╭─ Traceback (most recent call last) ─ {esc(scene_name)}{mode_note}
        </div>
        <div style="padding:10px 14px;">
          {''.join(body)}
          {hint_html}
          {raw_section}
        </div>
      </div>
      <div style="margin-top:8px; padding:10px 14px; border-radius:8px;
                  background:rgba(248,81,73,0.12); border:1px solid {RED};
                  color:{RED}; font:700 13.5px/1.5 {MONO};">
        {esc(exception_type)}: {esc(message)}
      </div>
    </div>
    """
    display(HTML(panel))
    return exception_type, message
