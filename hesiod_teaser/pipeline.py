"""Build -> bake -> render -> assemble. Used by the UI operators and the CLI."""

import os
import time

import bpy

from . import props, timeline
from .shots import common

_TERRAIN_CACHE = {}


def _builders():
    import importlib
    return {k: importlib.import_module(".shots." + k.lower(), __package__) for k in timeline.SHOTS}


def enabled_shots(settings):
    return [k for k in timeline.SHOTS if getattr(settings, k.lower() + "_enabled")]


def shot_scene(kind):
    return bpy.data.scenes.get(common.SCENE_NAMES[kind])


def activate(context, scene):
    """Show ``scene`` in the window (no-op in background mode)."""
    win = getattr(context, "window", None)
    if win is not None and win.scene != scene:
        win.scene = scene


def _override(context, scene, obj=None):
    kw = dict(scene=scene, view_layer=scene.view_layers[0])
    if obj is not None:
        kw.update(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj])
    return context.temp_override(**kw)


# ----------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------

def load_terrain(settings, use_cache=False):
    if use_cache and "hf" in _TERRAIN_CACHE:
        return _TERRAIN_CACHE["hf"]
    hf = common.load_terrain(settings)
    _TERRAIN_CACHE["hf"] = hf
    return hf


def build_shot(context, kind, hf=None):
    settings = props.get_settings(context)
    master = props.master_scene(context)
    if hf is None:
        hf = load_terrain(settings)
    import importlib
    scene = importlib.import_module('.shots.' + kind.lower(), __package__).build(context, settings, hf)
    activate(context, master)
    return scene


def build_all(context):
    settings = props.get_settings(context)
    hf = load_terrain(settings)
    scenes = [build_shot(context, kind, hf) for kind in enabled_shots(settings)]
    from . import edit
    edit.assemble(context)
    return scenes


# ----------------------------------------------------------------------------
# bake
# ----------------------------------------------------------------------------

def is_baked(kind):
    scene = shot_scene(kind)
    if scene is None:
        return False
    dom = bpy.data.objects.get(scene.get("ht_domain", ""))
    if dom is None:
        return False
    for mod in dom.modifiers:
        if mod.type == "FLUID" and mod.fluid_type == "DOMAIN":
            return bool(mod.domain_settings.has_cache_baked_data)
    return False


def _domain(scene):
    dom = bpy.data.objects.get(scene.get("ht_domain", ""))
    if dom is None:
        raise RuntimeError("Shot '%s' has no fluid domain - build it first" % scene.name)
    for mod in dom.modifiers:
        if mod.type == "FLUID" and mod.fluid_type == "DOMAIN":
            return dom, mod.domain_settings
    raise RuntimeError("Domain object of '%s' lost its Fluid modifier" % scene.name)


def free_bake(context, kind):
    scene = shot_scene(kind)
    if scene is None:
        return
    dom, _ = _domain(scene)
    activate(context, scene)
    with _override(context, scene, dom):
        bpy.ops.fluid.free_all()
    activate(context, props.master_scene(context))


def bake_shot(context, kind, interactive=False):
    """Bake the simulation of one shot. Blocks unless ``interactive``."""
    scene = shot_scene(kind)
    if scene is None:
        raise RuntimeError("Build the %s shot first" % kind.title())
    import importlib
    builder = importlib.import_module('.shots.' + kind.lower(), __package__)
    dom, d = _domain(scene)
    os.makedirs(bpy.path.abspath(d.cache_directory), exist_ok=True)
    activate(context, scene)
    if hasattr(builder, "pre_bake"):
        builder.pre_bake(context, scene)
    t0 = time.time()
    with _override(context, scene, dom):
        if d.has_cache_baked_any:
            bpy.ops.fluid.free_all()
        if interactive:
            bpy.ops.fluid.bake_all("INVOKE_DEFAULT")
            return scene
        bpy.ops.fluid.bake_all()
    scene["ht_bake_seconds"] = round(time.time() - t0, 1)
    sync_shot(context, kind)
    activate(context, props.master_scene(context))
    return scene


def sync_shot(context, kind):
    """Re-time a shot to what its baked simulation actually does."""
    import importlib
    scene = shot_scene(kind)
    builder = importlib.import_module('.shots.' + kind.lower(), __package__)
    if scene is None or not hasattr(builder, "sync"):
        return None
    activate(context, scene)
    with _override(context, scene):
        message = builder.sync(context, scene)
    scene["ht_sync"] = message or "no change"
    return message


# ----------------------------------------------------------------------------
# render
# ----------------------------------------------------------------------------

def render_still(context, scene):
    """Render the current frame of ``scene`` to its output path.

    The scene has to be the active one while it renders: Blender only reads
    fluid caches for the scene the window is showing.
    """
    activate(context, scene)
    with _override(context, scene):
        bpy.ops.render.render(write_still=True)


def render_shot(context, kind, interactive=False):
    """Render a shot's frame range to PNGs in <project>/render/<shot>/."""
    scene = shot_scene(kind)
    if scene is None:
        raise RuntimeError("Build the %s shot first" % kind.title())
    settings = props.get_settings(context)
    common.render_dir(settings, kind)
    activate(context, scene)
    with _override(context, scene):
        if interactive:
            bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
            return scene
        bpy.ops.render.render(animation=True)
    activate(context, props.master_scene(context))
    return scene


def render_final(context, interactive=False):
    """Assemble the edit and export the finished film."""
    from . import edit
    notes = edit.assemble(context)
    master = props.master_scene(context)
    activate(context, master)
    with _override(context, master):
        if interactive:
            bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
        else:
            bpy.ops.render.render(animation=True)
    return notes


def run_all(context, build=True, bake=True, render=True, final=True, shots=None, log=print):
    """The whole teaser, start to finish (blocking)."""
    settings = props.get_settings(context)
    kinds = [k for k in enabled_shots(settings) if shots is None or k in shots]
    if build:
        hf = load_terrain(settings)
        for kind in kinds:
            t0 = time.time()
            build_shot(context, kind, hf)
            log("built %s in %.0f s" % (kind.title(), time.time() - t0))
    if bake:
        for kind in kinds:
            t0 = time.time()
            bake_shot(context, kind)
            scene = shot_scene(kind)
            log("baked %s in %.0f s (%s)" % (kind.title(), time.time() - t0, scene.get("ht_sync", "")))
    if render:
        for kind in kinds:
            t0 = time.time()
            render_shot(context, kind)
            log("rendered %s in %.0f s" % (kind.title(), time.time() - t0))
    from . import edit
    notes = edit.assemble(context)
    if final:
        notes = render_final(context)
        log("exported the film to %s" % common.project_dir(settings))
    for note in notes:
        log(note)
    return notes
