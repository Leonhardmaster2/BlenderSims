"""Shared scene plumbing for the three simulated shots."""

import math
import os
import shutil

import bpy
import numpy as np
from mathutils import Vector

from .. import heightfield as hfmod
from .. import lighting, timeline
from ..compat import set_enum, set_if, set_image_output

SCENE_NAMES = {"WATER": "HT_Water", "ROCK": "HT_Rock", "SNOW": "HT_Snow"}


# ----------------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------------

def project_dir(settings):
    path = bpy.path.abspath(settings.output_dir)
    if settings.output_dir.startswith("//") and not bpy.data.is_saved:
        path = os.path.join(bpy.app.tempdir, "hesiod_teaser")
    return os.path.normpath(path)


def cache_dir(settings, kind, fresh=False):
    path = os.path.join(project_dir(settings), "cache", kind.lower())
    if fresh and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def render_dir(settings, kind):
    path = os.path.join(project_dir(settings), "render", kind.lower())
    os.makedirs(path, exist_ok=True)
    return path


def render_prefix(kind):
    return kind.lower() + "_"


# ----------------------------------------------------------------------------
# terrain
# ----------------------------------------------------------------------------

def find_hesiod_tile():
    """The newest visible tile the Hesiod bridge streamed, if there is one."""
    tiles = [o for o in bpy.data.objects
             if o.type == "MESH" and ("hesiod_tid" in o or o.name.startswith("TerrainTile"))]
    tiles.sort(key=lambda o: (o.hide_get() if o.name in bpy.context.view_layer.objects else True, o.name))
    return tiles[0] if tiles else None


def load_terrain(settings):
    """Resolve the terrain choice into a metric heightfield."""
    src = settings.terrain_source
    if src == "OBJECT":
        obj = settings.terrain_object or find_hesiod_tile()
        if obj is None:
            raise RuntimeError("No terrain object set. Stream a tile with the Hesiod bridge and pick it, "
                               "or switch Terrain to the built-in stand-in")
        hf = hfmod.from_object(obj, settings.terrain_width, settings.height_scale)
        if not settings.use_hesiod_texture:
            hf.texture = None
        return hf
    if src == "HEIGHTMAP":
        if not settings.heightmap_path:
            raise RuntimeError("No heightmap file set")
        return hfmod.from_image(settings.heightmap_path, settings.terrain_width, settings.heightmap_relief)
    return hfmod.builtin_terrain(seed=settings.seed)


def resolve_site(settings, hf, kind):
    """Automatic site, or the user's anchor object projected onto the terrain."""
    anchor = getattr(settings, kind.lower() + "_anchor")
    auto = hfmod.find_site(hf, kind)
    if anchor is None:
        return auto
    obj = settings.terrain_object or find_hesiod_tile()
    if settings.terrain_source != "OBJECT" or obj is None:
        return auto
    # world position -> metric terrain coordinates (same mapping as from_object)
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo_x = min(c.x for c in corners)
    lo_y = min(c.y for c in corners)
    ext = max(c.x for c in corners) - lo_x
    s = settings.terrain_width / max(ext, 1e-9)
    p = anchor.matrix_world.translation
    x = min(max((p.x - lo_x) * s, 0.0), hf.width)
    y = min(max((p.y - lo_y) * s, 0.0), hf.depth)
    sm = hf.decimated(384).smoothed(max(8.0, hf.cell * 1.5))
    gx, gy = sm.grad_at(x, y)
    yaw = math.atan2(-float(gx), float(gy))
    return hfmod.Site(x, y, yaw, auto.z_boost, 0.0, "placed by anchor '%s'" % anchor.name)


def condition_slope(stage, lo_deg, hi_deg, y_from, y_to, concavity=0.0, half_width=None):
    """Make sure the working area is usable for the shot, whatever the terrain.

    Looks at the broad fall-line profile (averaged across a central band) and
    reshapes it only as far as needed: the mean slope is clamped into
    [lo_deg, hi_deg] and bulges that would hide the upper slope from a camera
    at the bottom are straightened (``concavity`` > 0 makes it steepen with
    height, like a real face). Fine relief is left untouched, and the change
    fades out sideways and towards the rim. Returns the mean slope in degrees.
    """
    from ..heightfield import gaussian_blur, smoothstep

    gx, gy = stage.fine_xy()
    z = stage.fine()
    ys = gy[:, 0]
    half_width = half_width or 0.22 * stage.width
    band = (np.abs(gx) < half_width).astype(np.float64)
    profile = (z * band).sum(axis=1) / band.sum(axis=1)
    profile = gaussian_blur(profile[:, None], 5.0 / stage.cell)[:, 0]

    z_a, z_b = float(np.interp(y_from, ys, profile)), float(np.interp(y_to, ys, profile))
    span = y_to - y_from
    tan_now = (z_b - z_a) / span
    tan_new = min(max(tan_now, math.tan(math.radians(lo_deg))), math.tan(math.radians(hi_deg)))
    t = (ys - y_from) / span
    inner = z_a + tan_new * span * (t + concavity * t * (t - 1.0))
    below = z_a + tan_new * span * (1.0 - concavity) * t          # straight continuation
    above = z_a + tan_new * span * (1.0 + (1.0 + concavity) * (t - 1.0))
    target = np.where(t < 0.0, below, np.where(t > 1.0, above, inner))
    # only correct what is wrong: keep the terrain's own profile where it is already fine
    delta = target - profile
    if concavity <= 0.0:
        delta = (tan_new - tan_now) * (ys - y_from)
    lateral = 1.0 - smoothstep(half_width, 1.7 * half_width, np.abs(gx))
    stage.apply(z + delta[:, None] * lateral)
    stage.invalidate()
    return math.degrees(math.atan(tan_new))


