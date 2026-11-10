"""Shot 3 - ROCK: a rockfall comes down a steep face and its dust swallows the frame.

A handful of rigid-body boulders (Bullet) tumble down the terrain collider.
Gravel is a particle system bouncing on the same collider. Both feed a small
Mantaflow smoke domain, and that dust is what actually covers the lens.
"""

import bpy
import numpy as np
from mathutils import Euler, Vector

from .. import lighting, materials, meshgen
from ..compat import set_enum, set_if
from ..heightfield import spectral_noise, worley
from ..stage import Stage
from . import common

KIND = "ROCK"
WIDTH, Y_MIN, Y_MAX, CELL = 48.0, -12.0, 64.0, 0.16
RELEASE_Y = (30.0, 44.0)      # where the boulders start, metres up the slope
CAM_HEIGHT = 1.25


def roughen(stage, rng):
    """Turn the smooth heightfield patch into a broken rock face."""
    z = stage.fine()
    shape = z.shape
    z = z + spectral_noise(shape, stage.cell, 1.0, 14.0, 0.7, rng) * 0.45
    z = z + spectral_noise(shape, stage.cell, 0.35, 2.5, 0.6, rng) * 0.10
    for feature, amount in ((3.2, 0.75), (1.3, 0.32), (0.55, 0.12)):
        dist, ident = worley(shape, stage.cell, feature, rng)
        block = np.clip(1.0 - (dist / (0.36 + 0.2 * ident)) ** 2, 0.0, None) ** 0.6
        z = z + block * (ident > 0.4) * amount * (0.4 + ident)
    stage.apply(z)
    stage.invalidate()


