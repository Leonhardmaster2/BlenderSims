"""Shot 4 - SNOW: a still slope, the slab releases, the powder cloud rolls over the lens.

* The snowpack is real geometry on top of the terrain, with layered
  stratigraphy that shows in the crown wall and on the broken blocks.
* The slab is cut into blocks that slide off, exposing the bed surface.
* The powder cloud is a Mantaflow gas sim fed by a moving "dense core": a set
  of emitters that follow the true fall lines of the terrain, with their speed
  integrated from a Voellmy friction model - so the cloud arrives at the lens
  on a known frame and the camera can be placed for it.
"""

import math

import bpy
import numpy as np
from mathutils import Euler, Quaternion, Vector

from .. import lighting, materials, meshgen, timeline
from ..compat import set_enum, set_if
from ..heightfield import gaussian_blur, smoothstep, spectral_noise, trace_descent, voellmy
from ..stage import Stage
from . import common

KIND = "SNOW"
WIDTH, Y_MIN, Y_MAX, CELL = 230.0, -55.0, 205.0, 0.65
SLAB_Y = 102.0           # centre of the slab, metres up the slope from the stage origin
BLOCK = 4.6              # typical slab block size
ARRIVAL_MARGIN = 0.5     # seconds before the end at which the cloud front reaches the lens
CLOUD_LEAD = 1.5         # the powder front runs this far ahead of the dense core (from test bakes)
CAM_HEIGHT = 1.7


def lay_snow(stage, settings, rng):
    """Put a snowpack on the working area. Returns the bare-rock mask (fine area)."""
    ground = gaussian_blur(stage.fine(), 1.2 / stage.cell)
    gy, gx = np.gradient(ground, stage.cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    shape = ground.shape
    cover = 1.0 - smoothstep(47.0, 60.0, slope + spectral_noise(shape, stage.cell, 4.0, 30.0, 0.6, rng) * 4.0)
    drift = spectral_noise(shape, stage.cell, 14.0, 90.0, 0.8, rng)
    depth = settings.snow_depth * cover * np.clip(1.0 + 0.22 * drift, 0.4, 1.6)
    surface = gaussian_blur(ground + depth, 0.9 / stage.cell)
    surface += spectral_noise(shape, stage.cell, 1.8, 9.0, 0.7, rng) * 0.045 * cover   # wind ripples
    stage.apply(surface)
    stage.invalidate()
    return 1.0 - cover


def _slab_blocks(settings, rng):
    """Jittered lattice of quads covering the slab outline (stage XY)."""
    half_w, half_l = settings.slab_width * 0.5, settings.slab_length * 0.5
    ni = max(3, int(round(settings.slab_width / BLOCK)))
    nj = max(3, int(round(settings.slab_length / BLOCK)))
    bx, by = settings.slab_width / ni, settings.slab_length / nj
    ii, jj = np.meshgrid(np.arange(ni + 1), np.arange(nj + 1))
    px = -half_w + ii * bx + rng.uniform(-0.28, 0.28, ii.shape) * bx
    py = SLAB_Y - half_l + jj * by + rng.uniform(-0.28, 0.28, ii.shape) * by
    quads = []
    wob = rng.uniform(0.0, 6.28)
    for j in range(nj):
        for i in range(ni):
            cx = float(px[j:j + 2, i:i + 2].mean())
            cy = float(py[j:j + 2, i:i + 2].mean())
            u = cx / half_w
            v = (cy - SLAB_Y) / half_l
            top = 1.0 - 0.38 * u * u + 0.07 * math.sin(u * 7.0 + wob)          # arched crown
            bottom = -1.0 + 0.30 * u * u + 0.08 * math.sin(u * 5.0 + wob * 2)  # ragged stauchwall
            if abs(u) < 0.97 and bottom < v < top:
                quads.append(np.array([[px[j, i], py[j, i]], [px[j, i + 1], py[j, i + 1]],
                                       [px[j + 1, i + 1], py[j + 1, i + 1]], [px[j + 1, i], py[j + 1, i]]]))
    return quads


def _raster_quads(stage, quads):
    """Mask of fine-grid vertices that lie inside any of the (convex) quads."""
    fx = stage.xs[stage.i0:stage.i1]
    fy = stage.ys[stage.j0:stage.j1]
    mask = np.zeros(stage.fine_shape, dtype=bool)
    for q in quads:
        i_lo, i_hi = np.searchsorted(fx, q[:, 0].min()), np.searchsorted(fx, q[:, 0].max())
        j_lo, j_hi = np.searchsorted(fy, q[:, 1].min()), np.searchsorted(fy, q[:, 1].max())
        if i_hi <= i_lo or j_hi <= j_lo:
            continue
        gx, gy = np.meshgrid(fx[i_lo:i_hi], fy[j_lo:j_hi])
        inside = np.ones(gx.shape, dtype=bool)
        for k in range(4):
            a, b = q[k], q[(k + 1) % 4]
            inside &= ((b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])) >= 0.0
        mask[j_lo:j_hi, i_lo:i_hi] |= inside
    return mask