def line_of_sight(loc, eye, target, samples=48, clearance=0.15):
    """True if the terrain does not block the straight line eye -> target."""
    t = np.linspace(0.04, 0.97, samples)
    x = eye[0] + (target[0] - eye[0]) * t
    y = eye[1] + (target[1] - eye[1]) * t
    z = eye[2] + (target[2] - eye[2]) * t
    return bool(np.all(loc.sample(x, y) + clearance < z))


def best_viewpoint(loc, candidates, targets, eye_height):
    """Among ground positions, the one that sees most of the targets.

    The eye is raised (up to a few metres, as if on a boulder or a tripod)
    only if nothing lower sees enough. Returns (x, y, z).
    """
    best, best_score = None, -1.0
    for lift in (0.0, 0.8, 1.8, 3.2, 5.0):
        for (x, y) in candidates:
            eye = (x, y, float(loc.sample(x, y)) + eye_height + lift)
            seen = sum(line_of_sight(loc, eye, tgt) for tgt in targets) / float(len(targets))
            score = seen - 0.02 * lift - 0.004 * math.hypot(x, y)
            if score > best_score:
                best, best_score = eye, score
        if best_score > 0.82:
            break
    return best


def density_at(scene, dom_obj, point, radius_cells=1):
    """Smoke density of a (non-adaptive) gas domain around a world position,
    for the frame the scene is currently on."""
    dg = bpy.context.evaluated_depsgraph_get() if bpy.context.scene == scene \
        else scene.view_layers[0].depsgraph
    ev = dom_obj.evaluated_get(dg)
    d = None
    for mod in ev.modifiers:
        if mod.type == "FLUID" and mod.fluid_type == "DOMAIN":
            d = mod.domain_settings
    if d is None:
        return 0.0
    res = tuple(d.domain_resolution)
    n = res[0] * res[1] * res[2]
    grid = np.empty(len(d.density_grid), dtype=np.float32)
    if len(grid) != n or n == 0:
        return 0.0
    d.density_grid.foreach_get(grid)
    grid = grid.reshape(res[2], res[1], res[0])
    corners = [dom_obj.matrix_world @ Vector(c) for c in dom_obj.bound_box]
    lo = np.array([min(c[i] for c in corners) for i in range(3)])
    hi = np.array([max(c[i] for c in corners) for i in range(3)])
    idx = ((np.array(point) - lo) / (hi - lo) * np.array(res)).astype(int)
    if np.any(idx < 0) or np.any(idx >= np.array(res)):
        return 0.0
    r = radius_cells
    sl = tuple(slice(max(0, idx[a] - r), idx[a] + r + 1) for a in (2, 1, 0))
    return float(grid[sl].mean())


# ----------------------------------------------------------------------------
# scenes and objects
# ----------------------------------------------------------------------------

def remove_scene(name):
    scene = bpy.data.scenes.get(name)
    if scene is None:
        return
    objs = list(scene.collection.all_objects)
    datas = {o.data for o in objs if o.data is not None}
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for d in datas:
        try:
            if d.users == 0:
                getattr(bpy.data, _data_collection(d)).remove(d)
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    for coll in list(scene.collection.children_recursive):
        bpy.data.collections.remove(coll)
    world = scene.world
    if len(bpy.data.scenes) > 1:
        bpy.data.scenes.remove(scene)
    if world is not None and world.users == 0:
        bpy.data.worlds.remove(world)


def _data_collection(d):
    return {"Mesh": "meshes", "Camera": "cameras", "Light": "lights", "Curve": "curves"}.get(
        type(d).__name__, "meshes")


def fresh_scene(kind, settings):
    name = SCENE_NAMES[kind]
    remove_scene(name)
    scene = bpy.data.scenes.new(name)
    scene["ht_shot"] = kind
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.use_gravity = True
    scene.gravity = (0.0, 0.0, -9.81)
    return scene


def collection(scene, name):
    coll = bpy.data.collections.new("HT_%s_%s" % (scene.get("ht_shot", "X").title(), name))
    scene.collection.children.link(coll)
    return coll


