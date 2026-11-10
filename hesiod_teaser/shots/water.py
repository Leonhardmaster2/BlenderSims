"""Shot 2 - WATER: a surge comes down a gully and hits the lens.

Mantaflow FLIP liquid in a small domain that only covers the gully in front of
the camera. The terrain patch is a closed collision solid, the surge is a fast
inflow at the top of the gully, and whitewater (spray / foam / bubbles) is
simulated as secondary particles.
"""

import math

import bpy
import numpy as np

from .. import lighting, materials, meshgen
from ..compat import set_enum, set_if
from ..heightfield import gaussian_blur, smoothstep, spectral_noise, worley
from ..stage import Stage
from . import common

KIND = "WATER"
WIDTH, Y_MIN, Y_MAX, CELL = 18.0, -7.0, 34.0, 0.07
LIP_Y = 21.0             # a rock sill; the surge wells up in the basin behind it
BASIN = (22.2, 27.0)     # hidden from the lens by the sill
SOURCE_Y = 24.6          # centre of the inflow, metres up the gully from the lens
CAM_HEIGHT = 0.42        # lens height above the gully bed
# frames from the start of the inflow until the front reaches the lens,
# measured on test bakes at 24 fps for the default speed over SOURCE_Y metres
TRAVEL_SECONDS = 2.3


def centreline(y):
    """Gentle S-bend, passing through x=0 at the camera."""
    return 1.5 * np.sin(2.0 * math.pi * y / 36.0)


def carve_gully(stage, settings, rng):
    gx, gy = stage.fine_xy()
    z = stage.fine()
    ys = gy[:, 0]
    xc = centreline(ys)
    half = settings.water_gully_width * 0.5
    depth = settings.water_gully_depth

    # terrain height along the centreline, made to fall monotonically downhill
    loc = stage.local()
    zc = loc.sample(xc, ys)
    bed = np.minimum.accumulate(zc[::-1])[::-1] - depth
    bed = gaussian_blur(bed[:, None], 1.2 / stage.cell)[:, 0]

    # a sill with a basin behind it: the inflow sits in the basin, out of
    # sight of the low camera, and the surge pours over the lip
    lip_z = float(np.interp(LIP_Y, ys, bed)) + 0.35
    basin = smoothstep(BASIN[0] - 0.7, BASIN[0], ys) * (1.0 - smoothstep(BASIN[1], BASIN[1] + 0.7, ys))
    sill = np.exp(-((ys - LIP_Y - 0.3) / 0.7) ** 2)
    bed = bed + 0.35 * sill
    bed = bed + basin * ((lip_z - 1.2) - bed)

    dx = gx - xc[:, None]
    cut_depth = max(depth, 0.6)
    cut = bed[:, None] + cut_depth * (np.abs(dx) / half) ** 2
    if depth > 1e-3:
        z = np.minimum(z, cut)
    else:   # no gully wanted: still sink the basin so the inflow stays hidden
        z = np.where(basin[:, None] > 0.01, np.minimum(z, cut), z)
    z = gaussian_blur(z, 0.10 / stage.cell)

    # bedrock roughness, then stones: cobbles in the bed, blocks on the banks
    shape = z.shape
    in_bed = 1.0 - smoothstep(0.35 * half, 0.95 * half, np.abs(dx))
    rough = spectral_noise(shape, stage.cell, 0.5, 7.0, 0.7, rng) * 0.14
    z = z + rough * (1.0 - 0.5 * in_bed)
    for feature, amount, where in ((0.55, 0.22, in_bed), (0.24, 0.10, in_bed),
                                   (1.5, 0.42, 1.0 - in_bed), (0.6, 0.16, 1.0 - 0.5 * in_bed)):
        dist, ident = worley(shape, stage.cell, feature, rng)
        present = ident > 0.35                       # leave gaps between stones
        dome = np.clip(1.0 - (dist / (0.34 + 0.22 * ident)) ** 2, 0.0, None) ** 0.75
        z = z + dome * present * amount * (0.5 + ident) * where
    stage.apply(z)
    stage.invalidate()

    wet_noise = spectral_noise(shape, stage.cell, 0.3, 3.0, 0.6, rng) * 0.12
    wet = 1.0 - smoothstep(0.30 * half, 0.80 * half, np.abs(dx) + wet_noise * half)
    stage.set_attr("ht_wet", wet * stage.weight)
    return lip_z