def build(context, settings, hf):
    rng = np.random.default_rng(settings.seed + 37)
    fps = settings.fps
    preset = settings.preset()
    dt = 1.0 / fps
    site = common.resolve_site(settings, hf, KIND)
    stage = Stage(hf, site, WIDTH, Y_MIN, Y_MAX, CELL)
    slope = common.condition_slope(stage, 32.0, 39.0, 0.0, SLAB_Y + 40.0, concavity=0.12)
    rock_mask = lay_snow(stage, settings, rng)

    thick = settings.slab_thickness
    quads = _slab_blocks(settings, rng)
    pit = _raster_quads(stage, quads)

    scene = common.fresh_scene(KIND, settings)
    scene["ht_site"] = repr(site)
    env = common.collection(scene, "Set")
    sim = common.collection(scene, "Sim")
    slab = common.collection(scene, "Slab")

    length = common.shot_frames(settings, KIND)
    release = 1 + timeline.frames(timeline.SNOW_STILL, fps)
    n_steps = length - release + 1 + int(1.0 * fps)

    surf = stage.local()                       # snow surface
    bed_z = surf.h - thick * pit               # after the slab has gone
    bed = type(surf)(bed_z, surf.cell, surf.x0, surf.y0)
    smooth = surf.smoothed(5.0)                # fall lines follow the broad shape

    # -- terrain with snowpack -------------------------------------------------
    far_rock = smoothstep(45.0, 58.0, stage.full_slope_deg())
    stage.set_attr_full("ht_rock", far_rock)
    stage.attrs["ht_rock"][stage.j0:stage.j1, stage.i0:stage.i1] = (
        far_rock[stage.j0:stage.j1, stage.i0:stage.i1] * (1.0 - stage.weight) + rock_mask * stage.weight)
    stage.set_attr_full("ht_ground", np.ones(stage.z.shape))
    stage.set_attr_full("ht_surf_z", stage.z)
    texture = hf.texture if settings.use_hesiod_texture else None
    mat_snow = materials.snow("HT_Snow", thick, texture)
    terrain = common.link(env, stage.build_terrain("HT_Snow_Terrain"), mat_snow)
    set_if(terrain.cycles, use_deform_motion=False)

    # the pit the slab leaves behind is a shape key that switches on at release
    terrain.shape_key_add(name="Intact")
    key = terrain.shape_key_add(name="Released")
    co = np.empty(len(terrain.data.vertices) * 3, dtype=np.float32)
    terrain.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    drop = np.zeros(stage.z.shape, dtype=np.float32)
    drop[stage.j0:stage.j1, stage.i0:stage.i1] = thick * pit
    co[:, 2] -= drop.ravel()
    key.data.foreach_set("co", co.ravel())
    key.value = 0.0
    key.keyframe_insert("value", frame=release - 1)
    key.value = 1.0
    key.keyframe_insert("value", frame=release)

    collider = common.link(sim, stage.build_collider("HT_Snow_Collider", stride=3))
    common.sim_only(collider)
    common.make_effector(collider)

    # -- the dense core: emitters riding the fall lines ---------------------------
    half_w, half_l = settings.slab_width * 0.5, settings.slab_length * 0.5
    trigger = np.array([rng.uniform(-0.2, 0.2) * half_w, SLAB_Y + 0.55 * half_l])
    cols = max(4, int(round(settings.slab_width / 11.0)))
    rows = max(3, int(round(settings.slab_length / 11.0)))
    core_me = meshgen.ellipsoid_mesh("HT_Snow_Core", 5.5, 5.5, 2.4, 2)
    cores, reach = [], []
    lo = np.array([1e9, 1e9, 1e9])
    hi = -lo
    for r in range(rows):
        for c in range(cols):
            x0 = -half_w * 0.86 + (c + 0.5 + rng.uniform(-0.25, 0.25)) * (settings.slab_width * 0.86 / cols)
            y0 = SLAB_Y - half_l * 0.9 + (r + 0.5 + rng.uniform(-0.25, 0.25)) * (settings.slab_length * 0.9 / rows)
            pts, arc = trace_descent(smooth, x0, y0, 2.5, 320.0)
            if len(pts) < 4:
                continue
            pz = surf.sample(pts[:, 0], pts[:, 1])
            delay = float(np.hypot(x0 - trigger[0], y0 - trigger[1])) / 70.0 + rng.uniform(0.0, 0.12)
            s = voellmy(arc, pz, dt, n_steps, mu=rng.uniform(0.13, 0.19), xi=rng.uniform(2200.0, 3000.0),
                        v_min=9.0, delay=delay)
            obj = bpy.data.objects.new("HT_Snow_Core_%02d" % len(cores), core_me)
            common.link(sim, obj)
            common.sim_only(obj)
            for k in range(0, n_steps, 2):
                x = float(np.interp(s[k], arc, pts[:, 0]))
                y = float(np.interp(s[k], arc, pts[:, 1]))
                z = float(np.interp(s[k], arc, pz)) + 1.0
                obj.location = (x, y, z)
                obj.keyframe_insert("location", frame=release + k)
                lo = np.minimum(lo, (x, y, z))
                hi = np.maximum(hi, (x, y, z))
            f = common.fluid(obj, "FLOW")
            f.flow_type = "SMOKE"
            f.flow_behavior = "INFLOW"
            set_enum(f, "flow_source", "MESH")
            set_if(f, density=1.0, temperature=0.6, surface_distance=1.5, volume_density=0.7,
                   use_initial_velocity=True, velocity_factor=0.85, velocity_normal=0.8, subframes=1,
                   smoke_color=(1.0, 1.0, 1.0))
            # no powder until the mass is actually moving
            start_frame = release + int(delay * fps)
            f.use_inflow = False
            f.keyframe_insert("use_inflow", frame=start_frame)
            f.use_inflow = True
            f.keyframe_insert("use_inflow", frame=start_frame + 2)
            cores.append(obj)
            if r == 0:
                reach.append((abs(x0), pts, arc, pz, s))

    # -- camera: where the cloud front will be at the arrival time -----------------
    arrive = length - release - int(ARRIVAL_MARGIN * fps)
    reach.sort(key=lambda item: item[0])
    _, pts, arc, pz, s = reach[0]
    s_core = float(s[min(arrive, len(s) - 1)])
    low = int(np.searchsorted(pts[::-1, 1], Y_MIN + 24.0))      # keep clear of the stage rim
    s_max = float(arc[max(len(arc) - 1 - low, 1)])
    s_cam = min(s_core * CLOUD_LEAD, s_max)

    def camera_at(dist):
        x = float(np.interp(dist, arc, pts[:, 0]))
        y = float(np.interp(dist, arc, pts[:, 1]))
        pos = (x, y, float(surf.sample(x, y)) + CAM_HEIGHT)
        aim = (0.0, SLAB_Y - 0.15 * half_l, float(surf.sample(0.0, SLAB_Y)) + 2.0)
        d = (Vector(aim) - Vector(pos)).length
        return pos, aim, d, min(max(36.0 * d * 0.58 / settings.slab_width, 18.0), 40.0)

    cam_pos, look, dist, lens = camera_at(s_cam)
    cam = common.add_camera(scene, env, "HT_Snow_Camera", cam_pos, look, lens=lens, clip_start=0.1)

    # the fall line the camera sits on, kept so the shot can be re-timed after baking
    path_me = meshgen.mesh_from_arrays("HT_Snow_CameraPath", np.column_stack([pts, pz]))
    path_obj = bpy.data.objects.new("HT_Snow_CameraPath", path_me)
    sim.objects.link(path_obj)
    path_obj.hide_render = True
    path_obj.hide_viewport = True
    scene["ht_path_limit"] = s_max
    scene["ht_arrive_frame"] = release + arrive
    scene["ht_slab_width"] = settings.slab_width
    scene["ht_look"] = look

    # -- slab blocks -------------------------------------------------------------
    _build_blocks(slab, quads, surf, bed, smooth, mat_snow, thick, trigger, release, n_steps, dt, fps, rng)

    # -- powder cloud domain ---------------------------------------------------
    # room below the camera too, so it can slide down the fall line when re-timed
    far = min(s_cam * 1.35 + 14.0, s_max)
    for dist_ in (s_cam, far):
        p = camera_at(dist_)[0]
        lo = np.minimum(lo, (p[0] - 8.0, p[1] - 10.0, p[2] - 2.0))
        hi = np.maximum(hi, (p[0] + 8.0, p[1], p[2]))
    hi = np.maximum(hi, (0.0, SLAB_Y + half_l, 0.0))
    d_lo = (float(lo[0]) - 24.0, float(lo[1]) - 6.0, float(lo[2]) - 6.0)
    d_hi = (float(hi[0]) + 24.0, float(hi[1]) + 10.0, float(hi[2]) + 34.0)
    dom_obj = bpy.data.objects.new("HT_Snow_Powder", meshgen.box_mesh("HT_Snow_Powder", d_lo, d_hi))
    cloud = settings.snow_cloud
    common.link(sim, dom_obj, materials.smoke_volume(
        "HT_Powder", (0.96, 0.975, 1.0), 0.30 * cloud, 0.55, noise_scale=0.35, ambient=0.85))
    dom_obj.display_type = "WIRE"
    sim_start, sim_end = release - 1, length + 2
    d = common.base_domain(dom_obj, "GAS", common.resolution(settings, KIND),
                           common.cache_dir(settings, KIND, fresh=True), sim_start, sim_end)
    # a suspension current: denser than air so it hugs the slope and runs out,
    # while turbulence lifts it into a tall billowing cloud
    # (no adaptive domain: it would force the terrain to be re-voxelised every frame)
    set_if(d, alpha=-0.12, beta=0.9, vorticity=0.45, use_dissolve_smoke=False,
           use_adaptive_domain=False, cfl_condition=4.0, timesteps_min=1, timesteps_max=6)
    if preset["upres"]:
        set_if(d, use_noise=True, noise_scale=preset["upres"], noise_strength=1.6,
               noise_pos_scale=2.0, noise_time_anim=0.15)

    # -- light ----------------------------------------------------------------
    sun_el, sun_az = lighting.pick_sun(stage, azimuth_pref=80.0, elevation_pref=24.0,
                                       subject_y=SLAB_Y, min_incidence=0.16)
    lighting.setup_world(scene, "HT_Snow_World", sun_el, sun_az, strength=0.05, haze=0.7)
    scene["ht_sun"] = "elevation %.0f, azimuth %.0f" % (sun_el, sun_az)
    common.configure_render(scene, settings, KIND, volume_bounces=3)

    common.set_frame_range(scene, 1, length, sim_start, sim_end)
    scene["ht_domain"] = dom_obj.name
    scene["ht_slope"] = slope
    scene["ht_release_frame"] = release
    scene["ht_blocks"] = len(quads)
    scene["ht_camera_distance"] = round(dist, 1)
    return scene