def build(context, settings, hf):
    rng = np.random.default_rng(settings.seed + 23)
    fps = settings.fps
    preset = settings.preset()
    site = common.resolve_site(settings, hf, KIND)
    stage = Stage(hf, site, WIDTH, Y_MIN, Y_MAX, CELL)
    slope = common.condition_slope(stage, 36.0, 48.0, -4.0, RELEASE_Y[1] + 4.0, concavity=0.3)
    roughen(stage, rng)

    scene = common.fresh_scene(KIND, settings)
    scene["ht_site"] = repr(site)
    env = common.collection(scene, "Set")
    sim = common.collection(scene, "Sim")
    rocks = common.collection(scene, "Boulders")
    loc = stage.local_cache()

    def ground(x, y):
        return float(loc.sample(x, y))

    # -- terrain ------------------------------------------------------------
    texture = hf.texture if settings.use_hesiod_texture else None
    mat_rock = materials.rock("HT_Rock", texture)
    common.link(env, stage.build_terrain("HT_Rock_Terrain"), mat_rock)
    collider = common.link(sim, stage.build_collider("HT_Rock_Collider", stride=2))
    common.sim_only(collider)
    collider.modifiers.new("Collision", "COLLISION")
    # The smoke gets its own copy of the collider. Mantaflow only voxelises an
    # obstacle once if it is static, and a rigid body never counts as static -
    # sharing one object would re-voxelise the terrain on every frame.
    smoke_collider = bpy.data.objects.new("HT_Rock_DustCollider", collider.data)
    common.link(sim, smoke_collider)
    common.sim_only(smoke_collider)
    common.make_effector(smoke_collider)
    set_if(collider.collision, damping_factor=0.5, damping_random=0.3,
           friction_factor=0.3, friction_random=0.2, thickness_outer=0.05)

    # -- camera -------------------------------------------------------------
    targets = [(x, y, ground(x, y) + 1.0) for y in (8.0, 14.0, 20.0, 26.0, 32.0, 38.0, 44.0)
               for x in (-6.0, 0.0, 6.0)]
    spots = [(x, y) for y in (0.0, -2.0, 2.0, -5.0) for x in (0.0, -2.5, 2.5, -5.0, 5.0)]
    cam_pos = common.best_viewpoint(loc, spots, targets, CAM_HEIGHT)
    aim_y = 22.0
    common.add_camera(scene, env, "HT_Rock_Camera", cam_pos,
                            (0.0, aim_y, ground(0.0, aim_y) + 1.5), lens=19.0, clip_start=0.05)

    # -- timing -------------------------------------------------------------
    length = common.shot_frames(settings, KIND)
    sim_start = length
    sim_end = sim_start + int(6.0 * fps)

    # downhill direction along the face (unit vector in the YZ plane)
    rise = ground(0.0, RELEASE_Y[1]) - ground(0.0, 4.0)
    run = RELEASE_Y[1] - 4.0
    down = Vector((0.0, -run, -rise)).normalized()

    # -- rigid bodies -------------------------------------------------------
    with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        if scene.rigidbody_world is None:
            bpy.ops.rigidbody.world_add()
    rbw = scene.rigidbody_world
    rbw.collection = rocks
    set_if(rbw, substeps_per_frame=12, solver_iterations=24, time_scale=1.0)
    rbw.point_cache.frame_start = sim_start
    rbw.point_cache.frame_end = sim_end
    rocks.objects.link(collider)
    _rigid(context, scene, collider, "PASSIVE", shape="MESH", friction=0.85, restitution=0.22)

    mat_boulder = materials.rock("HT_Boulder", None, tint=(0.92, 0.88, 0.84))
    boulders = []
    for i in range(settings.rock_count):
        r = settings.rock_size * float(np.clip(rng.lognormal(0.0, 0.38), 0.5, 2.1))
        me = meshgen.boulder_mesh("HT_Boulder_%02d" % i, r, rng)
        obj = bpy.data.objects.new("HT_Boulder_%02d" % i, me)
        common.link(rocks, obj, mat_boulder)
        x = float(rng.uniform(-8.0, 8.0))
        y = float(rng.uniform(*RELEASE_Y))
        start = Vector((x, y, ground(x, y) + r * 1.05 + 0.2))
        obj.location = start
        obj.rotation_euler = Euler(rng.uniform(0, 6.28, 3).tolist())
        _rigid(context, scene, obj, "ACTIVE", shape="CONVEX_HULL", friction=0.7, restitution=0.28,
               mass=2600.0 * 4.19 * r ** 3 * 0.55)
        # a short animated shove, then physics takes over with that velocity
        f0 = sim_start + int(rng.integers(0, int(0.7 * fps)))
        v0 = float(rng.uniform(1.5, 4.0))
        rb = obj.rigid_body
        rb.kinematic = True
        rb.keyframe_insert("kinematic", frame=f0)
        obj.keyframe_insert("location", frame=f0)
        obj.keyframe_insert("rotation_euler", frame=f0)
        obj.location = start + down * (v0 * 3.0 / fps) + Vector((0, 0, 0.15))
        obj.rotation_euler.x -= 0.25
        obj.keyframe_insert("location", frame=f0 + 3)
        obj.keyframe_insert("rotation_euler", frame=f0 + 3)
        rb.kinematic = False
        rb.keyframe_insert("kinematic", frame=f0 + 3)
        boulders.append(obj)

    # -- gravel: particles bouncing down the face ---------------------------------
    gravel_src = _gravel(scene, sim, rocks, stage, loc, rng, settings, preset, sim_start, down, mat_boulder)

    # -- dust: smoke domain ---------------------------------------------------
    gx, gy = stage.fine_xy()
    region = (np.abs(gx) < 18.0) & (gy > -9.0) & (gy < RELEASE_Y[1] + 6.0)
    zf = stage.fine()[region]
    lo = (-18.0, -9.0, float(zf.min()) - 1.0)
    hi = (18.0, RELEASE_Y[1] + 6.0, float(zf.max()) + 10.0)
    dom_obj = bpy.data.objects.new("HT_Rock_Dust", meshgen.box_mesh("HT_Rock_Dust", lo, hi))
    dust = settings.rock_dust
    common.link(sim, dom_obj, materials.smoke_volume(
        "HT_Dust", (0.40, 0.34, 0.27), 1.1 * dust, 0.25, noise_scale=0.9))
    dom_obj.display_type = "WIRE"
    d = common.base_domain(dom_obj, "GAS", common.resolution(settings, KIND),
                           common.cache_dir(settings, KIND, fresh=True), sim_start, sim_end)
    # heavy dust: it sinks and runs downhill as a density current, billowing as it goes
    # (no adaptive domain: it would force the terrain to be re-voxelised every frame)
    set_if(d, alpha=-0.35, beta=0.6, vorticity=0.35, use_dissolve_smoke=False,
           use_adaptive_domain=False, cfl_condition=4.0, timesteps_min=1, timesteps_max=4)
    if preset["upres"]:
        set_if(d, use_noise=True, noise_scale=preset["upres"], noise_strength=1.4,
               noise_pos_scale=2.0, noise_time_anim=0.12)

    for obj in boulders:
        f = common.fluid(obj, "FLOW")
        f.flow_type = "SMOKE"
        f.flow_behavior = "INFLOW"
        set_enum(f, "flow_source", "MESH")
        set_if(f, density=0.6, temperature=0.25, surface_distance=0.7, volume_density=0.0,
               use_initial_velocity=True, velocity_factor=0.5, velocity_normal=0.4,
               subframes=1, smoke_color=(0.7, 0.7, 0.7))
    f = common.fluid(gravel_src, "FLOW")
    f.flow_type = "SMOKE"
    f.flow_behavior = "INFLOW"
    set_enum(f, "flow_source", "PARTICLES")
    f.particle_system = gravel_src.particle_systems[0]
    set_if(f, density=0.45, temperature=0.2, use_particle_size=True, particle_size=1.3,
           use_initial_velocity=True, velocity_factor=0.8, subframes=1)

    # a gentle katabatic push so the cloud keeps rolling onto the lens
    wind = bpy.data.objects.new("HT_Rock_Wind", None)
    wind.empty_display_type = "SINGLE_ARROW"
    wind.empty_display_size = 3.0
    wind.location = (0.0, RELEASE_Y[1], ground(0.0, RELEASE_Y[1]) + 6.0)
    wind.rotation_euler = Vector((0.0, 0.0, 1.0)).rotation_difference(down).to_euler()
    sim.objects.link(wind)
    with context.temp_override(scene=scene, view_layer=scene.view_layers[0], object=wind,
                               active_object=wind, selected_objects=[wind]):
        bpy.ops.object.forcefield_toggle()
    if wind.field is not None:
        wind.field.type = "WIND"
        set_if(wind.field, strength=1.8, flow=0.0, noise=0.6, seed=settings.seed)
    # the wind is for the dust only
    for psys in gravel_src.particle_systems:
        psys.settings.effector_weights.wind = 0.0
    set_if(rbw.effector_weights, wind=0.0)

    # -- light ----------------------------------------------------------------
    sun_el, sun_az = lighting.pick_sun(stage, azimuth_pref=70.0, elevation_pref=30.0, subject_y=22.0)
    lighting.setup_world(scene, "HT_Rock_World", sun_el, sun_az, strength=0.09, haze=2.2)
    scene["ht_sun"] = "elevation %.0f, azimuth %.0f" % (sun_el, sun_az)
    common.configure_render(scene, settings, KIND, volume_bounces=3)

    scene["ht_domain"] = dom_obj.name
    scene["ht_slope"] = slope
    scene["ht_cut_delay"] = settings.rock_cut_delay
    guess = sim_start + int(3.2 * fps)
    common.set_frame_range(scene, guess - length + 1, length, sim_start, sim_end)
    scene["ht_hit_frame"] = guess

    # rigid bodies and gravel are quick: simulate them now so the cut is already timed
    pre_bake(context, scene)
    sync(context, scene)
    return scene


