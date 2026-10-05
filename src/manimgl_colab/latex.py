"""Optional LaTeX installation — nothing TeX-related is installed by setup().

Two modes:

- ``install_latex()`` / ``install_latex(slim=True)``: fast, smaller download.
  Installs the core TeX Live collections and switches ManimGL's default
  TeX preamble to a slim one that only needs those collections, so
  ``Tex``/``TexText`` work immediately.
- ``install_latex(slim=False)``: the complete set (adds texlive-latex-extra,
  texlive-fonts-extra, tipa, ...) and restores ManimGL's original full
  preamble (dsfont, calligra, wasysym, pifont, ...).

Switching between the two later is safe; the original template is backed up.
"""

from __future__ import annotations

import shutil

from . import paths
from .shell import apt, run

SLIM_PACKAGES = [
    "texlive-latex-base",
    "texlive-latex-recommended",
    "texlive-fonts-recommended",
    "texlive-science",
    "dvisvgm",
    "cm-super",
]

FULL_EXTRA_PACKAGES = [
    "texlive-latex-extra",
    "texlive-fonts-extra",
]

SLIM_PREAMBLE = """\
    \\usepackage[english]{babel}
    \\usepackage[utf8]{inputenc}
    \\usepackage[T1]{fontenc}
    \\usepackage{amsmath}
    \\usepackage{amssymb}
    \\usepackage{mathrsfs}
    \\usepackage{physics}
    \\usepackage{xcolor}
    \\usepackage{microtype}
    \\linespread{1}
"""


def _templates_file():
    return paths.SOURCE_DIR / "manimlib/tex_templates.yml"


def _backup_file():
    return paths.SOURCE_DIR / "manimlib/tex_templates.yml.original"


def _swap_default_preamble(slim: bool) -> None:
    """Replace (or restore) the preamble of the 'default' template."""
    templates = _templates_file()
    backup = _backup_file()
    if not templates.exists():
        print("tex_templates.yml not found; skipping template adjustment.")
        return
    if not backup.exists():
        shutil.copy2(templates, backup)

    original = backup.read_text(encoding="utf-8")
    if not slim:
        templates.write_text(original, encoding="utf-8")
        print("Restored ManimGL's original full TeX preamble.")
        return

    lines = original.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    swapped = False
    while index < len(lines):
        line = lines[index]
        output.append(line)
        if not swapped and line.rstrip() == "default:":
            # Copy description/compiler lines, replace the preamble block.
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("preamble:"):
                output.append(lines[index])
                index += 1
            if index < len(lines):
                output.append(lines[index])  # 'preamble: |-'
                index += 1
                while index < len(lines) and (
                    lines[index].startswith("    ") or lines[index].strip() == ""
                ):
                    if lines[index].strip() == "" and index + 1 < len(lines) and not lines[
                        index + 1
                    ].startswith("    "):
                        break
                    index += 1
                output.append(SLIM_PREAMBLE)
                swapped = True
            continue
        index += 1

    if swapped:
        templates.write_text("".join(output), encoding="utf-8")
        print("Default TeX preamble switched to the slim set.")
    else:
        print("Could not locate the default template; preamble left unchanged.")


def is_latex_installed() -> bool:
    return shutil.which("latex") is not None and shutil.which("dvisvgm") is not None


def install_latex(*, slim: bool = True) -> None:
    """Install optional LaTeX support for Tex/TexText objects.

    Args:
        slim: True (default) = smaller/faster install with a slim default
            preamble. False = complete install with the original preamble.
    """
    mode = "slim" if slim else "full"
    print(f"Installing optional LaTeX ({mode} mode)...", flush=True)

    packages = list(SLIM_PACKAGES)
    if not slim:
        packages += FULL_EXTRA_PACKAGES

    apt(["update", "-qq"], quiet=True)
    apt(["install", "-y", "-qq", "--no-install-recommends", *packages], quiet=True)

    if not slim:
        # tipa ships as its own Debian package on some images.
        try:
            apt(["install", "-y", "-qq", "tipa"], quiet=True)
        except RuntimeError:
            print("(tipa package unavailable; texlive-fonts-extra may already provide it)")

    _swap_default_preamble(slim)

    run(["mktexlsr"], quiet=True, capture=True, check=False)
    run(["latex", "--version"], quiet=True, capture=True)
    run(["dvisvgm", "--version"], quiet=True, capture=True)

    print(f"LaTeX ({mode}) installed successfully. Tex/TexText are now available.")
    if slim:
        print("Need dsfont/calligra/wasysym/pifont etc.? Run mc.install_latex(slim=False).")