def _build_blocks(coll, quads, surf, bed, smooth, material, thick, trigger, release, n_steps, dt, fps, rng):
    for n, q in enumerate(quads):
        centre = q.mean(axis=0)
        top_z = surf.sample(q[:, 0], q[:, 1])
        origin = np.array([centre[0], centre[1], float(surf.sample(centre[0], centre[1]))])
        me, depth = meshgen.prism_mesh("HT_Slab_%03d" % n, q - centre, top_z - origin[2],
                                       top_z - origin[2] - thick)
        meshgen.set_point_attribute(me, "ht_depth", depth)
        obj = bpy.data.objects.new("HT_Slab_%03d" % n, me)
        obj.location = origin.tolist()
        common.link(coll, obj, material)

        # hidden until the slab lets go (before that the ground mesh is intact)
        for attr in ("hide_render", "hide_viewport"):
            common.key(obj, attr, release - 1, True)
            common.key(obj, attr, release, False)

        pts, arc = trace_descent(smooth, centre[0], centre[1], 2.5, 300.0)
        if len(pts) < 4:
            continue
        pz = bed.sample(pts[:, 0], pts[:, 1])
        delay = float(np.hypot(*(centre - trigger))) / 70.0 + rng.uniform(0.0, 0.18)
        s = voellmy(arc, pz, dt, n_steps, mu=rng.uniform(0.2, 0.32), xi=rng.uniform(1100.0, 1700.0),
                    delay=delay)
        e1, e2 = q[1] - q[0], q[3] - q[0]
        size = float(np.sqrt(abs(e1[0] * e2[1] - e1[1] * e2[0])))
        tumble = rng.uniform(0.15, 0.5) if rng.random() < 0.6 else 0.0
        axis = Vector((1.0, rng.uniform(-0.4, 0.4), rng.uniform(-0.3, 0.3))).normalized()
        yaw = rng.uniform(-0.6, 0.6)
        for k in range(0, n_steps, 2):
            dist = float(s[k])
            x = float(np.interp(dist, arc, pts[:, 0]))
            y = float(np.interp(dist, arc, pts[:, 1]))
            shrink = 1.0 - 0.55 * float(smoothstep(8.0, 95.0, dist))
            z = float(bed.sample(x, y)) + thick * shrink + (0.0 if dist < 0.3 else 0.12)
            if dist < 0.3:   # until it has really moved, stay exactly in place
                x, y, z = origin
            obj.location = (x, y, z)
            angle = -tumble * max(dist - 4.0, 0.0) / max(size, 1.0)
            rot = (Euler((0.0, 0.0, yaw * float(smoothstep(2.0, 40.0, dist)))).to_quaternion()
                   @ Quaternion(axis, angle))
            obj.rotation_euler = rot.to_euler()
            obj.scale = (shrink, shrink, shrink)
            frame = release + k
            obj.keyframe_insert("location", frame=frame)
            obj.keyframe_insert("rotation_euler", frame=frame)
            obj.keyframe_insert("scale", frame=frame)


