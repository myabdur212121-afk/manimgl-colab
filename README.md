# manimgl-colab

**ManimGL (3Blue1Brown) on Google Colab — one engine, honest CPU/GPU switching, ManimCE-style `%%manimgl` magic, optional LaTeX.**

- ✅ **One** isolated environment + **one** pinned ManimGL (v1.7.2) serves **both** CPU and GPU — switching never reinstalls anything.
- ✅ **Honest hardware proof**: every render prints the real `GL_RENDERER` (e.g. `Tesla T4` or `llvmpipe`). GPU mode is **strict** — if the context is not a real NVIDIA renderer, the render **fails loudly** instead of silently using the CPU.
- ✅ ManimCE-style magic: `%%manimgl -qm MyScene` with `-ql -qm -qh -qp -qk --draft`, `-v WARNING`, `--gpu/--cpu`.
- ✅ LaTeX is **optional**: `mc.install_latex()` (slim, fast) or `mc.install_latex(slim=False)` (complete).
- ✅ Rich compact/full error reports, `%manimgl_download`, `%openfile` with automatic backups, Colab IDE autocomplete bridge.
- ✅ Colab's own IPython is never touched (no dependency crash, no kernel restart needed).

---

## Quick start (Google Colab)

### Cell 1 — install the setup API

```python
!pip install -q --no-deps git+https://github.com/myabdur212121-afk/manimgl-colab.git
```

`--no-deps` keeps Colab's IPython untouched. The heavy engine is installed by `setup()` into `/content/manimgl-env`, fully isolated.

### Cell 2 — set up the engine (≈2–3 minutes on a fresh runtime)

```python
import manimgl_colab as mc

mc.setup()          # installs engine + registers all magics (no LaTeX)
```

On a **GPU runtime** (Runtime → Change runtime type → T4 GPU):

```python
mc.backend("gpu")   # strict verification: prints the real NVIDIA renderer
```

### Cell 3 — render

```python
%%manimgl -qm RotatingSphere
from manimlib import *


class RotatingSphere(ThreeDScene):
    def construct(self):
        self.frame.reorient(25, 70)
        sphere = Sphere(radius=2.2, resolution=(25, 25))
        sphere.set_color(BLUE_D)
        self.play(FadeIn(sphere))
        self.play(Rotate(sphere, TAU, axis=UP), run_time=4, rate_func=linear)
        self.wait()
```

The MP4 is saved under `/content/manimgl_videos/` and displayed automatically, together with the hardware proof line:

```
Proof — GL_RENDERER: Tesla T4/PCIe/SSE2  →  GPU ✅
```

---

## Switching CPU ↔ GPU — any time, instantly

```python
mc.backend("gpu")      # strict NVIDIA verification, then set as default
mc.backend("cpu")      # honest Mesa/llvmpipe software rendering
mc.backend()           # read the current default
```

or as line magic / per-cell override:

```python
%manimgl_backend gpu
```

```python
%%manimgl --cpu --draft MyScene     # this cell only: CPU
%%manimgl --gpu -qh MyScene         # this cell only: GPU (strict)
```

**Strict mode guarantee:** when GPU is requested but no NVIDIA context can be created, you get a clear error — never a hidden CPU fallback. Verify anytime:

```python
%manimgl_status
```

```
Default backend : GPU
Live renderer   : Tesla T4/PCIe/SSE2  →  GPU ✅
OpenGL          : 4.6.0 NVIDIA 550.54.15
```

## Quality flags (ManimCE style)

| Flag | Output |
|---|---|
| `--draft` | 640×360 @ 15 FPS (fastest check) |
| `-ql` | low, 480p |
| `-qm` | medium, 720p |
| `-qh` | high, 1080p |
| `-qp` | 2560×1440 |
| `-qk` | 4K |
| `-r 960x540` | custom resolution (passed through) |
| `--fps 60` | custom frame rate (passed through) |

Other flags: `-v WARNING|INFO|DEBUG`, `--display-width 560` (preview size only), `--prerun`, `--progress`, `--ERROR` (full backend traceback; default is a compact report highlighting your scene line).

## Optional LaTeX

Nothing TeX-related is installed by default — `Text(...)` works out of the box (Computer Modern, Noto fonts). When you need `Tex`/`TexText`:

```python
mc.install_latex()            # slim: fast, small; slim default preamble
mc.install_latex(slim=False)  # complete: texlive-fonts-extra, tipa, original preamble
```

If a render fails with a LaTeX-related error, the error report itself shows this hint.

## Other magics

```python
%manimgl_download             # download the newest MP4
%manimgl_download MyScene     # newest MP4 of that scene (partial renders too)

%openfile /content/manimGL/manimlib/scene/scene.py:114   # preview + Colab editor (auto backup)
%filebackups /path/file.py    # list backups
%restorefile /path/file.py    # restore newest backup

mc.enable_autocomplete()      # refresh the IDE bridge (manimlib autocomplete)
mc.status()                   # same as %manimgl_status, returns a dict
```

## How the GPU mode works (and why it is not fake)

1. `nvidia-smi` must report a GPU and kernel-driver version.
2. The matching NVIDIA **userspace** EGL libraries are used — taken from the runtime image when present, otherwise downloaded as exact-version `.deb`s and extracted under `/content` (the system driver is never replaced).
3. A standalone **EGL** OpenGL 4.3+ context is created and `GL_RENDERER` must be a real NVIDIA adapter — verified at switch time **and again inside every render process**.
4. The renderer string is printed with every render as proof.

CPU mode sets `LIBGL_ALWAYS_SOFTWARE=1` + Mesa EGL (surfaceless llvmpipe) explicitly — software rendering is a labelled choice, never a disguise.

## Persistence

A new/reset Colab runtime loses `/content`. Rerun Cell 1 + `mc.setup()` (idempotent — fast when things already exist). Copy videos you want to keep to Drive or download them.

---

## বাংলা সংক্ষিপ্ত গাইড

```python
# সেল ১
!pip install -q --no-deps git+https://github.com/myabdur212121-afk/manimgl-colab.git

# সেল ২
import manimgl_colab as mc
mc.setup()            # ইঞ্জিন ইনস্টল + সব magic রেজিস্টার
mc.backend("gpu")     # GPU রানটাইমে; CPU-তে ফিরতে mc.backend("cpu")
mc.install_latex()    # শুধু Tex/TexText দরকার হলে
```

```python
# সেল ৩
%%manimgl -qm MyScene
from manimlib import *

class MyScene(Scene):
    def construct(self):
        self.play(ShowCreation(Circle()))
```

- প্রতিটা রেন্ডারে আসল `GL_RENDERER` দেখানো হয় — GPU আসল কি না নিজের চোখে দেখবেন।
- GPU চেয়েছেন কিন্তু GPU নেই → স্পষ্ট error; লুকিয়ে CPU-তে চালানো হয় **না**।
- `%manimgl_status` দিয়ে যেকোনো সময় যাচাই করুন।

## License

MIT
