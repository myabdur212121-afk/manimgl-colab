"""Honest CPU/GPU backend switching for ManimGL on Google Colab.

The same installed engine renders on either backend; only render-time
environment variables change:

- CPU: Mesa EGL (surfaceless llvmpipe). ``LIBGL_ALWAYS_SOFTWARE=1`` is set
  explicitly — software rendering is never hidden behind a "GPU" label.
- GPU: NVIDIA EGL via the driver's own userspace libraries. The renderer
  string is verified to be a real NVIDIA adapter; if it is not, rendering
  FAILS instead of silently falling back to the CPU.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import paths
from .shell import apt, run

NVIDIA_PACKAGE_PATTERNS = (
    "libnvidia-common-{major}",
    "libnvidia-compute-{major}",
    "libnvidia-gpucomp-{major}",
    "libnvidia-gl-{major}",
)

NVIDIA_RENDERER_TOKENS = (
    "nvidia", "tesla", "quadro", "geforce", "rtx", "t4", "a100", "l4", "v100", "p100",
)

_SCRUB_VARIABLES = ("DISPLAY", "WAYLAND_DISPLAY", "VK_ICD_FILENAMES", "VK_DRIVER_FILES")


def _base_render_env() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYGLET_HEADLESS"] = "true"
    environment["PYOPENGL_PLATFORM"] = "egl"
    environment["XDG_RUNTIME_DIR"] = str(paths.RUNTIME_DIR)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["MANIMGL_ERROR_REPORT"] = str(paths.ERROR_REPORT)
    environment["MANIMGL_CELL_FILE"] = str(paths.SCENE_FILE)
    for name in _SCRUB_VARIABLES:
        environment.pop(name, None)
    return environment


def cpu_render_env() -> dict[str, str]:
    """Environment for honest Mesa/llvmpipe software rendering."""
    environment = _base_render_env()
    environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
    environment["EGL_PLATFORM"] = "surfaceless"
    environment["MANIMGL_COLAB_EXPECT"] = "cpu"
    if paths.MESA_VENDOR_JSON.exists():
        environment["__EGL_VENDOR_LIBRARY_FILENAMES"] = str(paths.MESA_VENDOR_JSON)
    else:
        environment.pop("__EGL_VENDOR_LIBRARY_FILENAMES", None)
    environment.pop("__GLX_VENDOR_LIBRARY_NAME", None)
    return environment


def gpu_render_env() -> dict[str, str]:
    """Environment for verified NVIDIA EGL rendering."""
    state = _load_gpu_state()
    if state is None:
        raise RuntimeError(
            "GPU backend is not prepared. Run mc.backend('gpu') first."
        )
    environment = _base_render_env()
    library_dir = state["library_dir"]
    environment["LD_LIBRARY_PATH"] = (
        f"{library_dir}:/usr/lib64-nvidia:{environment.get('LD_LIBRARY_PATH', '')}"
    )
    environment["__EGL_VENDOR_LIBRARY_FILENAMES"] = state["egl_json"]
    environment["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
    environment["MANIMGL_COLAB_EXPECT"] = "gpu"
    environment.pop("LIBGL_ALWAYS_SOFTWARE", None)
    environment.pop("EGL_PLATFORM", None)
    return environment


def render_env(backend: str) -> dict[str, str]:
    if backend == "gpu":
        return gpu_render_env()
    if backend == "cpu":
        return cpu_render_env()
    raise ValueError(f"Unknown backend: {backend!r} (use 'cpu' or 'gpu')")


def get_backend() -> str:
    """Return the saved default backend ('cpu' unless switched)."""
    try:
        data = json.loads(paths.BACKEND_FILE.read_text(encoding="utf-8"))
        backend = str(data.get("backend", "cpu"))
        return backend if backend in ("cpu", "gpu") else "cpu"
    except (OSError, json.JSONDecodeError, ValueError):
        return "cpu"


def _save_backend(backend: str, probe: dict[str, str]) -> None:
    paths.BACKEND_FILE.write_text(
        json.dumps({"backend": backend, "probe": probe}, indent=2) + "\n",
        encoding="utf-8",
    )


def detect_nvidia_gpu() -> dict[str, str]:
    """Return the Colab NVIDIA GPU and kernel-driver version, or raise."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
         "--format=csv,noheader,nounits"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    ) if shutil.which("nvidia-smi") else None
    if result is None or result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "No NVIDIA GPU runtime detected.\n"
            "Colab: Runtime → Change runtime type → T4 GPU, then reconnect.\n"
            "(strict mode: there is NO silent CPU fallback)"
        )
    parts = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 3:
        raise RuntimeError(f"Unexpected nvidia-smi output: {result.stdout}")
    return {"name": parts[0], "driver_version": parts[1], "memory_mib": parts[2]}


