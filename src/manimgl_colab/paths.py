"""Central path configuration for manimgl-colab.

Every path lives under ROOT (default /content on Google Colab).
Override with the MANIMGL_COLAB_ROOT environment variable for testing.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("MANIMGL_COLAB_ROOT", "/content"))

# One isolated environment + one pinned ManimGL source for BOTH backends.
ENV_DIR = ROOT / "manimgl-env"
SOURCE_DIR = ROOT / "manimGL"
ENV_PYTHON = ENV_DIR / "bin/python"
ENV_PIP = ENV_DIR / "bin/pip"

VIDEO_DIR = ROOT / "manimgl_videos"
SCENE_FILE = ROOT / "manimgl_cell.py"
ERROR_REPORT = ROOT / "manimgl_error_report.json"
BACKEND_FILE = ROOT / "manimgl_backend.json"
GET_PIP_FILE = ROOT / "get-pip.py"

# NVIDIA userspace libraries extracted locally (never replacing the driver).
NVIDIA_ROOT = ROOT / "manimgl-nvidia-root"
NVIDIA_DEBS = ROOT / "manimgl-nvidia-debs"
NVIDIA_EGL_JSON = ROOT / "manimgl_nvidia_egl_vendor.json"
GPU_STATE = ROOT / "manimgl_gpu_state.json"

RUNTIME_DIR = Path("/tmp/runtime-colab")

PACKAGE_DIR = Path(__file__).resolve().parent
RUNNER = PACKAGE_DIR / "runner.py"
ERROR_RUNNER = PACKAGE_DIR / "error_runner.py"

MANIMGL_GIT_URL = "https://github.com/3b1b/manim.git"
MANIMGL_GIT_TAG = "v1.7.2"

MESA_VENDOR_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
