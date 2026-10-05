"""Safe, idempotent ManimGL installation for a fresh Google Colab runtime.

Design:
- ONE isolated environment (ROOT/manimgl-env) and ONE pinned ManimGL clone
  (ROOT/manimGL, tag v1.7.2) serve BOTH the CPU and the GPU backend.
  Switching backends never reinstalls anything; it only changes the
  render-time environment variables.
- ManimGL's newer IPython dependency never touches Colab's own IPython.
- No LaTeX is installed here. Use install_latex() when you need Tex.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request

from . import paths
from .shell import apt, run

SYSTEM_PACKAGES = [
    "git",
    "curl",
    "ffmpeg",
    "build-essential",
    "python3-dev",
    "pkg-config",
    "libcairo2-dev",
    "libpango1.0-dev",
    "libgl1",
    "libegl1",
    "libgles2",
    "libgl1-mesa-dri",
    "libegl-mesa0",
    "fonts-cmu",
    "fonts-noto-core",
]


def install_system_dependencies() -> None:
    """Install FFmpeg, EGL/Mesa graphics libraries, build tools, and fonts."""
    print("\n[1/7] Installing system dependencies...", flush=True)
    apt(["update", "-qq"], quiet=True)
    try:
        apt(["install", "-y", "-qq", *SYSTEM_PACKAGES], quiet=True)
    except RuntimeError:
        # fonts-cmu is unavailable on some images; retry without it.
        packages = [name for name in SYSTEM_PACKAGES if name != "fonts-cmu"]
        apt(["install", "-y", "-qq", *packages], quiet=True)
    print("System dependencies ready.")


def create_virtual_environment(*, force: bool = False) -> None:
    """Create the isolated environment without invoking broken ensurepip."""
    print("\n[2/7] Creating the isolated Python environment...", flush=True)
    if force and paths.ENV_DIR.exists():
        shutil.rmtree(paths.ENV_DIR)
    if paths.ENV_PYTHON.exists():
        print(f"Environment already exists: {paths.ENV_DIR}")
        return
    if paths.ENV_DIR.exists():
        shutil.rmtree(paths.ENV_DIR)
    run([sys.executable, "-m", "venv", "--without-pip", str(paths.ENV_DIR)])


def install_pip() -> None:
    """Install pip manually inside the isolated environment."""
    print("\n[3/7] Installing pip inside the isolated environment...", flush=True)
    if paths.ENV_PIP.exists():
        print(f"pip already exists: {paths.ENV_PIP}")
        return
    if not paths.ENV_PYTHON.exists():
        raise FileNotFoundError("The virtual environment does not exist.")
    urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", paths.GET_PIP_FILE)
    run([str(paths.ENV_PYTHON), str(paths.GET_PIP_FILE)], capture=True, quiet=True)
    print("pip installed.")


def download_manimgl(*, force: bool = False) -> None:
    """Clone the official 3Blue1Brown ManimGL repository (pinned tag)."""
    print(f"\n[4/7] Downloading ManimGL {paths.MANIMGL_GIT_TAG}...", flush=True)
    if force and paths.SOURCE_DIR.exists():
        shutil.rmtree(paths.SOURCE_DIR)
    if (paths.SOURCE_DIR / ".git").exists():
        print(f"ManimGL source already exists: {paths.SOURCE_DIR}")
        return
    if paths.SOURCE_DIR.exists():
        shutil.rmtree(paths.SOURCE_DIR)
    run([
        "git", "clone", "--depth", "1",
        "--branch", paths.MANIMGL_GIT_TAG,
        paths.MANIMGL_GIT_URL,
        str(paths.SOURCE_DIR),
    ])


def patch_manimgl_source() -> None:
    """Apply the two required source patches.

    1. Headless EGL standalone context (works for BOTH Mesa/CPU and
       NVIDIA/GPU; the vendor is chosen at render time via environment
       variables, never by reinstalling).
    2. The legacy ``--fps`` CLI flag must parse as an integer.
    """
    camera_file = paths.SOURCE_DIR / "manimlib/camera/camera.py"
    config_file = paths.SOURCE_DIR / "manimlib/config.py"

    camera_source = camera_file.read_text(encoding="utf-8")
    old_context = "moderngl.create_standalone_context()"
    new_context = 'moderngl.create_standalone_context(backend="egl", require=430)'
    if old_context in camera_source:
        camera_file.write_text(
            camera_source.replace(old_context, new_context, 1), encoding="utf-8"
        )
    if new_context not in camera_file.read_text(encoding="utf-8"):
        raise RuntimeError("Could not apply the ModernGL EGL camera patch.")

    config_source = config_file.read_text(encoding="utf-8")
    fps_old = '"--fps",\n            help="Frame rate, as an integer",'
    fps_new = '"--fps",\n            type=int,\n            help="Frame rate, as an integer",'
    if fps_old in config_source:
        config_file.write_text(config_source.replace(fps_old, fps_new, 1), encoding="utf-8")
    if fps_new not in config_file.read_text(encoding="utf-8"):
        raise RuntimeError("Could not apply the legacy --fps integer patch.")
    print("Source patches applied (EGL context, --fps).")


def install_manimgl(*, force: bool = False) -> None:
    """Install ManimGL only inside the isolated environment."""
    print("\n[5/7] Installing ManimGL into the isolated environment...", flush=True)
    marker = paths.ENV_DIR / "bin/manimgl"
    if marker.exists() and not force:
        print(f"ManimGL is already installed: {marker}")
        return
    if not paths.ENV_PYTHON.exists():
        raise FileNotFoundError("The isolated Python environment does not exist.")
    if not paths.SOURCE_DIR.exists():
        raise FileNotFoundError("The ManimGL source directory does not exist.")

    pip = [str(paths.ENV_PYTHON), "-m", "pip", "install", "-q"]
    run([*pip, "--upgrade", "pip", "setuptools<81", "wheel"], quiet=True, capture=True)
    run([*pip, "-e", str(paths.SOURCE_DIR)], quiet=True, capture=True)
    # Editable installation can leave a newer setuptools; enforce again.
    run([*pip, "--force-reinstall", "setuptools<81"], quiet=True, capture=True)

    # Python 3.13 removed the standard-library audioop module that Pydub needs.
    version = subprocess.check_output(
        [str(paths.ENV_PYTHON), "-c", "import sys;print(sys.version_info[1])"],
        text=True,
    ).strip()
    if int(version) >= 13:
        run([*pip, "audioop-lts"], quiet=True, capture=True)
    run(
        [str(paths.ENV_PYTHON), "-c",
         "import audioop; from pydub import AudioSegment; print('Pydub audio backend: OK')"],
        quiet=True, capture=True,
    )
    print("ManimGL installed.")


def prepare_directories() -> None:
    """Create render and runtime directories."""
    print("\n[6/7] Preparing rendering directories...", flush=True)
    paths.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    paths.RUNTIME_DIR.chmod(0o700)
    print(f"Video directory: {paths.VIDEO_DIR}")


def verify_installation() -> None:
    """Verify manimlib imports headlessly and FFmpeg is present."""
    print("\n[7/7] Verifying the installation...", flush=True)
    from .backends import cpu_render_env

    output = run(
        [str(paths.ENV_PYTHON), "-W", "ignore", "-c",
         "import manimlib; print('manimlib import: OK')"],
        capture=True, quiet=True, env=cpu_render_env(),
    )
    if "OK" not in output:
        raise RuntimeError("manimlib failed to import:\n" + output)
    run(["ffmpeg", "-version"], capture=True, quiet=True)
    print("manimlib import: OK\nffmpeg: OK")


def setup(
    *,
    backend: str | None = None,
    register_magics: bool = True,
    force: bool = False,
) -> None:
    """Run the complete safe Colab installation.

    Args:
        backend: Optionally select ``"cpu"`` or ``"gpu"`` right away.
            Defaults to keeping the previously saved choice (or ``cpu``).
        register_magics: Register ``%%manimgl`` and helper magics.
        force: Delete and rebuild the environment and source checkout.
    """
    print("=" * 70)
    print("manimgl-colab setup  (one engine, CPU/GPU switchable)")
    print("No LaTeX is installed. Use install_latex() when you need Tex.")
    print("ManimGL stays isolated from Colab's internal Python environment.")
    print("=" * 70)

    install_system_dependencies()
    create_virtual_environment(force=force)
    install_pip()
    download_manimgl(force=force)
    patch_manimgl_source()
    install_manimgl(force=force)
    prepare_directories()
    verify_installation()

    if backend is not None:
        from .backends import set_backend

        set_backend(backend)

    if register_magics:
        from .magic import register_magics as _register

        _register()

    from .backends import get_backend

    print("\n" + "=" * 70)
    print("Setup completed successfully.")
    print(f"Active backend: {get_backend().upper()}")
    print("Switch anytime:  mc.backend('gpu')  /  mc.backend('cpu')")
    print("Render:          %%manimgl -qm MyScene   (flags: --gpu / --cpu)")
    print("=" * 70)