def _find_system_nvidia_egl(driver_version: str) -> Path | None:
    """Fast path: the Colab image often already ships libEGL_nvidia."""
    for directory in (Path("/usr/lib64-nvidia"), Path("/usr/lib/x86_64-linux-gnu")):
        if not directory.is_dir():
            continue
        if (directory / "libEGL_nvidia.so.0").exists() or list(
            directory.glob(f"libEGL_nvidia.so.{driver_version}*")
        ):
            return directory
    return None


def _available_exact_version(package: str, driver_version: str) -> str:
    output = run(["apt-cache", "madison", package], capture=True, quiet=True, check=False)
    versions = [
        fields[1].strip()
        for line in output.splitlines()
        if len(fields := line.split("|")) >= 2
    ]
    exact = [v for v in versions if v.startswith(driver_version + "-")]
    if not exact:
        raise RuntimeError(
            f"No userspace package matching NVIDIA driver {driver_version} "
            f"was found for {package}. Available: {versions}"
        )
    return exact[0]


def _extract_nvidia_libraries(driver_version: str, *, force: bool = False) -> Path:
    """Download and locally extract NVIDIA userspace libs matching the driver."""
    major = driver_version.split(".", 1)[0]
    if force:
        shutil.rmtree(paths.NVIDIA_ROOT, ignore_errors=True)
        shutil.rmtree(paths.NVIDIA_DEBS, ignore_errors=True)

    library_dir = paths.NVIDIA_ROOT / "usr/lib/x86_64-linux-gnu"
    if not paths.NVIDIA_ROOT.exists():
        paths.NVIDIA_ROOT.mkdir(parents=True)
        paths.NVIDIA_DEBS.mkdir(parents=True, exist_ok=True)
        apt(["update", "-qq"], quiet=True)
        for pattern in NVIDIA_PACKAGE_PATTERNS:
            package = pattern.format(major=major)
            try:
                version = _available_exact_version(package, driver_version)
            except RuntimeError as error:
                if "common" in package or "gpucomp" in package:
                    print(f"(optional package skipped: {package})")
                    continue
                raise error
            apt(["download", f"{package}={version}"], quiet=True, cwd=paths.NVIDIA_DEBS)
        for deb_file in sorted(paths.NVIDIA_DEBS.glob("*.deb")):
            run(["dpkg-deb", "--extract", str(deb_file), str(paths.NVIDIA_ROOT)],
                quiet=True)

    if not list(library_dir.glob("libEGL_nvidia.so*")):
        raise FileNotFoundError(f"libEGL_nvidia was not extracted under {library_dir}")
    return library_dir


def _write_egl_vendor_json(library_dir: Path, driver_version: str) -> Path:
    candidates = [library_dir / "libEGL_nvidia.so.0",
                  *library_dir.glob(f"libEGL_nvidia.so.{driver_version}*")]
    library = next((c for c in candidates if c.exists()), None)
    if library is None:
        raise FileNotFoundError(f"libEGL_nvidia.so not found in {library_dir}")
    paths.NVIDIA_EGL_JSON.write_text(
        json.dumps(
            {"file_format_version": "1.0.0", "ICD": {"library_path": str(library)}},
            indent=4,
        ) + "\n",
        encoding="utf-8",
    )
    return paths.NVIDIA_EGL_JSON


