"""ManimCE-identical error reports for failed renders.

ManimCE (manim/cli/render/commands.py:118) shows errors with
``error_console.print_exception()`` — i.e. rich's traceback renderer with
default settings.  This module reproduces that renderer (rich/traceback.py)
in HTML, faithfully:

- rounded red panel titled "Traceback (most recent call last)"
- EVERY frame shown, oldest first, "path:lineno in function" headers
- extra_lines=3 of context per frame, syntax highlighted, failing line
  marked with ❱ and a highlighted background
- the exact failing expression red-underlined via Python 3.11+ fine-grained
  column positions (rich: f_code.co_positions / last_instruction)
- "... N frames hidden ..." middle cut beyond max_frames=100
- chained exceptions with rich's exact separator sentences
- final line outside the panel:  bold red ``ErrorType:`` + message with
  numbers/strings colorized (rich's ReprHighlighter)
- locals NOT shown (rich default — and the user's explicit choice)

Below the CE-identical part we keep two manimgl-colab extras: hint strips
and the collapsible raw log.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Optional

from . import paths
from .ui import ACCENT, BG, BORDER, DIM, MONO, PANEL, RED, TEXT, YELLOW, esc

MAX_FRAMES = 100          # rich.traceback default
CONTEXT_LINES = 3         # rich extra_lines default

# ----------------------------------------------------------------------
# Token-level syntax highlighting with exact-range underline
# (equivalent of rich's  syntax.stylize_range(style="traceback.error_range"))
# ----------------------------------------------------------------------

try:
    from pygments.lexers import PythonLexer
    from pygments.styles import get_style_by_name

    _LEXER = PythonLexer(stripnl=False)
    _STYLE = get_style_by_name("monokai")

    def _token_css(token) -> str:
        rules = _STYLE.style_for_token(token)
        css = []
        if rules.get("color"):
            css.append(f"color:#{rules['color']};")
        if rules.get("bold"):
            css.append("font-weight:700;")
        if rules.get("italic"):
            css.append("font-style:italic;")
        return "".join(css)

    def _highlight_line(code: str, underline: Optional[tuple[int, int]]) -> str:
        """Pygments-colored line; chars in [start, end) get rich's
        traceback.error_range style (red underline + bold)."""
        if not code:
            return "&nbsp;"
        pieces: list[str] = []
        for index, token, value in _LEXER.get_tokens_unprocessed(code):
            if not value or value == "\n":
                continue
            segments = [(index, value, False)]
            if underline:
                start, end = underline
                segments = []
                v_start, v_end = index, index + len(value)
                cut_a, cut_b = max(v_start, start), min(v_end, end)
                if cut_a >= cut_b:
                    segments = [(index, value, False)]
                else:
                    if v_start < cut_a:
                        segments.append((v_start, value[: cut_a - v_start], False))
                    segments.append((cut_a, value[cut_a - v_start: cut_b - v_start], True))
                    if cut_b < v_end:
                        segments.append((cut_b, value[cut_b - v_start:], False))
            for _, text_piece, marked in segments:
                if not text_piece:
                    continue
                style = _token_css(token)
                if marked:
                    style += (
                        f"font-weight:700; text-decoration:underline;"
                        f" text-decoration-color:{RED};"
                        f" text-decoration-thickness:2px; text-underline-offset:3px;"
                    )
                pieces.append(f'<span style="{style}">{esc(text_piece)}</span>')
        return "".join(pieces) or "&nbsp;"

except Exception:  # pragma: no cover - pygments is present on Colab
    def _highlight_line(code: str, underline: Optional[tuple[int, int]]) -> str:
        return html.escape(code) or "&nbsp;"


ANSI_PATTERN = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TRACEBACK_FRAME_PATTERN = re.compile(
    r'^\s*File "(?P<filename>.+?)", line (?P<line>\d+), in (?P<function>.+?)\s*$',
    re.MULTILINE,
)
EXCEPTION_LINE_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit)):\s*(?P<message>.*)$",
    re.MULTILINE,
)
# rich's ReprHighlighter essentials: numbers / quoted strings / none-bools
_REPR_NUMBER = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?![\w.])")
_REPR_STRING = re.compile(r"('[^']*'|\"[^\"]*\")")


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
            "context": None,
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


def _source_lines(frame: dict[str, Any]) -> tuple[int, list[str]]:
    """(first_line_number, lines) — prefer the context captured at crash
    time inside the subprocess (rich's linecache approach), else read the
    file, else fall back to the single recorded line."""
    context = frame.get("context")
    if isinstance(context, dict) and context.get("lines"):
        return int(context.get("start", 1)), list(context["lines"])
    filename = str(frame.get("filename", ""))
    lineno = int(frame.get("lineno") or 1)
    try:
        all_lines = Path(filename).read_text(encoding="utf-8").splitlines()
        start = max(1, lineno - CONTEXT_LINES)
        end = min(len(all_lines), lineno + CONTEXT_LINES)
        return start, all_lines[start - 1: end]
    except (OSError, UnicodeError):
        line = str(frame.get("line", ""))
        return lineno, ([line] if line else [])


# ----------------------------------------------------------------------
# Rendering — faithful port of rich/traceback.py:_render_stack
# ----------------------------------------------------------------------

def _underline_for(frame: dict[str, Any], number: int, code: str) -> Optional[tuple[int, int]]:
    """rich traceback.py:863-885 — per-line slice of the instruction span,
    skipping indentation when the span starts at column 0."""
    colno = frame.get("colno")
    end_colno = frame.get("end_colno")
    lineno = int(frame.get("lineno") or 0)
    end_lineno = frame.get("end_lineno") or lineno
    if not isinstance(colno, int) or not isinstance(end_colno, int):
        return None
    if number < lineno or number > int(end_lineno):
        return None
    col1 = colno if number == lineno else 0
    col2 = end_colno if number == int(end_lineno) else len(code)
    if col1 == 0:
        col1 = len(code) - len(code.lstrip())
    col2 = min(col2, len(code))
    if col2 <= col1:
        return None
    return (col1, col2)


def _frame_header(frame: dict[str, Any], user_frame: bool) -> str:
    lineno = int(frame.get("lineno") or 0)
    function = str(frame.get("function", "<unknown>"))
    if user_frame:
        location = "Your cell"
        color = YELLOW
    else:
        location = str(frame.get("filename", "unknown"))
        color = ACCENT
    return (
        f'<div style="font-size:12px; padding:6px 0 2px 0; color:{TEXT};">'
        f'<span style="color:{color};">{esc(location)}</span>'
        f'<span style="color:{DIM};">:</span>'
        f'<b style="color:{TEXT};">{lineno}</b>'
        f'<span style="color:{DIM};"> in </span>'
        f'<b style="color:{ACCENT};">{esc(function)}</b></div>'
    )


def _frame_html(frame: dict[str, Any]) -> str:
    user_frame = _is_user_frame(frame)
    lineno = int(frame.get("lineno") or 1)
    start, lines = _source_lines(frame)

    rows: list[str] = []
    for offset, code in enumerate(lines):
        number = start + offset
        is_error = number == lineno
        marker = "❱" if is_error else "&nbsp;"
        background = "rgba(248,81,73,0.13)" if is_error else "transparent"
        underline = _underline_for(frame, number, code)
        rows.append(
            f'<div style="display:flex; background:{background};">'
            f'<span style="width:1.4em; color:{RED}; flex:none;">{marker}</span>'
            f'<span style="width:3em; color:{DIM}; text-align:right;'
            f' padding-right:1em; user-select:none; flex:none;">{number}</span>'
            f'<span style="white-space:pre;">{_highlight_line(code, underline)}</span>'
            "</div>"
        )
    if not rows:
        rows.append(
            f'<div style="color:{DIM};">(source not available)</div>'
        )
    return _frame_header(frame, user_frame) + (
        f'<div style="background:{PANEL}; border-radius:6px; padding:8px 10px;'
        f' overflow-x:auto; font:12.5px/1.6 {MONO}; margin:2px 0 8px 0;">'
        + "".join(rows)
        + "</div>"
    )


def _repr_highlight(message: str) -> str:
    """rich's ReprHighlighter for the final message: colorize numbers and
    quoted strings (applied on escaped text)."""
    escaped = esc(message)
    escaped = _REPR_STRING.sub(
        rf'<span style="color:#a5d6ff;">\1</span>', escaped)
    escaped = _REPR_NUMBER.sub(
        rf'<span style="color:#79c0ff;">\1</span>', escaped)
    return escaped


def display_error_report(
    report: dict[str, Any],
    raw_output: str,
    *,
    full_mode: bool = False,   # False: user frames only · True (--ERROR): full CE chain
    scene_name: str = "",
) -> tuple[str, str]:
    from IPython.display import HTML, display

    final_exception = report.get("exception") or {}
    chain = _exception_chain(final_exception)
    exception_type = str(final_exception.get("type") or "ManimGLRenderError")
    message = str(final_exception.get("message") or "Unknown rendering failure")
    clean_raw = strip_ansi(raw_output).strip()

    body: list[str] = []
    hidden_total = 0
    for chain_index, exception in enumerate(chain, start=1):
        if chain_index > 1:
            # the PREVIOUS entry's relation describes how it links forward
            previous = chain[chain_index - 2]
            relation = previous.get("relation") or "context"
            label = (
                "The above exception was the direct cause of the following exception:"
                if relation == "cause" else
                "During handling of the above exception, another exception occurred:"
            )
            body.append(
                f'<div style="color:{TEXT}; font-style:italic; font-size:12px;'
                f' margin:14px 0;">{esc(label)}</div>'
            )

        frames = [f for f in exception.get("frames", []) if isinstance(f, dict)]
        frames = [
            f for f in frames
            if not str(f.get("filename", "")).endswith(("/error_runner.py", "/runner.py"))
        ]
        syntax_frame = exception.get("syntax_frame")
        if isinstance(syntax_frame, dict):
            frames.append(syntax_frame)

        if not full_mode:
            # Compact default: only the user's own frames + the error line.
            # The full ManimCE-identical chain stays behind --ERROR.
            user_frames = [f for f in frames if _is_user_frame(f)]
            if not user_frames and frames:
                user_frames = [frames[-1]]   # no user frame: show the raiser
            hidden_total += len(frames) - len(user_frames)
            for frame in user_frames:
                body.append(_frame_html(frame))
            continue

        # rich max_frames middle cut (traceback.py:785-805)
        if MAX_FRAMES and len(frames) > MAX_FRAMES:
            head = frames[: MAX_FRAMES // 2]
            tail = frames[len(frames) - MAX_FRAMES // 2:]
            hidden_count = len(frames) - len(head) - len(tail)
            for frame in head:
                body.append(_frame_html(frame))
            body.append(
                f'<div style="text-align:center; color:{RED}; font-size:12px;'
                f' margin:8px 0;">… {hidden_count} frames hidden …</div>'
            )
            for frame in tail:
                body.append(_frame_html(frame))
        else:
            for frame in frames:
                body.append(_frame_html(frame))

    if not full_mode and hidden_total:
        body.append(
            f'<div style="text-align:center; color:{DIM}; font-size:11.5px;'
            f' margin:6px 0 2px 0;">… {hidden_total} library frame'
            f'{"s" if hidden_total != 1 else ""} hidden — rerun with'
            f' <b style="color:{ACCENT};">--ERROR</b> for the full'
            f' ManimCE-style traceback …</div>'
        )

    # ------------------------------------------------------------------
    # manimgl-colab extras (below the CE-identical part)
    # ------------------------------------------------------------------
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

    panel = f"""
    <div style="font-family:{MONO}; max-width:900px; margin:8px 0;">
      <div style="border:1px solid {RED}; border-radius:12px; background:{BG};
                  overflow:hidden;">
        <div style="padding:7px 14px; text-align:center;
                    color:{RED}; font-weight:700; font-size:13px;">
          ─── Traceback <span style="color:{DIM}; font-weight:400;">(most
          recent call last)</span> ───
        </div>
        <div style="padding:2px 14px 10px 14px;">
          {''.join(body)}
        </div>
      </div>
      <div style="margin-top:10px; font:13.5px/1.5 {MONO};">
        <span style="color:{RED}; font-weight:700;">{esc(exception_type)}:</span>
        <span style="color:{TEXT};">{_repr_highlight(message)}</span>
      </div>
      {hint_html}
      {raw_section}
    </div>
    """
    display(HTML(panel))
    return exception_type, message
