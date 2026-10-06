"""Colorful file-viewing and safe editing shortcuts for Google Colab."""

from __future__ import annotations

import hashlib
import html
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


from . import paths as _paths

BACKUP_ROOT = _paths.ROOT / "manimgl_file_backups"
DEFAULT_CONTEXT = 8
MAX_CONTEXT = 100
MAX_PREVIEW_BYTES = 10 * 1024 * 1024

TRACEBACK_REFERENCE = re.compile(
    r'^\s*File\s+["\'](?P<path>.+?)["\']\s*,\s*line\s+(?P<line>\d+)',
    re.IGNORECASE,
)
PATH_LINE_REFERENCE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?:\s+in\s+.+)?\s*$",
    re.IGNORECASE,
)
PATH_SPACE_LINE_REFERENCE = re.compile(
    r"^(?P<path>.+?)\s+(?P<line>\d+)(?:\s+in\s+.+)?\s*$",
    re.IGNORECASE,
)


class FileToolError(RuntimeError):
    pass


def _parse_options(line: str) -> tuple[str, int]:
    """Extract ``--context N`` while preserving the remaining reference."""
    tokens = shlex.split(line)
    context = DEFAULT_CONTEXT
    remaining: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token == "--context":
            if index + 1 >= len(tokens):
                raise ValueError("--context must be followed by a number.")
            try:
                context = int(tokens[index + 1])
            except ValueError as error:
                raise ValueError("--context must be an integer, such as 12.") from error
            if not 0 <= context <= MAX_CONTEXT:
                raise ValueError(f"--context must be between 0 and {MAX_CONTEXT}.")
            index += 2
            continue
        remaining.append(token)
        index += 1

    return " ".join(remaining).strip(), context


def parse_file_reference(reference: str) -> tuple[str, int | None]:
    """Parse a path, ``path:line``, or a copied Python traceback header."""
    reference = reference.strip()
    if not reference:
        raise ValueError(
            "A file path is required. Example: "
            "%openfile /content/manimGL/manimlib/scene/scene.py:114"
        )

    match = TRACEBACK_REFERENCE.search(reference)
    if match:
        return match.group("path"), int(match.group("line"))

    match = PATH_LINE_REFERENCE.match(reference)
    if match:
        return match.group("path").strip('"\''), int(match.group("line"))

    match = PATH_SPACE_LINE_REFERENCE.match(reference)
    if match and Path(match.group("path").strip('"\'')).suffix:
        return match.group("path").strip('"\''), int(match.group("line"))

    # Remove a copied Rich-style suffix such as " in construct" when no line
    # was supplied separately.
    reference = re.sub(r"\s+in\s+[A-Za-z_][\w.<>]*\s*$", "", reference)
    return reference.strip('"\''), None


def _candidate_paths(path_text: str) -> list[Path]:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return [path]
    return [
        Path.cwd() / path,
        _paths.ROOT / path,
        _paths.SOURCE_DIR / path,
        _paths.ROOT / "manim-env-setup" / path,
        _paths.ROOT / "manim-setup" / path,
    ]


def resolve_file_path(path_text: str, *, must_exist: bool = True) -> Path:
    candidates = _candidate_paths(path_text)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    fallback = candidates[0].resolve()
    if not must_exist:
        return fallback

    suggestions = find_file_suggestions(Path(path_text).name)
    suggestion_text = ""
    if suggestions:
        suggestion_text = "\n\nPossible matches:\n" + "\n".join(
            f"  - {path}" for path in suggestions
        )
    raise FileNotFoundError(f"File not found: {path_text}{suggestion_text}")


def find_file_suggestions(filename: str, limit: int = 8) -> list[Path]:
    if not filename or filename in (".", ".."):
        return []

    roots = [
        _paths.SOURCE_DIR,
        _paths.ROOT / "manim-env-setup",
        _paths.ROOT / "manim-setup",
        _paths.ENV_DIR,
    ]
    matches: list[Path] = []

    for root in roots:
        if not root.exists():
            continue
        for directory, _, files in os.walk(root):
            if filename in files:
                matches.append((Path(directory) / filename).resolve())
                if len(matches) >= limit:
                    return matches
    return matches


def _backup_directory(path: Path) -> Path:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    return BACKUP_ROOT / digest


def create_backup(path: Path, *, label: str = "open") -> Path:
    """Create a timestamped backup before exposing a file for editing."""
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Cannot back up missing file: {path}")

    destination_directory = _backup_directory(path)
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = destination_directory / f"{timestamp}__{label}__{path.name}"
    shutil.copy2(path, backup)

    metadata = destination_directory / "original_path.txt"
    metadata.write_text(str(path.resolve()), encoding="utf-8")
    return backup


