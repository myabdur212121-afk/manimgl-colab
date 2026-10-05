"""Colab editor bridge: IDE autocomplete and import resolution for manimlib.

The render environment stays isolated. A ``.pth`` dependency bridge plus a
symlink let Colab's language server resolve ``from manimlib import *``
without replacing Colab's own IPython installation.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import site
import subprocess
import sys
import warnings
from pathlib import Path

from . import paths


def enable_autocomplete() -> dict[str, object]:
    """Enable or refresh ManimGL IDE resolution and runtime completions."""
    if not paths.ENV_PYTHON.exists() or not (paths.SOURCE_DIR / "manimlib").exists():
        raise FileNotFoundError("ManimGL is not installed. Run mc.setup() first.")

    kernel_site = Path(site.getsitepackages()[0])
    env_site = Path(
        subprocess.check_output(
            [str(paths.ENV_PYTHON), "-c", "import site; print(site.getsitepackages()[0])"],
            text=True,
        ).strip()
    )
    source_manimlib = (paths.SOURCE_DIR / "manimlib").resolve()

    pth_file = kernel_site / "manimgl_colab_autocomplete.pth"
    link = kernel_site / "manimlib"
    try:
        pth_file.write_text(str(env_site) + "\n", encoding="utf-8")
        if link.is_symlink():
            if link.resolve() != source_manimlib:
                link.unlink()
                link.symlink_to(source_manimlib, target_is_directory=True)
        elif link.exists():
            if link.resolve() != source_manimlib:
                raise RuntimeError(
                    f"A different real manimlib package already exists: {link}"
                )
        else:
            link.symlink_to(source_manimlib, target_is_directory=True)
    except PermissionError:
        print("No permission to write into site-packages; using sys.path only.")
        pth_file = None
        link = None

    for path in (str(env_site), str(paths.SOURCE_DIR)):
        if path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()

    os.environ["PYGLET_HEADLESS"] = "true"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
    warnings.filterwarnings(
        "ignore", message=r"pkg_resources is deprecated.*", category=UserWarning
    )

    import pyglet

    pyglet.options["headless"] = True
    pyglet.options["headless_device"] = 0
    pyglet.options["shadow_window"] = False

    existing = sys.modules.get("manimlib")
    if existing is not None:
        existing_file = str(getattr(existing, "__file__", ""))
        if not existing_file.startswith(str(paths.SOURCE_DIR)):
            for name in list(sys.modules):
                if name == "manimlib" or name.startswith("manimlib."):
                    sys.modules.pop(name, None)

    manimlib = importlib.import_module("manimlib")
    symbols = {
        name: getattr(manimlib, name) for name in dir(manimlib) if not name.startswith("_")
    }

    try:
        from IPython import get_ipython

        ipython = get_ipython()
        if ipython is not None:
            ipython.user_ns.update(symbols)
    except ImportError:
        pass

    specification = importlib.util.find_spec("manimlib")
    result: dict[str, object] = {
        "module": str(getattr(manimlib, "__file__", "")),
        "resolved": str(specification.origin if specification else ""),
        "symbols": len(symbols),
        "pth_file": str(pth_file) if pth_file else None,
        "package_link": str(link) if link else None,
    }
    print("ManimGL editor bridge enabled.")
    print(f"Resolved module: {result['resolved']}")
    print(f"Autocomplete symbols: {result['symbols']}")
    return result
