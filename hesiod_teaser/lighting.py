"""Sky, sun and colour look for each shot (Cycles)."""

import math

from .compat import new_world, set_enum, set_if

LOOKS = {
    # view-transform look, exposure (stops), gamma, white-balance temperature
    "WATER": dict(look=("AgX - Medium High Contrast", "Medium High Contrast"), exposure=-0.2, gamma=1.0, temp=6100),
    "ROCK": dict(look=("AgX - Punchy", "AgX - Medium High Contrast", "Medium High Contrast"), exposure=-0.15, gamma=1.0, temp=6900),
    "SNOW": dict(look=("AgX - Base Contrast", "AgX - Medium High Contrast", "None"), exposure=-0.5, gamma=1.0, temp=6300),
}


def setup_world(scene, name, sun_elevation_deg, sun_azimuth_deg, strength=1.0,
                air=1.0, haze=1.0, sun_size_deg=0.545, sun_intensity=1.0):
    """Physical sky with its own sun disc.

    ``sun_azimuth_deg`` is measured in the scene: 0 = sun shining from +Y
    (ahead of the camera, i.e. back-light), 90 = from +X (camera right),
    180 = from behind the camera.
    """
    world = new_world(name)
    nt = world.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    set_enum(sky, "sky_type", "MULTIPLE_SCATTERING", "NISHITA")
    sky.sun_elevation = math.radians(sun_elevation_deg)
    # the sky node measures rotation clockwise from +Y, seen from above
    sky.sun_rotation = math.radians(sun_azimuth_deg)
    set_if(sky, sun_disc=True, sun_size=math.radians(sun_size_deg), sun_intensity=sun_intensity,
           air_density=air, aerosol_density=haze, dust_density=haze, ozone_density=1.0, altitude=2200.0)
    bg = nt.nodes.new("ShaderNodeBackground")
    # keep the exposure steady as the sun climbs (calibrated at 30 degrees)
    climb = 0.5 / max(math.sin(math.radians(sun_elevation_deg)), 0.2)
    bg.inputs["Strength"].default_value = strength * min(max(climb, 0.45), 1.5)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs[0], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    sky.location, bg.location, out.location = (-300, 0), (0, 0), (220, 0)
    scene.world = world
    return world


def _horizon_deg(hf, x, y, z, dx, dy, reach=5000.0):
    """Elevation angle of the terrain skyline seen from a point along a heading."""
    import numpy as np

    step = max(hf.cell, 2.0)
    d = np.arange(step * 1.5, reach, step)
    xs, ys = x + dx * d, y + dy * d
    ang = np.degrees(np.arctan2(hf.sample(xs, ys) - z, d))
    ang[~hf.contains(xs, ys)] = -90.0
    return float(ang.max()) if len(ang) else -90.0


def pick_sun(stage, azimuth_pref, elevation_pref, subject_y, min_incidence=0.22):
    """Closest sun position to the preferred one that actually lights the shot.

    Checks the real terrain skyline (so a neighbouring ridge cannot leave the
    set in shadow) and that the light does not merely graze the slope.
    Angles are in the stage frame: azimuth 0 = from straight ahead (+Y).
    """
    import numpy as np

    src = stage.src
    loc = stage.local_cache()
    points = []
    for y in (0.0, subject_y):
        sx, sy = stage.to_source(0.0, y)
        points.append((float(sx), float(sy), float(loc.sample(0.0, y)) + stage.z0 + 1.5))
    # slope normal around the subject (stage frame)
    span = max(4.0, abs(subject_y) * 0.25)
    dzdy = (float(loc.sample(0.0, subject_y + span)) - float(loc.sample(0.0, subject_y - span))) / (2 * span)
    dzdx = (float(loc.sample(span, subject_y)) - float(loc.sample(-span, subject_y))) / (2 * span)
    n = np.array([-dzdx, -dzdy, 1.0])
    n /= np.linalg.norm(n)

    best, best_cost = (elevation_pref, azimuth_pref), None
    for d_az in (0, 15, -15, 30, -30, 45, -45, 60, -60, 80, -80, 100, -100, 125, -125, 150, -150, 180):
        az = azimuth_pref + d_az
        a = math.radians(az)
        dir_stage = (math.sin(a), math.cos(a))
        dsx = dir_stage[0] * stage.cos - dir_stage[1] * stage.sin
        dsy = dir_stage[0] * stage.sin + dir_stage[1] * stage.cos
        skyline = max(_horizon_deg(src, px, py, pz, dsx, dsy) for px, py, pz in points)
        for d_el in (0, 6, 12, 18, 26, 34, 44):
            el = elevation_pref + d_el
            if el > 72.0 or el < skyline + 5.0:
                continue
            e = math.radians(el)
            sun = np.array([dir_stage[0] * math.cos(e), dir_stage[1] * math.cos(e), math.sin(e)])
            if float(sun @ n) < min_incidence:
                continue
            cost = abs(d_az) / 20.0 + d_el / 8.0
            if best_cost is None or cost < best_cost:
                best, best_cost = (el, az), cost
            break
    return best


def apply_look(scene, kind):
    look = LOOKS[kind]
    vs = scene.view_settings
    if set_enum(vs, "view_transform", "AgX", "Filmic") is None:
        return
    set_enum(vs, "look", *look["look"])
    vs.exposure = look["exposure"]
    vs.gamma = look["gamma"]
    if hasattr(vs, "use_white_balance"):
        vs.use_white_balance = True
        vs.white_balance_temperature = look["temp"]
        vs.white_balance_tint = 10.0