def _rigid(context, scene, obj, kind, shape, friction, restitution, mass=1.0):
    with context.temp_override(scene=scene, view_layer=scene.view_layers[0], object=obj,
                               active_object=obj, selected_objects=[obj]):
        if obj.rigid_body is None:
            bpy.ops.rigidbody.object_add(type=kind)
    rb = obj.rigid_body
    rb.type = kind
    set_enum(rb, "collision_shape", shape)
    set_enum(rb, "mesh_source", "BASE")
    rb.friction = friction
    rb.restitution = restitution
    if kind == "ACTIVE":
        rb.mass = mass
        set_if(rb, use_margin=True, collision_margin=0.02, linear_damping=0.03,
               angular_damping=0.08, use_deactivation=False)
    else:
        set_if(rb, use_margin=True, collision_margin=0.01)
    return rb


def _gravel(scene, sim, rocks, stage, loc, rng, settings, preset, sim_start, down, material):
    # template stones (kept far below the set; only their instances are seen)
    stones = bpy.data.collections.new("HT_Rock_GravelStones")
    scene.collection.children.link(stones)
    for i in range(4):
        me = meshgen.boulder_mesh("HT_Gravel_%d" % i, 1.0, rng, subdiv=2)
        ob = bpy.data.objects.new("HT_Gravel_%d" % i, me)
        ob.location = (i * 3.0, 0.0, -400.0)
        common.link(stones, ob, material)

    # emitter: a strip of the face inside the release zone, lifted a little
    xs = np.linspace(-9.0, 9.0, 13)
    ys = np.linspace(RELEASE_Y[0] + 2.0, RELEASE_Y[1], 9)
    gx, gy = np.meshgrid(xs, ys)
    verts = np.stack([gx, gy, loc.sample(gx, gy) + 0.6], axis=-1).reshape(-1, 3)
    me = meshgen.mesh_from_arrays("HT_Rock_GravelSource", verts, meshgen.grid_quads(len(xs), len(ys)))
    src = bpy.data.objects.new("HT_Rock_GravelSource", me)
    sim.objects.link(src)
    src.display_type = "WIRE"
    src.show_instancer_for_render = False
    src.show_instancer_for_viewport = True

    mod = src.modifiers.new("Gravel", "PARTICLE_SYSTEM")
    ps = mod.particle_system.settings
    ps.name = "HT_Gravel"
    fps = settings.fps
    ps.count = int(1400 * preset["detail"])
    ps.frame_start = sim_start
    ps.frame_end = sim_start + int(1.1 * fps)
    ps.lifetime = 2000
    ps.emit_from = "FACE"
    ps.physics_type = "NEWTON"
    ps.normal_factor = 0.8
    ps.object_align_factor = tuple(down * 3.5)
    ps.factor_random = 2.2
    ps.mass = 1.0
    ps.particle_size = 0.11
    ps.size_random = 0.85
    ps.use_rotations = True
    ps.rotation_factor_random = 1.0
    ps.phase_factor_random = 2.0
    set_enum(ps, "angular_velocity_mode", "VELOCITY")
    ps.angular_velocity_factor = 3.0
    ps.use_dynamic_rotation = True
    ps.render_type = "COLLECTION"
    ps.instance_collection = stones
    set_if(ps, use_collection_pick_random=True, drag_factor=0.02, damping=0.01, display_size=0.1)
    mod.particle_system.seed = settings.seed
    mod.particle_system.point_cache.frame_start = sim_start
    mod.particle_system.point_cache.frame_end = sim_start + int(6.0 * fps)
    return src