def _load_gpu_state() -> dict | None:
    try:
        state = json.loads(paths.GPU_STATE.read_text(encoding="utf-8"))
        if Path(state["egl_json"]).exists():
            return state
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def probe(backend: str) -> dict[str, str]:
    """Create a real EGL context on the given backend and report GL info."""
    code = (
        "import json, moderngl\n"
        "ctx = moderngl.create_standalone_context(backend='egl', require=430)\n"
        "print(json.dumps({'renderer': ctx.info.get('GL_RENDERER',''),"
        " 'vendor': ctx.info.get('GL_VENDOR',''),"
        " 'version': ctx.info.get('GL_VERSION',''),"
        " 'version_code': str(ctx.version_code)}))\n"
        "ctx.release()\n"
    )
    environment = render_env(backend)
    environment.pop("MANIMGL_COLAB_EXPECT", None)
    result = subprocess.run(
        [str(paths.ENV_PYTHON), "-W", "ignore", "-c", code],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{backend.upper()} EGL context test failed:\n{result.stdout}")
    json_line = next(
        (line for line in reversed(result.stdout.splitlines()) if line.startswith("{")),
        None,
    )
    if not json_line:
        raise RuntimeError("Context probe returned no JSON:\n" + result.stdout)
    return json.loads(json_line)


def is_nvidia_renderer(renderer: str) -> bool:
    lowered = renderer.lower()
    return any(token in lowered for token in NVIDIA_RENDERER_TOKENS)


def prepare_gpu(*, force: bool = False) -> dict:
    """Prepare and verify the NVIDIA EGL backend (strict, no fake GPU)."""
    gpu = detect_nvidia_gpu()
    print(f"GPU: {gpu['name']}  |  driver {gpu['driver_version']}  |  "
          f"{gpu['memory_mib']} MiB VRAM")

    state = None if force else _load_gpu_state()
    if state is None or state.get("driver_version") != gpu["driver_version"]:
        system_dir = _find_system_nvidia_egl(gpu["driver_version"])
        if system_dir is not None:
            print(f"Using the runtime's own NVIDIA EGL libraries: {system_dir}")
            library_dir = system_dir
        else:
            print("Downloading matching NVIDIA userspace libraries (no driver change)...")
            library_dir = _extract_nvidia_libraries(gpu["driver_version"], force=force)
        egl_json = _write_egl_vendor_json(library_dir, gpu["driver_version"])
        state = {
            **gpu,
            "library_dir": str(library_dir),
            "egl_json": str(egl_json),
        }
        paths.GPU_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    paths.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    paths.RUNTIME_DIR.chmod(0o700)

    info = probe("gpu")
    renderer = info.get("renderer", "")
    if not is_nvidia_renderer(renderer + " " + info.get("vendor", "")):
        raise RuntimeError(
            "STRICT CHECK FAILED: expected a real NVIDIA renderer but got "
            f"{info}. Refusing to pretend this is a GPU."
        )
    if int(info.get("version_code", "0")) < 430:
        raise RuntimeError(f"OpenGL 4.3+ required, got: {info}")

    state["probe"] = info
    paths.GPU_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"Verified GPU renderer: {renderer}  (OpenGL {info.get('version', '?')})")
    return state


def set_backend(backend: str, *, force: bool = False) -> dict[str, str]:
    """Switch the default backend. 'gpu' is strictly verified first."""
    backend = backend.strip().lower()
    if backend not in ("cpu", "gpu"):
        raise ValueError("backend must be 'cpu' or 'gpu'")

    if backend == "gpu":
        state = prepare_gpu(force=force)
        info = state["probe"]
    else:
        info = probe("cpu")
        print(f"CPU renderer: {info.get('renderer', '?')} "
              f"(honest software rendering, Mesa)")

    _save_backend(backend, info)
    label = "GPU (NVIDIA EGL) ✅" if backend == "gpu" else "CPU (Mesa llvmpipe)"
    print(f"Default backend is now: {label}")
    return info


def status() -> dict[str, object]:
    """Print and return the current configuration."""
    backend = get_backend()
    report: dict[str, object] = {
        "backend": backend,
        "env_dir": str(paths.ENV_DIR),
        "source_dir": str(paths.SOURCE_DIR),
        "video_dir": str(paths.VIDEO_DIR),
        "engine_installed": paths.ENV_PYTHON.exists(),
    }
    print("manimgl-colab status")
    print("-" * 50)
    print(f"Default backend : {backend.upper()}")
    print(f"Engine installed: {report['engine_installed']}")
    try:
        info = probe(backend)
        report["renderer"] = info.get("renderer", "")
        report["opengl"] = info.get("version", "")
        honest = ("GPU ✅" if is_nvidia_renderer(str(report["renderer"]))
                  else "CPU (software)")
        print(f"Live renderer   : {report['renderer']}  →  {honest}")
        print(f"OpenGL          : {report['opengl']}")
    except Exception as error:  # noqa: BLE001
        print(f"Live probe failed: {error}")
    from .latex import is_latex_installed

    report["latex"] = is_latex_installed()
    print(f"LaTeX installed : {report['latex']}")
    print(f"Video directory : {report['video_dir']}")
    return report