def build(context, settings, hf):
    rng = np.random.default_rng(settings.seed + 11)
    fps = settings.fps
    preset = settings.preset()
    site = common.resolve_site(settings, hf, KIND)
    stage = Stage(hf, site, WIDTH, Y_MIN, Y_MAX, CELL)
    slope = common.condition_slope(stage, 13.0, 27.0, 0.0, SOURCE_Y, half_width=4.0)
    lip_z = carve_gully(stage, settings, rng)

    scene = common.fresh_scene(KIND, settings)
    scene["ht_site"] = repr(site)
    env = common.collection(scene, "Set")
    sim = common.collection(scene, "Sim")

    # -- terrain ------------------------------------------------------------
    mat_rock = materials.rock("HT_Rock_Wet", hf.texture if settings.use_hesiod_texture else None, wet=True)
    common.link(env, stage.build_terrain("HT_Water_Terrain"), mat_rock)
    collider = common.link(sim, stage.build_collider("HT_Water_Collider", stride=2))
    common.make_effector(collider)
    common.sim_only(collider)

    loc = stage.local_cache()
    ys = np.linspace(Y_MIN + 1.0, Y_MAX - 1.0, 200)
    bed_line = loc.sample(centreline(ys), ys)

    def bed(y):
        return float(np.interp(y, ys, bed_line))

    # -- camera -------------------------------------------------------------
    px, py = np.meshgrid(np.linspace(-0.5, 0.5, 9), np.linspace(-0.6, 0.9, 12))
    cam_pos = (0.0, 0.0, float(loc.sample(px, py).max()) + CAM_HEIGHT - 0.12)
    aim_y = 12.0
    target = (float(centreline(aim_y)) * 0.5, aim_y, bed(aim_y) + 0.35)
    cam = common.add_camera(scene, env, "HT_Water_Camera", cam_pos, target, lens=17.0, clip_start=0.02)

    # the camera body is an obstacle, so the water piles up against the lens
    housing = bpy.data.objects.new("HT_Water_CameraHousing", meshgen.box_mesh(
        "HT_Water_CameraHousing", (-0.22, -0.75, -0.22), (0.22, -0.16, 0.22)))
    housing.parent = cam
    housing.rotation_euler = (math.radians(-90.0), 0.0, 0.0)   # local -Z (view) -> box +Y
    common.link(sim, housing)
    common.make_effector(housing)
    common.sim_only(housing)

    # -- liquid domain ------------------------------------------------------
    length = common.shot_frames(settings, KIND)
    sim_start = length            # dry gully until then
    travel = int(round(TRAVEL_SECONDS * fps * (9.0 / settings.water_surge_speed) ** 0.6))
    hit = sim_start + travel
    sim_end = hit + int(1.6 * fps)   # slack, so the real hit frame is always inside the bake

    half = max(settings.water_gully_width * 0.5 + 2.0, 4.0)
    y_lo, y_hi = -3.5, BASIN[1] + 0.8
    gx, gy = stage.fine_xy()
    region = (np.abs(gx - centreline(gy)) < half) & (gy > y_lo) & (gy < y_hi)
    z_lo = float(stage.fine()[region].min()) - 0.4
    z_hi = lip_z + settings.water_surge_height + 2.2
    dom_obj = bpy.data.objects.new("HT_Water_Domain", meshgen.box_mesh(
        "HT_Water_Domain", (-half - 1.0, y_lo, z_lo), (half + 1.0, y_hi, z_hi)))
    common.link(sim, dom_obj, materials.water("HT_Water", settings.water_turbidity))
    d = common.base_domain(dom_obj, "LIQUID", common.resolution(settings, KIND),
                           common.cache_dir(settings, KIND, fresh=True), sim_start, sim_end)
    set_enum(d, "simulation_method", "FLIP")
    set_if(d, flip_ratio=0.97, cfl_condition=3.0, timesteps_min=1, timesteps_max=6,
           particle_number=2, particle_radius=1.0, particle_randomness=0.2,
           particle_band_width=3.0, particle_min=8, particle_max=16,
           use_fractions=True, fractions_threshold=0.05, fractions_distance=0.5,
           use_mesh=True, mesh_scale=2, mesh_particle_radius=2.0,
           mesh_smoothen_pos=1, mesh_smoothen_neg=1, mesh_concave_upper=3.5, mesh_concave_lower=0.4,
           use_speed_vectors=True, use_collision_border_bottom=True)
    set_enum(d, "mesh_generator", "IMPROVED")
    if settings.water_whitewater:
        set_if(d, use_spray_particles=True, use_foam_particles=True, use_bubble_particles=True,
               particle_scale=1,
               sndparticle_potential_min_wavecrest=2.0, sndparticle_potential_max_wavecrest=8.0,
               sndparticle_potential_min_trappedair=5.0, sndparticle_potential_max_trappedair=20.0,
               sndparticle_potential_min_energy=4.0, sndparticle_potential_max_energy=40.0,
               sndparticle_sampling_wavecrest=int(180 * preset["detail"]),
               sndparticle_sampling_trappedair=int(36 * preset["detail"]),
               sndparticle_bubble_buoyancy=0.5, sndparticle_bubble_drag=0.6,
               sndparticle_life_min=6.0, sndparticle_life_max=18.0,
               sndparticle_potential_radius=2, sndparticle_update_radius=2)
        set_enum(d, "sndparticle_boundary", "DELETE")
        set_enum(d, "sndparticle_combined_export", "SPRAY_FOAM_BUBBLES")
        _setup_whitewater(dom_obj, sim, d)
    dom_obj.show_instancer_for_render = True
    dom_obj.show_instancer_for_viewport = True
    # an empty liquid domain renders as a solid block: keep it hidden until water exists
    common.key(dom_obj, "hide_render", sim_start, True)
    common.key(dom_obj, "hide_render", sim_start + 1, False)

    # -- the surge ------------------------------------------------------------
    # A hump of water that wells up out of the basin and is driven over the sill.
    sy = SOURCE_Y
    sx = float(centreline(sy))
    over = settings.water_surge_height            # how far it stands above the lip
    floor = lip_z - 1.4
    rz = 0.5 * (lip_z + over - floor)
    src_me = meshgen.ellipsoid_mesh("HT_Water_Surge", half + 0.8, 0.5 * (BASIN[1] - BASIN[0]) + 0.2, rz, 3)
    src = bpy.data.objects.new("HT_Water_Surge", src_me)
    top_z = floor + rz
    common.link(sim, src)
    common.sim_only(src)
    rise = max(4, int(0.4 * fps))
    src.location = (sx, sy, top_z - over - 0.15)
    src.keyframe_insert("location", frame=sim_start)
    src.location = (sx, sy, top_z)
    src.keyframe_insert("location", frame=sim_start + rise)
    f = common.fluid(src, "FLOW")
    f.flow_type = "LIQUID"
    f.flow_behavior = "INFLOW"
    f.use_initial_velocity = True
    v = settings.water_surge_speed
    f.velocity_coord = (0.0, -v, 0.12 * v)
    set_if(f, velocity_factor=0.0, velocity_normal=0.0, surface_distance=0.0, subframes=1)

    # -- light ----------------------------------------------------------------
    sun_el, sun_az = lighting.pick_sun(stage, azimuth_pref=-70.0, elevation_pref=32.0, subject_y=10.0)
    lighting.setup_world(scene, "HT_Water_World", sun_el, sun_az, strength=0.09, haze=1.6)
    scene["ht_sun"] = "elevation %.0f, azimuth %.0f" % (sun_el, sun_az)
    common.configure_render(scene, settings, KIND, volume_bounces=2)
    common.set_frame_range(scene, hit - length + 1, length, sim_start, sim_end)
    scene["ht_hit_frame"] = hit
    scene["ht_domain"] = dom_obj.name
    scene["ht_slope"] = slope
    return scene


