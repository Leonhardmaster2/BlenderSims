"""End-to-end smoke test: build, bake, render and export a tiny version of the teaser.

Runs in a real Blender:      blender -b -P tests/e2e.py -- /tmp/ht_e2e
or with the pip bpy module:  python tests/e2e.py /tmp/ht_e2e

Uses the built-in stand-in terrain, 8 fps, very low simulation resolution and
a few render samples, so it finishes in minutes on a CPU. It checks that every
stage produces its files; it says nothing about how the result looks.
"""
import os
import runpy
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

import hesiod_teaser  # noqa: E402
import manta_fix  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
out = os.path.abspath(argv[0] if argv else "/tmp/ht_e2e")
fps = int(argv[1]) if len(argv) > 1 else 8
os.makedirs(out, exist_ok=True)

manta_fix.apply()
hesiod_teaser.register()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "e2e.blend"))
st = hesiod_teaser.props.get_settings()
hesiod_teaser.props.master_scene()
st.terrain_source = "BUILTIN"
st.quality = "PREVIEW"
st.fps = fps
st.res_x, st.res_y = 640, 360
st.water_res = st.rock_res = st.snow_res = 40
st.use_motion_blur = False
bpy.ops.wm.save_mainfile()

t0 = time.time()
sys.argv = [sys.argv[0], "--", "--all", "--samples", "4", "--percent", "50"]
runpy.run_path(os.path.join(HERE, "..", "scripts", "teaser_cli.py"), run_name="__main__")

project = os.path.join(out, "hesiod_teaser")
ok = True
for kind in ("water", "rock", "snow"):
    scene = bpy.data.scenes["HT_" + kind.title()]
    frames = [f for f in os.listdir(os.path.join(project, "render", kind)) if f.endswith(".png")]
    need = scene.frame_end - scene.frame_start + 1
    print("E2E %-5s frames %d/%d  range %d-%d  %s" % (kind, len(frames), need, scene.frame_start,
                                                     scene.frame_end, scene.get("ht_sync", "")))
    ok &= len(frames) >= need
films = [f for f in os.listdir(project) if f.endswith(".mp4")]
print("E2E film:", films)
ok &= bool(films)
edit = hesiod_teaser.props.master_scene()
se = edit.sequence_editor
strips = se.strips if hasattr(se, "strips") else se.sequences
print("E2E strips:", sorted("%s[%d-%d]" % (s.name, s.frame_final_start, s.frame_final_end) for s in strips))
print("E2E %s in %.1f min" % ("PASSED" if ok else "FAILED", (time.time() - t0) / 60.0), flush=True)
os._exit(0 if ok else 1)
