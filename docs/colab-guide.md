# 📒 Google Colab Guide — cell by cell

A fresh notebook to a downloaded video, step by step. Each block below is
**one Colab cell**, in order.

> Using a GPU? First do **Runtime ▸ Change runtime type ▸ T4 GPU**, then start.

---

## Cell 1 — Install + setup (once per runtime, ~1–2 min)

```python
!pip install -q git+https://github.com/myabdur212121-afk/manimgl-colab.git
import manimgl_colab as mc
mc.setup()
```

A status card appears when it finishes. ManimGL lives in its **own isolated
environment** — nothing in Colab's Python is touched.

## Cell 2 — Switch to GPU (only on a GPU runtime)

```python
mc.use_gpu()
```

You get an honest proof line (`GL_RENDERER: Tesla T4 …`). If the runtime has
no GPU this **fails loudly** — it never silently falls back to CPU.
Skip this cell on a CPU runtime; switch back anytime with `mc.use_cpu()`.

## Cell 3 — Warm mode (recommended)

```python
mc.warm()
```

One-time engine preload; every later render starts in **under a second**
instead of ~4 s. See [performance.md](performance.md) for how it works.

## Cell 4 — First render

```python
%%manimgl -qm FirstScene
from manimlib import *

class FirstScene(Scene):
    def construct(self):
        sq = Square(color=BLUE).set_fill(BLUE, 0.5)
        self.play(ShowCreation(sq))
        self.play(Rotate(sq, PI / 2))
        self.play(FadeOut(sq))
```

You see a live progress card (with CPU%/GPU%), then just the video.

## Cell 5 — Information, when you want it

```python
%manimgl_log       # full report of the last render + raw engine log
%manimgl_status    # backend, GL proof, NVENC, LaTeX, versions
```

## Cell 6 — Final quality & download

```python
%%manimgl -qk --jobs 2 FirstScene
...same scene code...
```

```python
%manimgl_download
```

---

## ⚠️ Important things to know

### LaTeX is NOT installed by default
`Tex(...)` / `TexText(...)` will fail until you run:

```python
mc.install_latex()            # slim (~200 MB), enough for most math
mc.install_latex(slim=False)  # full TeX Live, for exotic packages
```

Plain `Text("...")` always works without LaTeX.

### The scene class must be in every render cell
Each render runs in a clean process for reproducibility, so
`%%manimgl -qm MyScene` needs `class MyScene(Scene):` **in that same cell**
(the magic line must be line 1). To render from a file instead:

```python
%manimgl_file -qm /content/myfile.py MyScene
```

### Scenes with no animations become an image
`self.add(...)` without any `self.play()`/`self.wait()` produces a **PNG
still** automatically (same behaviour as ManimCE). Add `self.wait(2)` if you
wanted a video.

### Runtime restarts wipe everything
Colab deletes `/content` when the runtime resets — just run Cell 1 (and 2–3)
again.

### Upgrading to the latest version

```python
!pip install -q --force-reinstall --no-deps git+https://github.com/myabdur212121-afk/manimgl-colab.git
import sys
for m in [m for m in sys.modules if m.startswith("manimgl_colab")]: del sys.modules[m]
import manimgl_colab as mc; mc.register_magics()
```

### Common ManimGL gotchas
- Use `Group` (not `VGroup`) for `Surface`-based 3D objects.
- Clear updaters (`mob.clear_updaters()`) before `Transform`/`FadeOut` on
  updater-driven mobjects (the tool also self-heals this case automatically).
- `self.camera.frame` is your camera: `set_height()` to zoom,
  `move_to()` to pan, `reorient()` for 3D — all animatable.
