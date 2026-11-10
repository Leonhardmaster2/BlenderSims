"""Run the Hesiod teaser pipeline without the UI (good for long bakes and renders).

    blender -b my_teaser.blend -P scripts/teaser_cli.py -- --all
    blender -b my_teaser.blend -P scripts/teaser_cli.py -- --build --bake --shots water,snow
    blender -b my_teaser.blend -P scripts/teaser_cli.py -- --render --final --quality FINAL

Steps (any combination, always run in this order):
    --build   create the shot scenes       --bake    bake the simulations
    --render  render the shot frames       --final   assemble the cut and export the MP4
    --all     all four

Options:
    --shots water,rock,snow     limit to some shots
    --quality PREVIEW|MEDIUM|FINAL
    --terrain NAME              terrain object to use (default: the Hesiod tile in the file)
    --builtin                   use the built-in stand-in terrain
    --samples N / --percent N   override render samples / resolution percentage (quick tests)
    --no-save                   do not save the .blend after each step

The .blend keeps its settings from the panel; the options above only override them.
"""

import argparse
import importlib
import os
import sys
import time

import bpy


def load_addon():
    for name in ("hesiod_teaser", "bl_ext.user_default.hesiod_teaser", "bl_ext.blender_org.hesiod_teaser"):
        try:
            mod = importlib.import_module(name)
            break
        except ImportError:
            mod = None
    if mod is None:   # not installed: use the copy next to this script
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        mod = importlib.import_module("hesiod_teaser")
    if not hasattr(bpy.types.Scene, "hesiod_teaser"):
        mod.register()
    return mod


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="teaser_cli.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    for step in ("build", "bake", "render", "final", "all", "builtin", "no-save"):
        ap.add_argument("--" + step, action="store_true")
    ap.add_argument("--shots", default="")
    ap.add_argument("--quality", default="")
    ap.add_argument("--terrain", default="")
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--percent", type=int, default=0)
    args = ap.parse_args(argv)
    if args.all:
        args.build = args.bake = args.render = args.final = True
    if not (args.build or args.bake or args.render or args.final):
        ap.print_help()
        return

    if not bpy.data.is_saved:
        sys.exit("Open a saved .blend:  blender -b file.blend -P scripts/teaser_cli.py -- --all")
    addon = load_addon()
    props = importlib.import_module(addon.__name__ + ".props")
    settings = props.get_settings(bpy.context)
    props.master_scene(bpy.context)
    if args.quality:
        settings.quality = args.quality.upper()
    if args.builtin:
        settings.terrain_source = "BUILTIN"
    if args.terrain:
        obj = bpy.data.objects.get(args.terrain)
        if obj is None:
            sys.exit("No object named '%s' in this file" % args.terrain)
        settings.terrain_object = obj
        settings.terrain_source = "OBJECT"
    shots = [s.strip().upper() for s in args.shots.split(",") if s.strip()] or None

    def log(message):
        print("[Hesiod Teaser] %s" % message, flush=True)
        if not args.no_save:
            bpy.ops.wm.save_mainfile()

    t0 = time.time()
    run = addon.pipeline.run_all
    if args.build:
        run(bpy.context, build=True, bake=False, render=False, final=False, shots=shots, log=log)
    for scene in bpy.data.scenes:           # quick-test overrides (a build resets them)
        if scene.name.startswith("HT_") or scene.hesiod_teaser.is_master:
            if args.samples and scene.name.startswith("HT_"):
                scene.cycles.samples = args.samples
            if args.percent:
                scene.render.resolution_percentage = args.percent
    if args.bake or args.render or args.final:
        run(bpy.context, build=False, bake=args.bake, render=args.render, final=args.final,
            shots=shots, log=log)
    log("done in %.1f min" % ((time.time() - t0) / 60.0))


main()
