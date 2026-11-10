import bpy

from . import edit, pipeline, props, timeline
from .shots import common

SHOT_PROPS = {
    "WATER": ("water_turbidity", "water_gully_depth", "water_gully_width", "water_surge_speed",
              "water_surge_height", "water_whitewater", "water_res", "water_anchor"),
    "ROCK": ("rock_count", "rock_size", "rock_dust", "rock_cut_delay", "rock_res", "rock_anchor"),
    "SNOW": ("snow_depth", "slab_thickness", "slab_width", "slab_length", "snow_cloud", "snow_res",
             "snow_anchor"),
}
SHOT_ICONS = {"WATER": "MOD_FLUIDSIM", "ROCK": "MESH_ICOSPHERE", "SNOW": "FREEZE"}


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hesiod Teaser"


class HT_PT_main(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_main"
    bl_label = "Hesiod Teaser"

    def draw(self, context):
        layout = self.layout
        st = props.get_settings(context)
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("hesiod_teaser.build", text="1  Build All Shots", icon="SCENE_DATA").shot = "ALL"
        col.operator("hesiod_teaser.bake", text="2  Bake All Simulations", icon="PHYSICS").shot = "ALL"
        col.operator("hesiod_teaser.render", text="3  Render All Shots", icon="RENDER_ANIMATION").shot = "ALL"
        col.operator("hesiod_teaser.export", text="4  Export Film", icon="FILE_MOVIE")
        row = layout.row(align=True)
        row.operator("hesiod_teaser.everything", text="Do Everything", icon="PLAY")
        row.operator("hesiod_teaser.open_folder", text="", icon="FILE_FOLDER")
        row = layout.row(align=True)
        row.prop(st, "quality", expand=True)
        if not bpy.data.is_saved:
            layout.label(text="Save the .blend first", icon="ERROR")


class HT_PT_terrain(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_terrain"
    bl_label = "Terrain"
    bl_parent_id = "HT_PT_main"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = props.get_settings(context)
        layout.prop(st, "terrain_source")
        if st.terrain_source == "OBJECT":
            row = layout.row(align=True)
            row.prop(st, "terrain_object", text="Tile")
            row.operator("hesiod_teaser.detect_terrain", text="", icon="VIEWZOOM")
            layout.prop(st, "terrain_width")
            layout.prop(st, "height_scale")
            layout.prop(st, "use_hesiod_texture")
            if st.terrain_object is None and common.find_hesiod_tile() is None:
                layout.label(text="No tile yet: stream one with the bridge", icon="INFO")
        elif st.terrain_source == "HEIGHTMAP":
            layout.prop(st, "heightmap_path")
            layout.prop(st, "terrain_width")
            layout.prop(st, "heightmap_relief")
        else:
            layout.label(text="Procedural stand-in mountain", icon="INFO")
        layout.prop(st, "seed")


class HT_PT_shots(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_shots"
    bl_label = "Shots"
    bl_parent_id = "HT_PT_main"

    def draw(self, context):
        layout = self.layout
        st = props.get_settings(context)
        for kind in timeline.SHOTS:
            low = kind.lower()
            box = layout.box()
            head = box.row(align=True)
            head.prop(st, low + "_enabled", text=kind.title(), icon=SHOT_ICONS[kind])
            scene = pipeline.shot_scene(kind)
            head.operator("hesiod_teaser.view", text="", icon="HIDE_OFF").shot = kind
            if not getattr(st, low + "_enabled"):
                continue
            if scene is None:
                box.label(text="Not built", icon="DOT")
            else:
                baked = pipeline.is_baked(kind)
                done, total = edit.count_rendered(st, kind)
                box.label(text="Built   %s   %d/%d frames" % ("Baked" if baked else "Not baked", done, total),
                          icon="CHECKMARK" if baked and done == total else "DOT")
                note = scene.get("ht_sync", "")
                if note:
                    box.label(text=str(note), icon="TIME")
            row = box.row(align=True)
            row.operator("hesiod_teaser.build", text="Build").shot = kind
            row.operator("hesiod_teaser.bake", text="Bake").shot = kind
            row.operator("hesiod_teaser.sync", text="", icon="TIME").shot = kind
            row.operator("hesiod_teaser.render", text="Render").shot = kind
            row.operator("hesiod_teaser.free_bake", text="", icon="TRASH").shot = kind
            col = box.column(align=True)
            col.use_property_split = True
            col.use_property_decorate = False
            for name in SHOT_PROPS[kind]:
                col.prop(st, name)


class HT_PT_titles(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_titles"
    bl_label = "Titles and Edit"
    bl_parent_id = "HT_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = props.get_settings(context)
        for name in ("greek_line", "title_text", "version_text", "date_text", "logo_path", "font_path"):
            layout.prop(st, name)
        row = layout.row(align=True)
        row.operator("hesiod_teaser.assemble", icon="SEQUENCE")
        row.operator("hesiod_teaser.view", text="", icon="HIDE_OFF").shot = "EDIT"


class HT_PT_output(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_output"
    bl_label = "Output"
    bl_parent_id = "HT_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = props.get_settings(context)
        layout.prop(st, "output_dir")
        row = layout.row(align=True)
        row.prop(st, "res_x")
        row.prop(st, "res_y")
        layout.prop(st, "fps")
        layout.prop(st, "use_motion_blur")
        layout.prop(st, "use_gpu")


class HT_PT_sound(_Panel, bpy.types.Panel):
    bl_idname = "HT_PT_sound"
    bl_label = "Sound (optional)"
    bl_parent_id = "HT_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = props.get_settings(context)
        for name in ("sound_wind", "sound_roar", "sound_rock", "sound_crack", "sound_rumble"):
            layout.prop(st, name)


CLASSES = (HT_PT_main, HT_PT_terrain, HT_PT_shots, HT_PT_titles, HT_PT_output, HT_PT_sound)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
