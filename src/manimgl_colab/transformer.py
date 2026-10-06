"""Input transformer: allow comments/docstrings ABOVE the %%manimgl line.

IPython only recognises a cell magic on the very first line. This cleanup
transformer runs BEFORE magic parsing and hoists a ``%%manimgl`` line to the
top when everything above it is only blank lines, ``#`` comments, or a
triple-quoted string block. The hoisted-over lines are kept (they become the
first lines of the cell body, which is valid Python).
"""

from __future__ import annotations

import re

MAGIC_NAMES = ("%%manimgl",)
_TRIPLE = ('"""', "'''")


def _is_skippable_prefix(lines: list[str]) -> bool:
    """True when ``lines`` contain only blanks, comments, or string blocks."""
    in_string: str | None = None
    for line in lines:
        stripped = line.strip()
        if in_string is not None:
            if in_string in stripped:
                remainder = stripped.split(in_string, 1)[1].strip()
                in_string = None
                if remainder and not remainder.startswith("#"):
                    return False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        opened = None
        for quote in _TRIPLE:
            if stripped.startswith(quote):
                opened = quote
                break
        if opened is None:
            return False
        body = stripped[len(opened):]
        if opened in body:
            remainder = body.split(opened, 1)[1].strip()
            if remainder and not remainder.startswith("#"):
                return False
        else:
            in_string = opened
    return in_string is None


def hoist_manimgl_magic(lines: list[str]) -> list[str]:
    """IPython cleanup transformer (list[str] -> list[str])."""
    try:
        magic_index = next(
            index for index, line in enumerate(lines)
            if line.lstrip().startswith(MAGIC_NAMES)
        )
    except StopIteration:
        return lines
    if magic_index == 0:
        return lines
    if not _is_skippable_prefix(lines[:magic_index]):
        return lines
    magic_line = lines[magic_index].lstrip()
    if not magic_line.endswith("\n"):
        magic_line += "\n"
    reordered = [magic_line, *lines[:magic_index], *lines[magic_index + 1:]]
    return reordered


def register_transformer() -> None:
    from IPython import get_ipython

    ipython = get_ipython()
    if ipython is None:
        return
    transforms = getattr(ipython, "input_transformers_cleanup", None)
    if transforms is None:
        return
    if not any(getattr(t, "__name__", "") == "hoist_manimgl_magic" for t in transforms):
        transforms.append(hoist_manimgl_magic)
