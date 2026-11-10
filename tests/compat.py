"""Quick compatibility check for another Blender version: build all shots,
bake them at tiny resolution, render one frame of each and of the edit.

    blender -b -P tests/compat.py -- /tmp/ht_compat
    python tests/compat.py /tmp/ht_compat          (pip bpy module)
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

import hesiod_teaser  # noqa: E402
import manta_fix  # noqa: E402
from hesiod_teaser import edit, pipeline, props  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
out = os.path.abspath(argv[0] if argv else "/tmp/ht_compat")
os.makedirs(out, exist_ok=True)
manta_fix.apply()
hesiod_teaser.register()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "compat.blend"))
st = props.get_settings()
props.master_scene()
st.terrain_source = "BUILTIN"
st.quality = "PREVIEW"
st.fps = 12
st.res_x, st.res_y = 640, 360
st.water_res = st.rock_res = st.snow_res = 32
st.use_motion_blur = False

t0 = time.time()
pipeline.run_all(bpy.context, build=True, bake=True, render=False, final=False)
for kind in ("WATER", "ROCK", "SNOW"):
    scene = pipeline.shot_scene(kind)
    scene.cycles.samples = 2
    scene.render.resolution_percentage = 25
    scene.frame_set(scene.frame_end - 6)
    scene.render.filepath = os.path.join(out, kind.lower() + "_")
    pipeline.render_still(bpy.context, scene)
    print("COMPAT %s rendered frame %d (%s)" % (kind, scene.frame_current, scene.get("ht_sync", "")), flush=True)
notes = edit.assemble(bpy.context)
master = props.master_scene()
pipeline.activate(bpy.context, master)
print("COMPAT %s PASSED in %.1f min, edit notes: %d" % (bpy.app.version_string, (time.time() - t0) / 60.0, len(notes)), flush=True)
os._exit(0)