def link(coll, obj, material=None):
    coll.objects.link(obj)
    if material is not None and hasattr(obj.data, "materials"):
        obj.data.materials.clear()
        obj.data.materials.append(material)
    return obj


def sim_only(obj):
    """Keep an object in every depsgraph (so sims see it) but out of the picture."""
    obj.display_type = "WIRE"
    obj.hide_render = False
    for flag in ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission",
                 "visible_volume_scatter", "visible_shadow"):
        if hasattr(obj, flag):
            setattr(obj, flag, False)
    return obj


def look_at(obj, target, roll=0.0):
    direction = Vector(target) - obj.location
    quat = direction.to_track_quat("-Z", "Y")
    obj.rotation_euler = quat.to_euler()
    if roll:
        obj.rotation_euler.rotate_axis("Z", roll)


def add_camera(scene, coll, name, location, target, lens=20.0, clip_start=0.03, clip_end=20000.0):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.sensor_width = 36.0
    cam.clip_start = clip_start
    cam.clip_end = clip_end
    obj = bpy.data.objects.new(name, cam)
    obj.location = location
    coll.objects.link(obj)
    look_at(obj, target)
    scene.camera = obj
    return obj


def key(owner, path, frame, value=None, index=-1):
    if value is not None:
        if index >= 0:
            getattr(owner, path)[index] = value
        else:
            setattr(owner, path, value)
    owner.keyframe_insert(path, frame=frame, index=index)


def set_frame_range(scene, start, length, sim_start, sim_end):
    scene.frame_start = int(start)
    scene.frame_end = int(start + length - 1)
    scene.frame_current = int(start)
    scene["ht_sim_start"] = int(sim_start)
    scene["ht_sim_end"] = int(sim_end)


# ----------------------------------------------------------------------------
# render settings
# ----------------------------------------------------------------------------

def configure_render(scene, settings, kind, volume_bounces=4, exposure=1.0):
    preset = settings.preset()
    r = scene.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = settings.res_x, settings.res_y
    r.resolution_percentage = preset["percent"]
    r.fps = settings.fps
    r.fps_base = 1.0
    r.use_motion_blur = settings.use_motion_blur
    set_if(r, motion_blur_shutter=0.5, film_transparent=False, use_persistent_data=False)
    r.filepath = os.path.join(render_dir(settings, kind), render_prefix(kind))
    set_image_output(scene)

    c = scene.cycles
    c.samples = preset["samples"]
    set_if(c, use_adaptive_sampling=True, adaptive_threshold=0.02 if settings.quality != "FINAL" else 0.01,
           use_denoising=True, max_bounces=12, diffuse_bounces=3, glossy_bounces=4,
           transmission_bounces=12, volume_bounces=volume_bounces, transparent_max_bounces=8,
           caustics_reflective=False, caustics_refractive=False, film_exposure=exposure,
           sample_clamp_indirect=10.0, volume_step_rate=1.0, volume_max_steps=512,
           motion_blur_position="CENTER")
    set_enum(c, "denoiser", "OPENIMAGEDENOISE")
    if settings.use_gpu:
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            if prefs.compute_device_type != "NONE":
                c.device = "GPU"
        except (KeyError, AttributeError):
            pass
    lighting.apply_look(scene, kind)


# ----------------------------------------------------------------------------
# fluids
# ----------------------------------------------------------------------------

def fluid(obj, kind):
    mod = obj.modifiers.new("Fluid", "FLUID")
    mod.fluid_type = kind
    return {"DOMAIN": mod.domain_settings, "FLOW": mod.flow_settings,
            "EFFECTOR": mod.effector_settings}[kind]


def make_effector(obj, surface_distance=0.0):
    eff = fluid(obj, "EFFECTOR")
    eff.effector_type = "COLLISION"
    eff.surface_distance = surface_distance
    eff.use_plane_init = False
    return eff


def base_domain(obj, kind, resolution, cache_path, frame_start, frame_end):
    d = fluid(obj, "DOMAIN")
    d.domain_type = kind
    d.resolution_max = int(resolution)
    d.cache_directory = cache_path
    d.cache_frame_start = int(frame_start)
    d.cache_frame_end = int(frame_end)
    set_enum(d, "cache_type", "ALL")
    set_enum(d, "cache_data_format", "OPENVDB")
    set_if(d, cache_resumable=True, use_adaptive_timesteps=True, time_scale=1.0)
    for side in ("front", "back", "left", "right", "top", "bottom"):
        setattr(d, "use_collision_border_" + side, False)
    return d


def resolution(settings, kind):
    explicit = getattr(settings, kind.lower() + "_res")
    return explicit if explicit > 0 else settings.preset()[kind.lower()]


def shot_frames(settings, kind):
    return timeline.shot_length(kind, settings.fps)
