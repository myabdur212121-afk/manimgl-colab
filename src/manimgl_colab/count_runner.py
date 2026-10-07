"""Animation-counting pass for --jobs — runs INSIDE the ManimGL environment.

Dry-runs the scene (skip_animations, tiny resolution, no output) and prints
``NUM_PLAYS: <n>`` so the parallel renderer can split the animation ranges.

Runs on both start paths:
- cold:  ENV_PYTHON count_runner.py SCENE_FILE SCENE_NAME
- warm:  forked from the warm worker (engine already imported) via runpy.
"""

from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("PYGLET_HEADLESS", "true")
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import pyglet  # noqa: E402

pyglet.options["headless"] = True
pyglet.options["shadow_window"] = False

import importlib.util  # noqa: E402

scene_file, scene_name = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("usercell", scene_file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cls = getattr(module, scene_name)
scene = cls(
    window=None,
    camera_config={"resolution": (160, 90), "fps": 5},
    file_writer_config={
        "write_to_movie": False,
        "save_last_frame": False,
        "quiet": True,
    },
    skip_animations=True,
)
scene.run()
print("NUM_PLAYS:", scene.num_plays, flush=True)
