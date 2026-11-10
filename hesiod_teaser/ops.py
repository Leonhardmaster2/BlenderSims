import os

import bpy
from bpy.props import EnumProperty

from . import edit, pipeline, props, timeline
from .shots import common

SHOT_ITEMS = (("WATER", "Water", ""), ("ROCK", "Rock", ""), ("SNOW", "Snow", ""))


def _need_saved(op):
    settings = props.get_settings()
    if settings.output_dir.startswith("//") and not bpy.data.is_saved:
        op.report({"ERROR"}, "Save the .blend first: caches and frames are stored next to it")
        return False
    return True


def _fail(op, exc):
    op.report({"ERROR"}, str(exc))
    return {"CANCELLED"}


class HT_OT_detect_terrain(bpy.types.Operator):
    bl_idname = "hesiod_teaser.detect_terrain"
    bl_label = "Find Hesiod Tile"
    bl_description = "Pick the terrain tile the Hesiod Blender bridge streamed into this file"

    def execute(self, context):
        tile = common.find_hesiod_tile()
        if tile is None:
            self.report({"WARNING"}, "No Hesiod tile found. Connect the bridge and stream a terrain, "
                                     "or pick any mesh by hand")
            return {"CANCELLED"}
        settings = props.get_settings(context)
        settings.terrain_object = tile
        settings.terrain_source = "OBJECT"
        self.report({"INFO"}, "Using '%s'" % tile.name)
        return {"FINISHED"}


class HT_OT_build(bpy.types.Operator):
    bl_idname = "hesiod_teaser.build"
    bl_label = "Build"
    bl_description = "Create the scene for this shot: terrain patch, simulation, camera, light, materials"
    bl_options = {"REGISTER", "UNDO"}
    shot: EnumProperty(items=SHOT_ITEMS + (("ALL", "All", ""),), default="ALL")

    def execute(self, context):
        if not _need_saved(self):
            return {"CANCELLED"}
        try:
            if self.shot == "ALL":
                scenes = pipeline.build_all(context)
                self.report({"INFO"}, "Built %d shots and the edit" % len(scenes))
            else:
                scene = pipeline.build_shot(context, self.shot)
                edit.assemble(context)
                self.report({"INFO"}, "Built %s (%s)" % (scene.name, scene.get("ht_site", "")))
        except Exception as exc:  # noqa: BLE001 - show any build problem to the user
            return _fail(self, exc)
        return {"FINISHED"}


def _watch_bake(kind):
    """Timer: once an interactive bake has finished, re-time the shot."""
    scene = pipeline.shot_scene(kind)
    if scene is None:
        return None
    try:
        _, d = pipeline._domain(scene)
    except RuntimeError:
        return None
    if d.is_cache_baking_any:
        return 1.0
    if d.has_cache_baked_data:
        try:
            pipeline.sync_shot(bpy.context, kind)
        except Exception as exc:  # noqa: BLE001
            print("[Hesiod Teaser] could not re-time %s: %s" % (kind, exc))
    return None


class HT_OT_bake(bpy.types.Operator):
    bl_idname = "hesiod_teaser.bake"
    bl_label = "Bake"
    bl_description = ("Bake the simulation. A single shot bakes in the background with a progress bar "
                      "(Esc cancels); 'All' bakes one after the other and blocks Blender until done")
    shot: EnumProperty(items=SHOT_ITEMS + (("ALL", "All", ""),), default="ALL")

    def execute(self, context):
        if not _need_saved(self):
            return {"CANCELLED"}
        settings = props.get_settings(context)
        try:
            if self.shot == "ALL":
                for kind in pipeline.enabled_shots(settings):
                    pipeline.bake_shot(context, kind)
                self.report({"INFO"}, "All simulations baked")
            else:
                pipeline.bake_shot(context, self.shot, interactive=not bpy.app.background)
                if not bpy.app.background:
                    kind = self.shot
                    bpy.app.timers.register(lambda: _watch_bake(kind), first_interval=2.0)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        return {"FINISHED"}


class HT_OT_free(bpy.types.Operator):
    bl_idname = "hesiod_teaser.free_bake"
    bl_label = "Free Bake"
    bl_description = "Delete the baked simulation of this shot"
    shot: EnumProperty(items=SHOT_ITEMS)

    def execute(self, context):
        try:
            pipeline.free_bake(context, self.shot)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        return {"FINISHED"}