def list_backups(path: Path) -> list[Path]:
    directory = _backup_directory(path)
    if not directory.exists():
        return []
    return sorted(
        [item for item in directory.iterdir() if item.is_file() and item.name != "original_path.txt"],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _lexer_and_formatter(path: Path):
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import TextLexer, get_lexer_for_filename
    from pygments.util import ClassNotFound

    try:
        lexer = get_lexer_for_filename(path.name)
    except ClassNotFound:
        lexer = TextLexer()
    return lexer, HtmlFormatter(nowrap=True, style="monokai")


def _highlight_line(code: str, lexer: Any, formatter: Any) -> str:
    from pygments import highlight

    return highlight(code or " ", lexer, formatter).rstrip("\n")


def _preview_html(path: Path, target_line: int | None, context: int) -> str:
    from pygments.formatters import HtmlFormatter

    if path.stat().st_size > MAX_PREVIEW_BYTES:
        raise FileToolError(
            f"The file is larger than {MAX_PREVIEW_BYTES // (1024 * 1024)} MB; "
            "preview was skipped for safety."
        )

    try:
        source_lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise FileToolError(f"The file is not UTF-8 text: {path}") from error

    total_lines = len(source_lines)
    if target_line is not None:
        if target_line < 1 or target_line > max(total_lines, 1):
            raise ValueError(
                f"Line {target_line} is outside this file (1–{total_lines})."
            )
        start = max(1, target_line - context)
        end = min(total_lines, target_line + context)
    else:
        start = 1
        end = min(total_lines, 40)

    lexer, formatter = _lexer_and_formatter(path)
    rows: list[str] = []

    for number in range(start, end + 1):
        code = source_lines[number - 1] if source_lines else ""
        selected = number == target_line
        background = "#0b3d5c" if selected else "transparent"
        border = "3px solid #58a6ff" if selected else "3px solid transparent"
        number_color = "#7ee787" if selected else "#8b949e"
        marker = "●" if selected else " "
        highlighted = _highlight_line(code, lexer, formatter)

        rows.append(
            f'<div style="display:flex; background:{background}; border-left:{border};">'
            f'<span style="width:2em; color:#58a6ff; user-select:none;">{marker}</span>'
            f'<span style="width:4em; color:{number_color}; text-align:right; padding-right:1em; '
            f'user-select:none;">{number}</span>'
            f'<span style="white-space:pre; color:#f0f3f6;">{highlighted}</span>'
            "</div>"
        )

    css = HtmlFormatter(style="monokai").get_style_defs(".source-preview")
    target_text = str(target_line) if target_line is not None else "not specified"

    return f"""
    <style>{css}</style>
    <div style="border:1px solid #58a6ff; border-radius:10px; overflow:hidden;
                margin:12px 0; background:#0d1117; color:#f0f3f6;">
      <div style="padding:12px 14px; background:#0b253a; border-bottom:1px solid #58a6ff;">
        <strong style="color:#79c0ff; font-size:16px;">File Viewer</strong><br>
        <span style="color:#c9d1d9;"><b>Name:</b> {html.escape(path.name)}</span><br>
        <span style="color:#8b949e; font-family:monospace;"><b>Path:</b> {html.escape(str(path))}</span><br>
        <span style="color:#7ee787;"><b>Target line:</b> {html.escape(target_text)}</span>
        <span style="color:#8b949e; float:right;">{total_lines} lines</span>
      </div>
      <div class="source-preview" style="padding:10px 8px; overflow-x:auto;
           font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">
        {''.join(rows) if rows else '<span style="color:#8b949e;">Empty file</span>'}
      </div>
    </div>
    """


def register_file_magics() -> None:
    """Register ``%openfile``, ``%restorefile``, and ``%filebackups``."""
    from IPython import get_ipython
    from IPython.display import HTML, display

    try:
        from google.colab import files
    except ImportError:  # Outside Colab: previews still work, no editor panel.
        files = None

    ipython = get_ipython()
    if ipython is None:
        raise RuntimeError("File shortcuts require Google Colab or IPython.")

    def openfile_magic(line: str) -> None:
        reference, context = _parse_options(line)
        path_text, target_line = parse_file_reference(reference)
        path = resolve_file_path(path_text)

        if not path.is_file():
            raise FileToolError(f"Not a regular file: {path}")

        backup = create_backup(path, label="before_open")
        try:
            display(HTML(_preview_html(path, target_line, context)))
        except FileToolError as warning:
            print(f"Preview warning: {warning}")

        print(f"Backup created: {backup}")
        print(f"Opening editable Colab panel: {path}")
        if target_line is not None:
            print(f"Target line: {target_line}")

        if files is None:
            print("(Not running in Google Colab: editor panel unavailable.)")
        else:
            try:
                files.view(str(path))
            except Exception as error:
                print(f"Colab editor could not be opened automatically: {error}")
            print("Use the Files panel on the left and open this path manually:")
            print(path)

    def restorefile_magic(line: str) -> None:
        reference, _ = _parse_options(line)
        path_text, _ = parse_file_reference(reference)
        path = resolve_file_path(path_text, must_exist=False)
        backups = list_backups(path)
        if not backups:
            raise FileNotFoundError(f"No backups were found for: {path}")

        backup_to_restore = backups[0]
        if path.exists():
            current_backup = create_backup(path, label="before_restore")
            print(f"Current version backed up: {current_backup}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(backup_to_restore, path)
        print(f"Restored: {path}")
        print(f"From: {backup_to_restore}")
        files.view(str(path))

    def filebackups_magic(line: str) -> None:
        reference, _ = _parse_options(line)
        path_text, _ = parse_file_reference(reference)
        path = resolve_file_path(path_text, must_exist=False)
        backups = list_backups(path)

        if not backups:
            print(f"No backups found for: {path}")
            return

        print(f"Backups for: {path}")
        for index, backup in enumerate(backups, start=1):
            size_kb = backup.stat().st_size / 1024
            print(f"{index:2}. {backup.name}  ({size_kb:.1f} KB)")

    ipython.register_magic_function(openfile_magic, magic_kind="line", magic_name="openfile")
    ipython.register_magic_function(
        restorefile_magic,
        magic_kind="line",
        magic_name="restorefile",
    )
    ipython.register_magic_function(
        filebackups_magic,
        magic_kind="line",
        magic_name="filebackups",
    )




if __name__ == "__main__":
    register_file_magics()
