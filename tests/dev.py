"""Development harness: build / bake / render single shots with the bpy module.

    blender -b -P tests/dev.py -- water --bake --render 150,160 --res 48
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bpy  # noqa: E402

import hesiod_teaser  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("shot")
ap.add_argument("--out", default="/tmp/ht_dev")
ap.add_argument("--bake", action="store_true")
ap.add_argument("--render", default="")
ap.add_argument("--res", type=int, default=0)
ap.add_argument("--quality", default="PREVIEW")
ap.add_argument("--samples", type=int, default=12)
ap.add_argument("--percent", type=int, default=25)
ap.add_argument("--save", action="store_true")
ap.add_argument("--load", action="store_true")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
args = ap.parse_args(argv)

hesiod_teaser.register()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manta_fix  # noqa: E402
print('manta fix:', manta_fix.apply())
from hesiod_teaser import props  # noqa: E402
from hesiod_teaser.shots import common  # noqa: E402

os.makedirs(args.out, exist_ok=True)
blend = os.path.join(args.out, "dev_%s.blend" % args.shot)
kind = args.shot.upper()
if args.load:
    bpy.ops.wm.open_mainfile(filepath=blend)
    scene = bpy.data.scenes[common.SCENE_NAMES[kind]]
else:
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    st = props.get_settings()
    props.master_scene()
    st.terrain_source = "BUILTIN"
    st.quality = args.quality
    if args.res:
        setattr(st, kind.lower() + "_res", args.res)
    t = time.time()
    scene = hesiod_teaser.build_shot(bpy.context, kind)
    print("BUILD %.1fs" % (time.time() - t), {k: scene[k] for k in scene.keys() if k.startswith("ht_")},
          "range", scene.frame_start, scene.frame_end)

if args.bake:
    t = time.time()
    hesiod_teaser.bake_shot(bpy.context, kind)
    print("BAKE %.1fs" % (time.time() - t), {k: scene[k] for k in scene.keys() if k.startswith("ht_")},
          "range", scene.frame_start, scene.frame_end)

if args.render:
    scene.cycles.samples = args.samples
    scene.render.resolution_percentage = args.percent
    scene.render.use_motion_blur = False
    for tok in args.render.split(","):
        if tok.startswith("s"):
            f = scene.frame_start + int(tok[1:] or 0)
        elif tok.startswith("e"):
            f = scene.frame_end + int(tok[1:] or 0)
        else:
            f = int(tok)
        scene.frame_set(f)
        scene.render.filepath = os.path.join(args.out, "%s_%04d.png" % (kind.lower(), f))
        t = time.time()
        hesiod_teaser.pipeline.render_still(bpy.context, scene)
        print("RENDER frame %d %.1fs -> %s" % (f, time.time() - t, scene.render.filepath))
if args.save:
    bpy.ops.wm.save_mainfile()