class HT_OT_sync(bpy.types.Operator):
    bl_idname = "hesiod_teaser.sync"
    bl_label = "Re-time"
    bl_description = ("Match the shot to its baked simulation: Water and Rock move the frame range so the "
                      "cut lands on the impact, Snow moves the camera to where the cloud front arrives on time")
    shot: EnumProperty(items=SHOT_ITEMS)

    def execute(self, context):
        try:
            message = pipeline.sync_shot(context, self.shot)
            edit.assemble(context)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        self.report({"INFO"}, message or "Nothing to re-time (is the simulation baked?)")
        return {"FINISHED"}


class HT_OT_render(bpy.types.Operator):
    bl_idname = "hesiod_teaser.render"
    bl_label = "Render"
    bl_description = ("Render the frames of a shot to the project folder. A single shot renders in the "
                      "background with a progress bar; 'All' renders one after the other and blocks Blender")
    shot: EnumProperty(items=SHOT_ITEMS + (("ALL", "All", ""),), default="ALL")

    def execute(self, context):
        if not _need_saved(self):
            return {"CANCELLED"}
        settings = props.get_settings(context)
        try:
            if self.shot == "ALL":
                for kind in pipeline.enabled_shots(settings):
                    pipeline.render_shot(context, kind)
                edit.assemble(context)
            else:
                pipeline.render_shot(context, self.shot, interactive=not bpy.app.background)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        return {"FINISHED"}


class HT_OT_assemble(bpy.types.Operator):
    bl_idname = "hesiod_teaser.assemble"
    bl_label = "Assemble Edit"
    bl_description = "Rebuild the 25 second cut in the sequencer: titles, shots, hard cuts, white-out, end card"

    def execute(self, context):
        try:
            notes = edit.assemble(context)
            pipeline.activate(context, props.master_scene(context))
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        for note in notes:
            self.report({"WARNING"}, note)
        if not notes:
            self.report({"INFO"}, "Edit assembled from rendered frames")
        return {"FINISHED"}


class HT_OT_export(bpy.types.Operator):
    bl_idname = "hesiod_teaser.export"
    bl_label = "Export Film"
    bl_description = "Assemble the edit and render it to an MP4 in the project folder"

    def execute(self, context):
        if not _need_saved(self):
            return {"CANCELLED"}
        try:
            pipeline.render_final(context, interactive=not bpy.app.background)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        return {"FINISHED"}


class HT_OT_everything(bpy.types.Operator):
    bl_idname = "hesiod_teaser.everything"
    bl_label = "Build, Bake, Render, Export"
    bl_description = ("Do the whole teaser in one go. Blender is blocked until it has finished, which can take "
                      "many hours at Final quality - for long runs use scripts/teaser_cli.py from a terminal")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not _need_saved(self):
            return {"CANCELLED"}
        try:
            pipeline.run_all(context)
        except Exception as exc:  # noqa: BLE001
            return _fail(self, exc)
        return {"FINISHED"}


class HT_OT_view(bpy.types.Operator):
    bl_idname = "hesiod_teaser.view"
    bl_label = "View"
    bl_description = "Switch the window to this scene"
    shot: EnumProperty(items=SHOT_ITEMS + (("EDIT", "Edit", ""),), default="EDIT")

    def execute(self, context):
        scene = props.master_scene(context) if self.shot == "EDIT" else pipeline.shot_scene(self.shot)
        if scene is None:
            self.report({"WARNING"}, "Not built yet")
            return {"CANCELLED"}
        pipeline.activate(context, scene)
        return {"FINISHED"}


class HT_OT_open_folder(bpy.types.Operator):
    bl_idname = "hesiod_teaser.open_folder"
    bl_label = "Open Project Folder"
    bl_description = "Show the caches, frames and exported film in the file browser"

    def execute(self, context):
        path = common.project_dir(props.get_settings(context))
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


CLASSES = (HT_OT_detect_terrain, HT_OT_build, HT_OT_bake, HT_OT_free, HT_OT_sync, HT_OT_render,
           HT_OT_assemble, HT_OT_export, HT_OT_everything, HT_OT_view, HT_OT_open_folder)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