def _setup_whitewater(dom_obj, coll, d):
    drop = bpy.data.objects.new("HT_Water_Droplet", meshgen.ellipsoid_mesh("HT_Water_Droplet", 1.0, 1.0, 1.0, 2))
    meshgen.shade_smooth(drop.data)
    common.link(coll, drop, materials.whitewater("HT_Whitewater"))
    drop.hide_viewport = True
    drop.location = (0.0, 0.0, -500.0)   # the template itself stays out of sight
    for psys in dom_obj.particle_systems:
        ps = psys.settings
        ps.render_type = "OBJECT"
        ps.instance_object = drop
        ps.particle_size = 0.02
        ps.size_random = 0.6
        ps.display_method = "DOT"
        ps.display_size = 0.02


def find_hit_frame(scene, reach=0.6):
    """After baking: the first frame the liquid surface comes within ``reach``
    metres of the lens. Returns None if it never does."""
    dom = bpy.data.objects.get(scene.get("ht_domain", ""))
    cam = scene.camera
    if dom is None or cam is None:
        return None
    start, end = int(scene["ht_sim_start"]), int(scene["ht_sim_end"])
    keep = scene.frame_current
    hit = None
    try:
        for frame in range(start + 1, end + 1):
            scene.frame_set(frame)
            dg = bpy.context.evaluated_depsgraph_get() if bpy.context.scene == scene \
                else scene.view_layers[0].depsgraph
            ev = dom.evaluated_get(dg)
            me = ev.data
            n = len(me.vertices)
            if n <= 8:
                continue
            co = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            p = np.array(cam.matrix_world.translation, dtype=np.float32)
            if float(np.min(np.linalg.norm(co - p, axis=1))) < reach:
                hit = min(frame + 1, end)     # one more frame: the lens is fully under
                break
    finally:
        scene.frame_set(keep)
    return hit


def sync(context, scene):
    """After baking: move the frame range so the cut lands on the real impact."""
    hit = find_hit_frame(scene)
    if hit is None:
        return None
    length = scene.frame_end - scene.frame_start + 1
    scene["ht_hit_frame"] = int(hit)
    scene.frame_start = max(1, int(hit) - length + 1)
    scene.frame_end = scene.frame_start + length - 1
    scene.frame_current = scene.frame_start
    return "cut re-timed to frame %d" % hit
