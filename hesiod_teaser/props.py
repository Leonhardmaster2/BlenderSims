import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

GREEK_DEFAULT = "ἤτοι μὲν πρώτιστα Χάος γένετ᾽· αὐτὰρ ἔπειτα\nΓαῖ᾽ εὐρύστερνος, πάντων ἕδος ἀσφαλὲς αἰεί"

QUALITY = {
    #           liquid, dust, powder, noise upres, samples, res %, particle count scale
    "PREVIEW": dict(water=72, rock=64, snow=72, upres=0, samples=24, percent=50, detail=0.5),
    "MEDIUM": dict(water=144, rock=112, snow=128, upres=2, samples=96, percent=100, detail=1.0),
    "FINAL": dict(water=240, rock=176, snow=200, upres=2, samples=192, percent=100, detail=1.5),
}


def _is_mesh(self, obj):
    return obj.type == "MESH"


class HesiodTeaserSettings(bpy.types.PropertyGroup):
    is_master: BoolProperty(default=False)
    status: StringProperty(default="")

    # -- output ---------------------------------------------------------------
    quality: EnumProperty(
        name="Quality",
        description="Simulation resolution and render samples for all three shots",
        items=(("PREVIEW", "Preview", "Fast: check timing and framing (minutes)"),
               ("MEDIUM", "Medium", "Good-looking test renders"),
               ("FINAL", "Final", "Full quality: long bakes, final frames")),
        default="MEDIUM")
    fps: IntProperty(name="FPS", default=24, min=12, max=60)
    res_x: IntProperty(name="Width", default=1920, min=320, max=7680)
    res_y: IntProperty(name="Height", default=1080, min=180, max=4320)
    output_dir: StringProperty(
        name="Project Folder", subtype="DIR_PATH", default="//hesiod_teaser/",
        description="Simulation caches, rendered frames and the final film go here")
    seed: IntProperty(name="Seed", default=7, min=0, description="Varies rocks, gully, slab and detail noise")
    use_motion_blur: BoolProperty(name="Motion Blur", default=True)
    use_gpu: BoolProperty(name="Use GPU if available", default=True)

    # -- terrain --------------------------------------------------------------
    terrain_source: EnumProperty(
        name="Terrain",
        items=(("OBJECT", "Hesiod Tile", "A terrain mesh in this file (streamed by the Hesiod Blender bridge)"),
               ("HEIGHTMAP", "Heightmap File", "A heightmap image exported from Hesiod"),
               ("BUILTIN", "Built-in Stand-in", "Procedural placeholder mountain, to try the sims without a terrain")),
        default="OBJECT")
    terrain_object: PointerProperty(name="Terrain Object", type=bpy.types.Object, poll=_is_mesh,
                                    description="The TerrainTile the Hesiod bridge created (any mesh works)")
    heightmap_path: StringProperty(name="Heightmap", subtype="FILE_PATH")
    terrain_width: FloatProperty(
        name="Real Width", default=2400.0, min=50.0, soft_max=20000.0, unit="LENGTH",
        description="How wide the terrain is in the real world. The bridge tile is 1 m across, "
                    "so this is what gives the simulations their scale")
    height_scale: FloatProperty(
        name="Height Scale", default=2.2, min=0.05, soft_max=6.0,
        description="Vertical exaggeration applied to a terrain object (the bridge streams heights at 0.12 of the width)")
    heightmap_relief: FloatProperty(name="Relief", default=750.0, min=1.0, unit="LENGTH",
                                    description="Height difference between black and white of the heightmap")
    use_hesiod_texture: BoolProperty(
        name="Colour from Hesiod Texture", default=True,
        description="Use the texture the bridge streamed as the rock colour (detail is added procedurally)")

    # -- titles ---------------------------------------------------------------
    greek_line: StringProperty(name="Greek Line", default=GREEK_DEFAULT,
                               description="Opening line. Use \\n for a line break")
    title_text: StringProperty(name="Logo Text", default="HESIOD")
    version_text: StringProperty(name="Version", default="0.7")
    date_text: StringProperty(name="Date", default="DATE TBA")
    logo_path: StringProperty(name="Logo Image", subtype="FILE_PATH",
                              description="Optional image used instead of the logo text")
    font_path: StringProperty(name="Font", subtype="FILE_PATH",
                              description="Optional .ttf/.otf for the titles (must contain polytonic Greek)")

    # -- water ----------------------------------------------------------------
    water_enabled: BoolProperty(name="Water", default=True)
    water_anchor: PointerProperty(name="Location", type=bpy.types.Object,
                                  description="Optional: an object placed on the terrain where the gully shot should be. Empty = find automatically")
    water_res: IntProperty(name="Resolution", default=0, min=0, max=512,
                           description="Liquid domain resolution. 0 = from the quality preset")
    water_turbidity: FloatProperty(name="Turbidity", default=0.3, min=0.0, max=1.0, subtype="FACTOR",
                                   description="0 = clear meltwater, 1 = silty flood")
    water_gully_depth: FloatProperty(name="Gully Depth", default=1.1, min=0.0, max=4.0, unit="LENGTH",
                                     description="A channel this deep is cut along the fall line so the surge has a bed to run in. 0 = leave the Hesiod terrain as is")
    water_gully_width: FloatProperty(name="Gully Width", default=5.0, min=1.5, max=14.0, unit="LENGTH")
    water_surge_speed: FloatProperty(name="Surge Speed", default=9.0, min=1.0, max=20.0,
                                     description="Speed of the water entering the gully (m/s)")
    water_surge_height: FloatProperty(name="Surge Height", default=1.7, min=0.4, max=5.0, unit="LENGTH")
    water_whitewater: BoolProperty(name="Whitewater", default=True,
                                   description="Simulate spray, foam and bubbles")

    # -- rock -----------------------------------------------------------------
    rock_enabled: BoolProperty(name="Rock", default=True)
    rock_anchor: PointerProperty(name="Location", type=bpy.types.Object,
                                 description="Optional: an object placed on the terrain where the rockfall should be")
    rock_res: IntProperty(name="Resolution", default=0, min=0, max=512,
                          description="Dust domain resolution. 0 = from the quality preset")
    rock_count: IntProperty(name="Boulders", default=11, min=3, max=40)
    rock_size: FloatProperty(name="Boulder Size", default=1.0, min=0.3, max=3.0, unit="LENGTH",
                             description="Typical boulder radius")
    rock_dust: FloatProperty(name="Dust", default=1.0, min=0.1, max=4.0,
                             description="How thick the dust cloud is")
    rock_cut_delay: IntProperty(name="Cut After Hit", default=5, min=0, max=24,
                                description="Frames between the first boulder reaching the camera and the cut to black")

    # -- snow -----------------------------------------------------------------
    snow_enabled: BoolProperty(name="Snow", default=True)
    snow_anchor: PointerProperty(name="Location", type=bpy.types.Object,
                                 description="Optional: an object placed on the terrain where the slab should release")
    snow_res: IntProperty(name="Resolution", default=0, min=0, max=512,
                          description="Powder-cloud domain resolution. 0 = from the quality preset")
    snow_depth: FloatProperty(name="Snow Depth", default=1.9, min=0.3, max=5.0, unit="LENGTH")
    slab_thickness: FloatProperty(name="Slab Thickness", default=1.2, min=0.3, max=3.0, unit="LENGTH",
                                  description="Depth of the layer that releases; the crown wall shows the snow layers")
    slab_width: FloatProperty(name="Slab Width", default=64.0, min=15.0, max=160.0, unit="LENGTH")
    slab_length: FloatProperty(name="Slab Length", default=40.0, min=10.0, max=120.0, unit="LENGTH")
    snow_cloud: FloatProperty(name="Powder Cloud", default=1.0, min=0.1, max=4.0,
                              description="How thick the powder cloud is")

    # -- sound (optional) -----------------------------------------------------
    sound_wind: StringProperty(name="Wind", subtype="FILE_PATH")
    sound_roar: StringProperty(name="Water Roar", subtype="FILE_PATH")
    sound_rock: StringProperty(name="Rockfall", subtype="FILE_PATH")
    sound_crack: StringProperty(name="Crack", subtype="FILE_PATH")
    sound_rumble: StringProperty(name="Avalanche Rumble", subtype="FILE_PATH")

    def preset(self):
        return QUALITY[self.quality]


def get_settings(context=None):
    """The one settings block of the file (lives on the master / edit scene)."""
    for scene in bpy.data.scenes:
        if scene.hesiod_teaser.is_master:
            return scene.hesiod_teaser
    context = context or bpy.context
    return context.scene.hesiod_teaser


def master_scene(context=None):
    for scene in bpy.data.scenes:
        if scene.hesiod_teaser.is_master:
            return scene
    context = context or bpy.context
    scene = context.scene
    if scene.name.startswith("HT_"):
        scene = bpy.data.scenes.new("Teaser Edit")
    scene.hesiod_teaser.is_master = True
    return scene


def register():
    bpy.utils.register_class(HesiodTeaserSettings)
    bpy.types.Scene.hesiod_teaser = PointerProperty(type=HesiodTeaserSettings)


def unregister():
    del bpy.types.Scene.hesiod_teaser
    bpy.utils.unregister_class(HesiodTeaserSettings)
