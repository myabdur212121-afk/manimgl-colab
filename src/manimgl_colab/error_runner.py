"""Run ManimGL and write structured exception data for the notebook frontend.

This file is executed by runner.py inside the isolated ManimGL environment.
It must stay dependency-free (standard library only).
"""

from __future__ import annotations

import json
import linecache
import os
import sys
import traceback
from pathlib import Path
from typing import Any

REPORT_ENV = "MANIMGL_ERROR_REPORT"
CELL_ENV = "MANIMGL_CELL_FILE"

CONTEXT = 3  # rich.traceback default: extra_lines=3


def _context_lines(filename: str, lineno: int) -> dict[str, Any] | None:
    """rich reads sources with linecache (traceback.py:835); so do we."""
    try:
        all_lines = linecache.getlines(filename)
    except Exception:
        return None
    if not all_lines:
        return None
    start = max(1, lineno - CONTEXT)
    end = min(len(all_lines), lineno + CONTEXT)
    return {
        "start": start,
        "lines": [all_lines[i - 1].rstrip("\n") for i in range(start, end + 1)],
    }


def _frame_to_dict(frame: traceback.FrameSummary) -> dict[str, Any]:
    return {
        "filename": frame.filename,
        "lineno": frame.lineno,
        "function": frame.name,
        "line": frame.line or "",
        "colno": getattr(frame, "colno", None),
        "end_colno": getattr(frame, "end_colno", None),
        "end_lineno": getattr(frame, "end_lineno", None),
        "context": _context_lines(frame.filename, frame.lineno or 1),
    }


def _syntax_frame(error: BaseException) -> dict[str, Any] | None:
    if not isinstance(error, SyntaxError):
        return None
    return {
        "filename": error.filename or os.environ.get(CELL_ENV, "<cell>"),
        "lineno": error.lineno or 1,
        "function": "<module>",
        "line": (error.text or "").rstrip("\n"),
        "colno": max((error.offset or 1) - 1, 0),
        "end_colno": getattr(error, "end_offset", None),
        "end_lineno": getattr(error, "end_lineno", None),
    }


def _serialize_exception(error: BaseException, seen: set[int] | None = None) -> dict[str, Any]:
    if seen is None:
        seen = set()
    if id(error) in seen:
        return {
            "type": type(error).__name__,
            "message": str(error),
            "frames": [],
            "syntax_frame": None,
            "cause": None,
        }
    seen.add(id(error))

    trace = traceback.TracebackException.from_exception(error, capture_locals=False)
    cause = error.__cause__
    relation = "cause"
    if cause is None and error.__context__ is not None and not error.__suppress_context__:
        cause = error.__context__
        relation = "context"

    return {
        "type": type(error).__name__,
        "qualified_type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
        "frames": [_frame_to_dict(frame) for frame in trace.stack],
        "syntax_frame": _syntax_frame(error),
        "relation": relation if cause is not None else None,
        "cause": _serialize_exception(cause, seen) if cause is not None else None,
    }


def _write_report(error: BaseException) -> None:
    destination = os.environ.get(REPORT_ENV)
    if not destination:
        return
    report = {"version": 1, "exception": _serialize_exception(error)}
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    try:
        from manimlib.__main__ import main as manimgl_main

        manimgl_main()
    except BaseException as error:
        _write_report(error)
        traceback.print_exception(type(error), error, error.__traceback__)
        if isinstance(error, KeyboardInterrupt):
            raise SystemExit(130)
        if isinstance(error, SystemExit):
            code = error.code
            raise SystemExit(code if isinstance(code, int) else 1)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
