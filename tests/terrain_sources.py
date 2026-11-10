"""Checks the two real terrain inputs: a Hesiod bridge tile and a heightmap file.

    blender -b -P tests/terrain_sources.py -- /tmp/ht_terrain
    python tests/terrain_sources.py /tmp/ht_terrain          (pip bpy module)

Builds a fake ``TerrainTile`` exactly the way the bridge does (a 1 m grid with
heights scaled by 0.12, a streamed texture, the ``hesiod_*`` properties),
then builds all three shots on it, and again from a 16-bit heightmap PNG.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import numpy as np  # noqa: E402

import hesiod_teaser  # noqa: E402
from hesiod_teaser import heightfield, pipeline, props  # noqa: E402
from hesiod_teaser.shots import common  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
out = os.path.abspath(argv[0] if argv else "/tmp/ht_terrain")
os.makedirs(out, exist_ok=True)
import manta_fix  # noqa: E402

manta_fix.apply()
hesiod_teaser.register()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "terrain.blend"))

# -- a tile as the Hesiod bridge makes it ------------------------------------
N = 256
ref = heightfield.builtin_terrain(seed=3, res=N)
h01 = (ref.h - ref.h.min()) / (ref.h.max() - ref.h.min())
bpy.ops.mesh.primitive_grid_add(x_subdivisions=N - 1, y_subdivisions=N - 1, size=1.0, calc_uvs=True)
tile = bpy.context.active_object
tile.name = "TerrainTile_0_1"
tile["hesiod_width"], tile["hesiod_height"], tile["hesiod_tid"] = N, N, 0
co = np.empty(len(tile.data.vertices) * 3, dtype=np.float32)
tile.data.vertices.foreach_get("co", co)
co[2::3] = h01.flatten().astype(np.float32) * 0.12
tile.data.vertices.foreach_set("co", co)
tile.data.update()
img = bpy.data.images.new("HesiodTexture_0", width=N, height=N, alpha=True)
rgba = np.dstack([h01 * 0.5 + 0.2, h01 * 0.45 + 0.2, h01 * 0.4 + 0.18, np.ones_like(h01)]).astype(np.float32)
img.pixels.foreach_set(rgba.ravel())
mat = bpy.data.materials.new("HesiodMat_0")
mat.use_nodes = True
nt = mat.node_tree
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
tile.data.materials.append(mat)

st = props.get_settings()
props.master_scene()
st.quality = "PREVIEW"
st.terrain_source = "OBJECT"
assert bpy.ops.hesiod_teaser.detect_terrain() == {"FINISHED"}
assert st.terrain_object == tile, "the bridge tile was not detected"
st.terrain_width = 2400.0
st.height_scale = ref.relief / (0.12 * 2400.0)

hf = common.load_terrain(st)
err = float(np.abs(hf.h - (ref.h - ref.h.min())).max())
print("TILE heightfield %s  cell %.2f m  relief %.0f m  max error vs source %.3f m  texture %s"
      % (hf.shape, hf.cell, hf.relief, err, hf.texture.name if hf.texture else None))
assert hf.shape == (N, N) and err < 0.5 and hf.texture == img

for kind in ("WATER", "ROCK", "SNOW"):
    scene = pipeline.build_shot(bpy.context, kind, hf)
    print("TILE built %-5s %s | %s | frames %d-%d" % (kind, scene["ht_site"], scene.get("ht_sun", ""),
                                                    scene.frame_start, scene.frame_end))

# an anchor object placed on the tile chooses the spot
anchor = bpy.data.objects.new("WaterHere", None)
bpy.context.scene.collection.objects.link(anchor)
anchor.location = (0.15, -0.2, 0.1)
st.water_anchor = anchor
bpy.context.view_layer.update()
site = common.resolve_site(st, hf, "WATER")
print("ANCHOR", site, site.note)
assert abs(site.x - (0.15 + 0.5) * 2400.0) < 15.0 and abs(site.y - (-0.2 + 0.5) * 2400.0) < 15.0
st.water_anchor = None

# -- a heightmap file ----------------------------------------------------------
path = os.path.join(out, "height.png")
himg = bpy.data.images.new("height", width=N, height=N, float_buffer=True, is_data=True)
himg.pixels.foreach_set(np.dstack([h01, h01, h01, np.ones_like(h01)]).astype(np.float32).ravel())
himg.filepath_raw = path
himg.file_format = "PNG"
scene = bpy.context.scene
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "BW"
scene.render.image_settings.color_depth = "16"
himg.save_render(path, scene=scene)
st.terrain_source = "HEIGHTMAP"
st.heightmap_path = path
st.heightmap_relief = ref.relief
hf2 = common.load_terrain(st)
err2 = float(np.abs(hf2.h - (ref.h - ref.h.min())).max())
print("HEIGHTMAP heightfield %s  relief %.0f m  max error vs source %.2f m" % (hf2.shape, hf2.relief, err2))
assert hf2.shape == (N, N) and err2 < 0.03 * ref.relief

# a flat, gentle terrain must still give usable shots (height boost + conditioning)
gentle = heightfield.Heightfield(ref.h * 0.18, ref.cell)
for kind in ("WATER", "ROCK", "SNOW"):
    s = heightfield.find_site(gentle, kind)
    print("GENTLE %-5s %s %s" % (kind, s, s.note))
    assert s.z_boost > 1.0 or kind == "WATER"
print("TERRAIN SOURCES PASSED", flush=True)
os._exit(0)
