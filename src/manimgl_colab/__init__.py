"""manimgl-colab — ManimGL (3b1b) on Google Colab with honest CPU/GPU switching.

Quick start::

    import manimgl_colab as mc

    mc.setup()               # one engine for both backends (no LaTeX)
    mc.backend("gpu")        # strict, verified NVIDIA switch (or "cpu")
    mc.install_latex()       # optional; slim=False for the complete set

Then render with the ManimCE-style cell magic::

    %%manimgl -qm MyScene
    from manimlib import *

    class MyScene(Scene):
        ...
"""

from __future__ import annotations

from .autocomplete import enable_autocomplete
from .backends import (
    detect_nvidia_gpu,
    nvenc_available,
    status_report,
    get_backend,
    prepare_gpu,
    probe,
    set_backend,
    status,
)
from .installer import (
    create_virtual_environment,
    download_manimgl,
    install_manimgl,
    install_pip,
    install_system_dependencies,
    patch_manimgl_source,
    prepare_directories,
    setup,
    verify_installation,
)
from .latex import install_latex, is_latex_installed
from .magic import register_magics


def backend(name: str | None = None, *, force: bool = False):
    """Get or set the default backend.

    ``mc.backend()`` returns the current default ("cpu" or "gpu").
    ``mc.backend("gpu")`` switches (with strict NVIDIA verification).
    """
    if name is None:
        return get_backend()
    return set_backend(name, force=force)


def use_gpu(*, force: bool = False):
    """Switch rendering to the NVIDIA GPU (strict: fails loudly without one)."""
    return set_backend("gpu", force=force)


def use_cpu():
    """Switch rendering to the CPU (llvmpipe software renderer)."""
    return set_backend("cpu")


def warm(enable: bool = True):
    """Keep the render engine preloaded for <1s render starts.

    ``mc.warm()`` starts the warm worker (one-time ~engine-import cost);
    ``mc.warm(False)`` stops it.  Renders keep full process isolation —
    each one runs in a fresh fork of the pristine preloaded worker.
    """
    from . import warmup as _warm_module

    if enable:
        return _warm_module.start()  # current default backend
    return _warm_module.stop()


__all__ = [
    "backend",
    "create_virtual_environment",
    "detect_nvidia_gpu",
    "download_manimgl",
    "enable_autocomplete",
    "get_backend",
    "install_latex",
    "install_manimgl",
    "install_pip",
    "install_system_dependencies",
    "is_latex_installed",
    "patch_manimgl_source",
    "prepare_directories",
    "nvenc_available",
    "prepare_gpu",
    "probe",
    "status_report",
    "register_magics",
    "set_backend",
    "setup",
    "status",
    "use_cpu",
    "use_gpu",
    "warm",
    "verify_installation",
]

__version__ = "2.7.1"
