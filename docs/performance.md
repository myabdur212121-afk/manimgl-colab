# ⚡ Performance guide

## Where render time actually goes

Every cold render pays a fixed startup toll before the first frame:

| Step | Cost |
|---|---|
| spawn a fresh Python process | ~0.3–0.5 s |
| import the engine (manimlib + numpy/moderngl/pyglet…) | **~2–3 s** |
| create the OpenGL context (+ GL proof) | ~0.3–0.6 s |
| prerun counting pass (for the progress bar) | ~0.3–1 s |

That ~4 s is identical for a 2-second draft and a 3-minute 4K render — it
only *feels* big on short renders.

## 🔥 Warm mode — removing the toll

```python
mc.warm()          # one-time preload; then renders start in <1 s
mc.warm(False)     # back to classic cold starts
%manimgl_warm status
```

**How it stays safe:** a resident worker inside the isolated venv keeps the
engine imported and **forks** a pristine child per render. The child creates
its own GL context (the per-render GL proof still happens), renders, and
dies — so isolation is fully preserved: crashes kill only the child, state
never leaks between renders.

Details that matter:

- The EGL vendor (NVIDIA vs Mesa) is sealed at engine import, so the worker
  is **born per backend**. Switching `--cpu`↔`--gpu` rebirths it once (~4 s),
  then everything is warm again.
- Any warm failure silently falls back to the cold path — a render never
  blocks. A strict-GPU failure additionally retires the worker and redoes
  the render cold.
- `--cold` forces the classic path for one render.
- Upgrading the package auto-restarts the worker.

## 🧵 `--jobs N` — when parallel pays off

`--jobs` splits the animation list across N processes and losslessly
concatenates the chunks. It is **warm-aware**: the counting pass and every
chunk fork from the warm worker.

But it has a fixed orchestration cost (counting pass + staggered starts +
ffmpeg concat ≈ 1–1.5 s), so:

| Render length | Verdict |
|---|---|
| < ~20 s | **don't** use `--jobs` — overhead eats the gain |
| > ~20 s | `--jobs 2` (or 3) — the longer the render, the bigger the win |

On free Colab (2 vCPUs) `--jobs 2–3` is the sweet spot; more only adds
context-switching.

## 📊 Reading the utilization numbers

The progress card shows live **CPU%** always, and **GPU% · CPU%** side by
side on GPU renders. A typical free-Colab GPU render reads:

```
GPU 5% · enc 0% · VRAM 1.2/15 GB · CPU 98%
```

That is *normal* and still ~3× faster than CPU rendering. Why: the T4
finishes its share (rasterizing) almost instantly each frame, then waits
while the CPU prepares the next frame's geometry — on free Colab the
**2 vCPUs are the bottleneck**, not the GPU. `%manimgl_log` records both
peaks.

Practical consequences:

- `mc.use_gpu()` is worth it even when GPU% looks tiny — compare wall time.
- If CPU% is already ~100%, more `--jobs` won't help.
- More vCPUs (Colab Pro) speed up the same code automatically.

## 🏁 Maximum-speed recipes

```python
# everyday iteration
mc.use_gpu(); mc.warm()
%%manimgl --draft MyScene            # instant drafts

# polish one animation of a big scene
%%manimgl -qm -n 12,15 MyScene       # renders only plays 13–15 (0-based, end-exclusive)

# final export
%%manimgl -qk --jobs 2 MyScene       # GPU draws, 2 processes share the CPU work

# thumbnail in seconds
%%manimgl -qk -s MyScene             # final frame as 4K PNG
```
