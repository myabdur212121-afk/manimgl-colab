# 🔧 How the setup works inside

What `mc.setup()` actually does, step by step, and the design decisions
behind it. You never need this to *use* the tool — it's here so the whole
machine is transparent.

## The problem being solved

ManimGL (3b1b's engine) assumes a desktop: a window, a display, an OpenGL
driver, and its own dependency versions. Colab offers none of that — and its
preinstalled Python fights back if you install conflicting packages into it.
Earlier naive installs suffered duplicated environments, name collisions
with `manimgl`, silent CPU fallbacks pretending to be GPU, and broken state
after every runtime reset.

## `mc.setup()` — the eight steps

1. **System dependencies** (`apt`): ffmpeg, build tools, Cairo/Pango dev
   headers, and the EGL/GL stack (`libegl1`, `libgl1`, Mesa drivers) that
   makes headless OpenGL possible on a server with no display.
2. **Isolated virtualenv** at `/content/manimgl-env` — ManimGL and its exact
   dependency pins live here, **completely separated from Colab's Python**.
   Your notebook process only ever talks to it via subprocesses.
3. **pip bootstrap** inside that venv.
4. **ManimGL source checkout** (pinned release) into `/content/manimGL`.
5. **Small source patches** for known Colab incompatibilities.
6. **Editable install** into the venv (plus pins like `setuptools<81` that
   the engine's older packaging needs).
7. **Directory layout**: videos in `/content/manimgl_videos`, runtime state
   in `/content/manimgl_runtime`.
8. **Verification**: imports the engine headlessly and runs
   `ffmpeg -version` — setup fails loudly here rather than at your first
   render.

Then it registers the `%%manimgl` magics and an **editor bridge** so Colab's
autocomplete understands `from manimlib import *`.

> LaTeX is intentionally **not** part of setup — most scenes never need it.
> `mc.install_latex(slim=True)` adds it on demand.

## Honest GPU rendering (strict mode)

Every render runs through `runner.py`, which wraps the engine's OpenGL
context creation:

- the moment a context exists, the **real `GL_RENDERER`** is printed into
  the log — that string is the proof shown in the UI;
- if the GPU backend was requested but the context is not a genuine NVIDIA
  renderer, the render **aborts with a clear error**. There is no code path
  that silently renders on CPU while claiming GPU.

`mc.use_gpu()` prepares the NVIDIA EGL environment (driver library path +
glvnd vendor JSON) and saves it; `mc.use_cpu()` selects honest Mesa/llvmpipe
software rendering. Switching is instant and per-render overridable
(`--gpu` / `--cpu`).

## Render pipeline per cell

```
%%manimgl -qm MyScene
   │  cell is written to a scene file (with a 1-line header so error line
   │  numbers match YOUR cell lines exactly)
   ├─ pre-flight: scene class exists? stale modules purged?
   ├─ subprocess (or warm fork): runner.py → GL proof → engine renders
   │     live progress card ← parsed from the engine's own output
   │     (frames, %, ETA, CPU% — plus GPU%/VRAM via nvidia-smi on GPU)
   ├─ NVENC hardware encoding when a verified GPU + encoder exist
   │     (automatic libx264 retry if NVENC refuses)
   ├─ zero animations? → automatic PNG still (ManimCE behaviour)
   └─ success: slim strip + video.  failure: ManimCE-identical error panel
        (compact by default: only YOUR frames; --ERROR shows everything)
```

Errors are captured as structured JSON by `error_runner.py` at crash time
(exact column spans included), then rendered as faithful HTML ports of
rich's traceback renderer — the same look ManimCE users know.

## The warm worker (optional fast path)

`worker.py` runs inside the venv, imports the engine once, and serves each
render by `os.fork()`: children inherit the warm imports for free, apply the
render's environment, create a fresh GL context, and exit. Because the EGL
vendor is cached per process at import time, the worker is **born for one
backend** and is transparently reborn when you switch. The notebook side
(`warmup.py`) talks to it over a unix socket and falls back to cold
subprocesses whenever anything is off. `--jobs` chunks and the counting pass
use the same fork path.

## Why a subprocess per render at all?

- a crashing scene can never take your notebook kernel down;
- renders are reproducible — no leaked globals between cells;
- the venv isolation means Colab package updates can't break the engine;
- warm mode then removes the startup cost **without** giving up any of this.
