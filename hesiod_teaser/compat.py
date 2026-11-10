"""Small shims so the same code runs on Blender 4.2 LTS through 5.x."""

import bpy

PREFIX = "HT_"


def strips(se):
    return se.strips if hasattr(se, "strips") else se.sequences


def new_effect(se, name, kind, channel, start, length):
    coll = strips(se)
    try:
        return coll.new_effect(name=name, type=kind, channel=channel, frame_start=start, length=length)
    except TypeError:
        return coll.new_effect(name=name, type=kind, channel=channel,
                               frame_start=start, frame_end=start + length)


def set_enum(owner, prop, *candidates):
    """Set the first enum value the running Blender accepts; returns it or None."""
    for value in candidates:
        try:
            setattr(owner, prop, value)
            return value
        except (TypeError, AttributeError, ValueError):
            continue
    return None


def set_if(owner, **values):
    """Set attributes that exist; silently skip the ones this version lacks."""
    for key, value in values.items():
        if hasattr(owner, key):
            try:
                setattr(owner, key, value)
            except (TypeError, AttributeError, ValueError):
                pass


def socket(node, *names):
    """First input socket found among ``names`` (socket names moved in 4.0)."""
    for name in names:
        sock = node.inputs.get(name)
        if sock is not None:
            return sock
    return None


def set_input(node, names, value):
    if isinstance(names, str):
        names = (names,)
    sock = socket(node, *names)
    if sock is not None:
        try:
            sock.default_value = value
        except (TypeError, ValueError):
            pass
    return sock


def new_material(name):
    old = bpy.data.materials.get(name)
    if old is not None:
        bpy.data.materials.remove(old)
    mat = bpy.data.materials.new(name)
    if not mat.node_tree:
        mat.use_nodes = True
    elif hasattr(mat, "use_nodes") and bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    mat.node_tree.nodes.clear()
    return mat


def new_world(name):
    old = bpy.data.worlds.get(name)
    if old is not None:
        bpy.data.worlds.remove(old)
    world = bpy.data.worlds.new(name)
    if not world.node_tree:
        world.use_nodes = True
    elif bpy.app.version < (5, 0, 0):
        world.use_nodes = True
    world.node_tree.nodes.clear()
    return world


def set_video_output(scene):
    """Point a scene's output at H.264 MP4 (the media_type switch is 5.0+)."""
    img = scene.render.image_settings
    set_enum(img, "media_type", "VIDEO")
    set_enum(img, "file_format", "FFMPEG")
    ff = scene.render.ffmpeg
    set_enum(ff, "format", "MPEG4")
    set_enum(ff, "codec", "H264")
    set_enum(ff, "constant_rate_factor", "HIGH")
    set_enum(ff, "ffmpeg_preset", "GOOD")
    set_enum(ff, "audio_codec", "AAC")
    set_if(ff, audio_bitrate=256)


def set_image_output(scene, depth="16"):
    img = scene.render.image_settings
    set_enum(img, "media_type", "IMAGE")
    set_enum(img, "file_format", "PNG")
    set_enum(img, "color_mode", "RGB")
    set_enum(img, "color_depth", depth)
    set_if(img, compression=15)
