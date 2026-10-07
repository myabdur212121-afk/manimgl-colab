# 🎛️ Flags & magic commands — complete reference

## Quality presets (horizontal 16:9)

| Flag | Output | Notes |
|---|---|---|
| `--draft` | 640×360 @15fps | fastest iteration |
| `-ql` | 854×480 | |
| `-qm` | 1280×720 | good default |
| `-qh` | 1920×1080 | Full HD |
| `-qp` | 2560×1440 | |
| `-qk` | 3840×2160 | 4K |

## Shorts presets (vertical 9:16) 📱

| Flag | Output | Use |
|---|---|---|
| `-sql` | 480×854 | vertical draft |
| `-sqm` | 720×1280 | preview |
| `-sqh` | 1080×1920 | **YouTube Shorts / Reels standard** |
| `-sqk` | 2160×3840 | 4K vertical |

Shorts presets auto-size the notebook player (`display-height 480`) so tall
videos don't swallow the notebook; your own `--display-*` flag overrides it.

## The three layers — never confuse them

| Layer | Question it answers | Controlled by |
|---|---|---|
| Camera frame | *How much of the scene world is photographed?* (units) | `self.camera.frame` in code — `set_height()`, `move_to()`, `reorient()` |
| Pixel resolution | *How many pixels is the file?* | quality presets **or** `-r WxH` (same knob; `-r` wins if both given) |
| Notebook player | *How big does it display in Colab?* | `--display-width` / `--display-height` — never touches the file |

Facts worth remembering:
- Camera frame height is always **8 units**; width = `8 × (W/H)` from the
  pixel aspect. At `-r 1080x1920` you see a 4.5×8-unit world.
- `-r` uses an **`x` separator**: `-r 1920x1080` ✓, `-r 1920,1080` ✗.
- `--display-width` and `--display-height` are mutually exclusive — the free
  side always follows the video's aspect, so distortion is impossible.

## Rendering control

| Flag | Meaning |
|---|---|
| `-r WxH` | custom pixel resolution (beats quality presets) |
| `--fps N` | frame rate 1–120, on top of any preset (`-qk --fps 30`) |
| `-n A` / `-n A,B` | partial render: start at animation index `A` (0-based), `B` is **exclusive**. Human rule: *M-th to N-th play → `-n M-1,N`*. Don't combine with `--jobs`. |
| `-s` / `--image` | render only the final frame as a PNG (poster/thumbnail — seconds instead of minutes) |
| `--jobs N` | parallel rendering in N processes (best for renders >20 s; see [performance.md](performance.md)) |
| `--gpu` / `--cpu` | backend for this render only |
| `--cold` | force the classic isolated start even when warm mode is on |
| `--ERROR` | full ManimCE-style traceback (default error view shows only *your* code frames) |
| `-v LEVEL` | engine log verbosity |
| `--no-prerun` | skip the frame-counting pre-pass |
| `--display-width W` | notebook player width in px (height auto; default 560) |
| `--display-height H` | notebook player height in px (width auto) — ideal for vertical videos |

## Magic commands

| Magic | Does |
|---|---|
| `%%manimgl [flags] SceneName` | render the scene defined in this cell |
| `%manimgl_file [flags] path.py SceneName` | render a scene from a file |
| `%manimgl_status` | backend, GL proof, NVENC, LaTeX, versions |
| `%manimgl_log` | full report of the last render (+ CPU/GPU peaks, raw log) |
| `%manimgl_backend gpu\|cpu` | switch the default backend |
| `%manimgl_warm on\|off\|status` | control the warm worker |
| `%manimgl_download [SceneName]` | download the last (or named) MP4/PNG |
| `%openfile` / `%restorefile` / `%filebackups` | simple file editing helpers |

## Python API

```python
mc.setup()                  # full installation (idempotent)
mc.use_gpu() / mc.use_cpu() # strict backend switching
mc.backend()                # current backend
mc.warm() / mc.warm(False)  # warm worker on/off
mc.install_latex(slim=True) # on-demand LaTeX
mc.status_report()          # status as a dict
mc.nvenc_available()        # NVENC hardware encoder check
```