def sync(context, scene):
    """After baking: slide the camera along its fall line to where the powder
    front actually is at the arrival frame, so the white-out lands on time."""
    dom = bpy.data.objects.get(scene.get("ht_domain", ""))
    path = bpy.data.objects.get("HT_Snow_CameraPath")
    cam = scene.camera
    if dom is None or path is None or cam is None:
        return None
    n = len(path.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    path.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(co[:, 0]), np.diff(co[:, 1])))])
    limit = float(scene.get("ht_path_limit", arc[-1]))
    keep = scene.frame_current
    try:
        scene.frame_set(int(scene["ht_arrive_frame"]))
        front = None
        for i in range(n):
            if arc[i] > limit:
                break
            if common.density_at(scene, dom, (co[i, 0], co[i, 1], co[i, 2] + 2.5), radius_cells=1) > 0.06:
                front = arc[i]
    finally:
        scene.frame_set(keep)
    if front is None:
        return None
    dist = min(front, limit)
    x, y, z = (float(np.interp(dist, arc, co[:, k])) for k in range(3))
    cam.location = (x, y, z + CAM_HEIGHT)
    look = Vector(scene["ht_look"])
    common.look_at(cam, look)
    d = (look - cam.location).length
    cam.data.lens = min(max(36.0 * d * 0.58 / float(scene["ht_slab_width"]), 18.0), 40.0)
    scene["ht_camera_distance"] = round(d, 1)
    return "camera moved to the cloud front, %.0f m below the slab" % d
