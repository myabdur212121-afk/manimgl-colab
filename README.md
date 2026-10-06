# manimgl-colab

Clean, honest **ManimGL (3b1b/manim)** setup for **Google Colab** — with verified
GPU rendering, a ManimCE-style `%%manimgl` cell magic, rich error reports, live
progress, NVENC hardware encoding and experimental parallel rendering.

> This package targets **Google Colab only** and **ManimGL** (3b1b's engine),
> not ManimCE.

---

## Quick start

```python
# Cell 1 — install (~1 minute)
!pip install -q git+https://github.com/myabdur212121-afk/manimgl-colab.git
import manimgl_colab as mc
mc.setup()          # installs ManimGL in an isolated venv + registers magics
```

```python
# Cell 2 — render
%%manimgl -qm MyScene
from manimlib import *

class MyScene(Scene):
    def construct(self):
        square = Square(color=BLUE).set_fill(BLUE, 0.5)
        self.play(ShowCreation(square))
        self.play(Rotate(square, PI / 2))
```

While rendering you see **one live progress card** (percent, it/s, ETA, backend
proof). When it finishes you see **the video — nothing else**. All details stay
available on demand (see *Information commands* below).

---

## Backends: CPU ↔ GPU, honestly

```python
mc.use_cpu()         # software rendering (llvmpipe) — works on any runtime
mc.use_gpu()         # NVIDIA EGL — requires a GPU runtime (Runtime ▸ Change runtime type ▸ GPU)
mc.backend("gpu")    # same as use_gpu(); mc.backend() returns the current one
```

- Every render prints the **actual `GL_RENDERER` string** from the render
  process itself — that is the proof of what really rendered your frames.
- `use_gpu()` on a CPU runtime raises a **strict error**. There is **no silent
  fallback**: you always know which hardware you used.
- Switch any time; the choice persists per session.

### NVENC (GPU video encoding)

On GPU runtimes the encoder is probed with a **real test encode** (not just
`ffmpeg -encoders`, which lies). If NVENC genuinely works, `h264_nvenc` is used
automatically — the biggest win at `-qp`/`-qk`. If an NVENC render fails due to
driver quirks it falls back to `libx264` **once, visibly** (the log card shows
`encoder: libx264 (fallback)`).

---

## `%%manimgl` — the cell magic

```
%%manimgl [flags] SceneName
```

| Flag | Meaning |
|---|---|
| `-ql` | 480p15 (low) |
| `-qm` | 720p30 (medium, good default) |
| `-qh` | 1080p60 (high) |
| `-qp` | 1440p60 (2K) |
| `-qk` | 2160p60 (4K) |
| `--draft` | 360p15 — fastest iteration |
| `--gpu` / `--cpu` | override backend for this render only |
| `--jobs N` | experimental parallel rendering (see below) |
| `--no-prerun` | skip the counting pass (progress shows it/s instead of %) |
| `--fps N` | override frame rate for any quality (e.g. `-qk --fps 30`) |
| `-s` / `--image` | render only the final frame as a PNG (poster/thumbnail) |
| `--cold` | force the classic isolated start even when warm mode is on |
| `--verbose` / `-v` | stream the raw ManimGL log while rendering |
| `--ERROR` | full ManimCE-style traceback (library frames included); default shows only your code |
| `--display-width W` | video player width in px (default 640) |

Notes:

- Comments or a docstring **above** the magic line are fine — the magic is
  hoisted automatically:

  ```python
  # my experiment
  """notes to self"""
  %%manimgl -qm MyScene
  ...
  ```

- The scene class must be defined **in the cell** (each render runs in a clean
  subprocess for reproducibility).
- **Static scenes render an image, like ManimCE**: a scene with no
  `self.play(...)`/`self.wait(...)` produces a PNG still of the final frame
  automatically (ManimCE's `scene_finished` behaviour) with a hint on how to
  get a video instead.
- `%manimgl_file path.py:SceneName -qh` renders a scene from a file instead.

### Live progress

By default a cheap **prerun pass** counts total frames first, so the progress
card shows a real percentage and ETA. If a scene cannot survive the prerun pass
(rare — e.g. `TracingTail`-style updaters left attached during a `Transform`),
the render **auto-retries without prerun** and still succeeds; you just get
it/s instead of %. `--no-prerun` opts out manually.

---

## Warm mode — sub-second render starts (opt-in)

Every render runs in a fresh subprocess, which costs ~4 s of engine imports
before the first frame. ManimCE avoids this by keeping the library loaded in
the notebook kernel; warm mode gives you the same feel **without giving up
isolation**:

```python
mc.warm()          # one-time engine preload (~4s); after this, renders start in <1s
mc.warm(False)     # back to classic cold starts
%manimgl_warm on | off | status
```

How it stays safe: a resident worker inside the venv keeps `manimlib`
imported and **forks** a pristine child per render. The child applies the
render's environment, creates its own OpenGL context (GL proof still printed
per render), renders and exits — crashes kill only the child, state never
leaks between renders, and the worker auto-restarts after upgrades. Any warm
failure silently falls back to the classic cold path. `--jobs N` renders
always use the cold path.

**GPU:** the dynamic linker only reads `LD_LIBRARY_PATH` at process start, so
when the GPU backend is prepared the worker is launched with the NVIDIA
library path already in place — one worker then serves **both** CPU and GPU
renders (glvnd vendor selection is applied per render). If the GPU becomes
available after the worker started, the next GPU render transparently
restarts the worker GPU-ready.

## Information commands (clean output policy)

During render: **only the progress card**. After render: **only the video**
plus a one-line summary strip. Everything else is on demand, as formatted HTML:

| Command | Shows |
|---|---|
| `%manimgl_status` | backend, verified renderer, OpenGL, NVENC, LaTeX, versions |
| `%manimgl_log` | full card for the last render: timings, frames, encoder, proof — plus the raw ManimGL log in a collapsible section |
| `%manimgl_backend gpu` / `cpu` | switch backend |
| `%manimgl_download` | download the last video |

---

## Error reports

Two views:

- **Default (compact, for everyday use):** only the frames from **your cell**
  — context lines, `❱` marker, exact-expression underline — plus the final
  `ErrorType: message` line and hints. Library frames are summarized in one
  dim note.
- **`--ERROR` (full, for hard debugging):** the complete ManimCE-identical
  traceback. ManimCE prints errors with rich's traceback renderer; this view
  reproduces that renderer faithfully in HTML:

- red rounded panel titled *Traceback (most recent call last)*
- **every frame shown**, oldest first, `path:lineno in function` headers —
  your cell's frames are labelled **Your cell** with line numbers matching
  the cell exactly (the `%%manimgl` line counts as line 1)
- 3 context lines around each failing line (syntax highlighted, `❱` marker,
  highlighted background)
- the **exact failing expression red-underlined** via Python 3.11 fine-grained
  column positions — the same `co_positions()` mechanism rich uses
- chained exceptions with the standard separator sentences; `… N frames
  hidden …` middle cut beyond 100 frames; locals are not shown (rich default)
- below the CE-identical part: hint strips for known gotchas and the full raw
  log in a collapsible section

---

## `--jobs N` — experimental parallel rendering

```python
%%manimgl -qk --jobs 2 MyScene
```

Splits the scene's animations into `N` chunks (ManimGL `-n start,end` slices),
renders them in parallel processes and losslessly concatenates the results
(`ffmpeg -c copy`). The output is verified to match the serial render.

Honest caveats:

- Speed-up is **less than N×**: each worker still fast-forwards through the
  animations before its chunk, and the prerun/counting pass is serial.
- It pays off on **long scenes at high quality** with many animations; for
  short scenes the overhead makes it *slower*.
- Scenes must be **deterministic** (seed your randomness) and must not rely on
  state mutated across animation boundaries in ways skipping breaks — the same
  rule as ManimGL's own `-n` flag.
- CPU rendering saturates more cores this way; on GPU runtimes the win is
  smaller (the GL pipeline is shared).

### A note on "GPU utilization"

ManimGL is bottlenecked by single-threaded Python and video encoding, not by
the GPU. 100% GPU usage is not a real lever. The honest speed levers are:
NVENC encoding (automatic), `--jobs`, `--draft` while iterating, and lower
quality until the final render.

---

## LaTeX (optional, on demand)

```python
mc.install_latex()            # slim TinyTeX-style set, enough for Tex/MathTex
mc.install_latex(slim=False)  # full scheme if you need exotic packages
```

Renders using `Tex`/`TexText` fail with a clear hint until LaTeX is installed.

---

## Editor comfort

`setup()` also enables an **editor bridge** so Colab's language server resolves
`manimlib` — autocomplete works and the yellow "missing import" underlines
disappear.

File helpers: `%openfile path.py:114`, `%restorefile path.py`,
`%filebackups path.py`.

---

## Upgrading

```python
!pip install -q --force-reinstall --no-deps git+https://github.com/myabdur212121-afk/manimgl-colab.git
import sys
for name in [m for m in sys.modules if m.startswith("manimgl_colab")]:
    del sys.modules[name]
import manimgl_colab as mc
mc.register_magics()
```

## Examples

- `examples/rotating_sphere.py` — minimal 3D scene.
- `examples/ultimate_stress_test.py` — 45 s, 25 animations: streamlines, 3D
  surfaces, Lorenz attractor with tracing tails, particle fields. Renders in
  ~1 min at `-qm` and ~3 min at `-qk` on a Colab T4.

## Changelog

**2.5.1**
- Warm mode now fully supports the GPU backend: the worker is born with the NVIDIA library path (LD_LIBRARY_PATH is start-time-only) and serves both CPU and GPU renders; auto-rebirth when the GPU is prepared later.

**2.5.0**
- Opt-in warm mode (`mc.warm()` / `%manimgl_warm`): resident fork-server keeps the engine preloaded — render startup drops from ~4 s to <1 s with full per-render isolation preserved; `--cold` flag and automatic cold fallback.

**2.4.0**
- Static scenes (no animations) now auto-render a PNG image, exactly like ManimCE; `%manimgl_download` and `%manimgl_log` understand image outputs.
- New `-s` / `--image` flag: save only the final frame of any scene (fast posters/thumbnails at any quality).

**2.3.0**
- Compact error view is now the default: your frames + error line only; `--ERROR` shows the full ManimCE-identical chain.

**2.2.0**
- Error reports rebuilt to be ManimCE-identical (rich traceback port): all frames, 3-line context, exact-expression underline via `co_positions()`, cell-accurate line numbers, chained-exception separators.
- New `--fps N` flag to override frame rate at any quality.

**2.1.0**
- Live GPU monitor: on GPU renders the progress card shows real **GPU-util %**, encoder % and VRAM every second (via nvidia-smi); peak values appear in `%manimgl_log`.

**2.0.1** — added `use_gpu()` / `use_cpu()` aliases.

**2.0.0**
- ManimCE-style rich error panels (highlighted frames, collapsed library frames, hints).
- Live HTML progress card with real % + ETA (prerun pass, auto-disables when unsafe).
- NVENC auto-detection via real test encode; one-shot visible libx264 fallback.
- Experimental `--jobs N` parallel rendering with lossless concat.
- Clean-output policy: progress → video only; info via `%manimgl_log` / `%manimgl_status`.
- `%%manimgl` works under leading comments/docstrings (input transformer).
- Editor bridge auto-enabled: autocomplete + no yellow underlines.
- New flags: `--jobs`, `--no-prerun`, `--verbose`, `--ERROR`, `--display-width`.

**1.1.1** — first public release: isolated venv install, verified CPU/GPU
backends, strict no-fallback GPU errors, on-demand LaTeX, `%%manimgl` magic.

## License

MIT