def pre_bake(context, scene):
    """(Re)simulate rigid bodies and gravel so the smoke bake has motion to follow."""
    with context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        bpy.ops.ptcache.free_bake_all()
        bpy.ops.ptcache.bake_all(bake=True)


def find_hit_frame(scene):
    """The frame to cut on: when the dust closes over the lens if the smoke is
    baked, otherwise shortly after the first boulder reaches the camera."""
    dusty = _dust_frame(scene)
    if dusty is not None:
        return dusty
    return _boulder_frame(scene)


def _dust_frame(scene, threshold=0.10):
    dom = bpy.data.objects.get(scene.get("ht_domain", ""))
    cam = scene.camera
    if dom is None or cam is None:
        return None
    baked = any(m.type == "FLUID" and m.fluid_type == "DOMAIN" and m.domain_settings.has_cache_baked_data
                for m in dom.modifiers)
    if not baked:
        return None
    start, end = int(scene["ht_sim_start"]), int(scene["ht_sim_end"])
    keep = scene.frame_current
    try:
        for frame in range(start + 12, end + 1):
            scene.frame_set(frame)
            # mean density along the first metres of the view ray
            origin = cam.matrix_world.translation
            ahead = cam.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
            seen = [common.density_at(scene, dom, tuple(origin + ahead * dist)) for dist in (0.5, 2.5, 5.0, 8.0)]
            if sum(seen) / len(seen) > threshold:
                return min(frame + 3, end)
    finally:
        scene.frame_set(keep)
    return None


def _boulder_frame(scene):
    """First frame a boulder reaches the camera, plus the cut delay."""
    cam = scene.camera
    boulders = [o for o in scene.objects if o.name.startswith("HT_Boulder_")]
    if cam is None or not boulders:
        return None
    start, end = int(scene["ht_sim_start"]), int(scene["ht_sim_end"])
    keep = scene.frame_current
    hit = None
    try:
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            c = cam.matrix_world.translation
            for ob in boulders:
                p = ob.matrix_world.translation
                near = (p - c).length < 3.5
                passed = p.y < c.y + 1.0 and abs(p.x - c.x) < 9.0
                if near or passed:
                    hit = frame
                    break
            if hit is not None:
                break
    finally:
        scene.frame_set(keep)
    if hit is None:
        return None
    return min(hit + int(scene.get("ht_cut_delay", 5)), end)


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
