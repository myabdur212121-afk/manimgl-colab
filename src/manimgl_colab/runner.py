"""Headless EGL bootstrap executed INSIDE the isolated ManimGL environment.

Responsibilities:
1. Configure pyglet/EGL for headless rendering.
2. Print the REAL ``GL_RENDERER`` the moment the OpenGL context is created,
   so every render proves which hardware actually did the work.
3. Strict mode: when the GPU backend was requested but the created context
   is not a real NVIDIA renderer, abort loudly — never silently render on
   the CPU while claiming GPU.
4. Delegate to error_runner for structured exception reports.
"""

from __future__ import annotations

import os
import runpy
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated.*",
    category=UserWarning,
)

os.environ.setdefault("PYGLET_HEADLESS", "true")
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import pyglet  # noqa: E402

pyglet.options["headless"] = True
pyglet.options["headless_device"] = 0
pyglet.options["shadow_window"] = False

import moderngl  # noqa: E402

_NVIDIA_TOKENS = (
    "nvidia", "tesla", "quadro", "geforce", "rtx", "t4", "a100", "l4", "v100", "p100",
)
_original_create = moderngl.create_standalone_context
_proof_printed = False


def _create_standalone_context(*args, **kwargs):
    global _proof_printed
    kwargs.setdefault("backend", "egl")
    context = _original_create(*args, **kwargs)
    renderer = str(context.info.get("GL_RENDERER", "unknown"))
    vendor = str(context.info.get("GL_VENDOR", ""))
    version = str(context.info.get("GL_VERSION", ""))

    if not _proof_printed:
        print(f"[manimgl-colab] GL_RENDERER: {renderer}", flush=True)
        print(f"[manimgl-colab] GL_VERSION: {version}", flush=True)
        _proof_printed = True

    expectation = os.environ.get("MANIMGL_COLAB_EXPECT", "")
    combined = (renderer + " " + vendor).lower()
    is_nvidia = any(token in combined for token in _NVIDIA_TOKENS)
    if expectation == "gpu" and not is_nvidia:
        context.release()
        raise RuntimeError(
            "GPU backend was requested, but the OpenGL context is "
            f"'{renderer}' (not NVIDIA). Strict mode refuses a hidden CPU "
            "fallback. Fix: select a GPU runtime and run mc.backend('gpu'), "
            "or render with --cpu."
        )
    return context


moderngl.create_standalone_context = _create_standalone_context

ERROR_RUNNER = Path(__file__).resolve().parent / "error_runner.py"
runpy.run_path(str(ERROR_RUNNER), run_name="__main__")
