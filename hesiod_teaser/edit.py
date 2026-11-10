"""The cut: titles, the three shots, hard cuts, the white-out and the end card,
assembled in the Video Sequencer of the master scene."""

import os

import bpy

from . import props, timeline
from .compat import new_effect, set_enum, set_if, set_video_output, strips
from .shots import common

CH_BG, CH_SHOT, CH_WASH, CH_TEXT, CH_SOUND = 1, 2, 3, 4, 8


def rendered_frames(settings, kind):
    """Paths of the rendered frames of a shot, if the whole range is on disk."""
    scene = bpy.data.scenes.get(common.SCENE_NAMES[kind])
    if scene is None:
        return []
    folder = common.render_dir(settings, kind)
    prefix = common.render_prefix(kind)
    paths = [os.path.join(folder, "%s%04d.png" % (prefix, f))
             for f in range(scene.frame_start, scene.frame_end + 1)]
    return paths if all(os.path.isfile(p) for p in paths) else []


_COUNT_CACHE = {}


def count_rendered(settings, kind):
    """(frames on disk, frames needed). Cached briefly: the panel asks on every redraw."""
    import time
    hit = _COUNT_CACHE.get(kind)
    if hit is not None and time.time() - hit[0] < 2.0:
        return hit[1]
    result = _count_rendered(settings, kind)
    _COUNT_CACHE[kind] = (time.time(), result)
    return result


def _count_rendered(settings, kind):
    scene = bpy.data.scenes.get(common.SCENE_NAMES[kind])
    if scene is None:
        return 0, 0
    folder = common.render_dir(settings, kind)
    prefix = common.render_prefix(kind)
    total = scene.frame_end - scene.frame_start + 1
    done = sum(os.path.isfile(os.path.join(folder, "%s%04d.png" % (prefix, f)))
               for f in range(scene.frame_start, scene.frame_end + 1))
    return done, total


def _colour(se, name, channel, start, length, rgb):
    s = new_effect(se, name, "COLOR", channel, start, length)
    s.color = rgb
    s.blend_type = "ALPHA_OVER"
    return s


def _fade(strip, keys):
    """keys: [(frame, alpha), ...]"""
    for frame, alpha in keys:
        strip.blend_alpha = alpha
        strip.keyframe_insert("blend_alpha", frame=int(frame))


def _text(se, name, channel, start, length, text, size, rgb, y, font=None):
    s = new_effect(se, name, "TEXT", channel, start, length)
    s.text = text
    s.font_size = float(size)
    s.color = (*rgb, 1.0)
    s.location = (0.5, y)
    for prop, value in (("alignment_x", "CENTER"), ("anchor_x", "CENTER"), ("anchor_y", "CENTER"),
                        ("align_x", "CENTER"), ("align_y", "CENTER")):
        set_enum(s, prop, value)
    set_if(s, use_shadow=False, use_outline=False, use_box=False, wrap_width=0.0)
    if font is not None:
        s.font = font
    s.blend_type = "ALPHA_OVER"
    return s


def _sound(se, name, path, channel, start, length):
    if not path:
        return None
    path = bpy.path.abspath(path)
    if not os.path.isfile(path):
        return None
    s = strips(se).new_sound(name=name, filepath=path, channel=channel, frame_start=int(start))
    if s.frame_final_duration > length:
        s.frame_final_duration = int(length)
    return s


def assemble(context):
    """(Re)build the sequencer edit. Returns a list of human-readable notes."""
    settings = props.get_settings(context)
    master = props.master_scene(context)
    fps = settings.fps
    notes = []

    r = master.render
    r.fps, r.fps_base = fps, 1.0
    r.resolution_x, r.resolution_y = settings.res_x, settings.res_y
    r.resolution_percentage = settings.preset()["percent"]
    master.frame_start = 1
    master.frame_end = timeline.total_frames(fps)
    set_if(r, use_sequencer=True, use_compositing=False)

    se = master.sequence_editor_create()
    for s in list(strips(se)):
        if s.name.startswith("HT_"):
            strips(se).remove(s)

    font = None
    if settings.font_path and os.path.isfile(bpy.path.abspath(settings.font_path)):
        font = bpy.data.fonts.load(bpy.path.abspath(settings.font_path), check_existing=True)
    h = settings.res_y

    total = timeline.total_frames(fps)
    _colour(se, "HT_Black", CH_BG, 1, total, (0.0, 0.0, 0.0))

    # 0-4 s: the Greek line fades in and out on black
    start, length = timeline.slot_frames("TITLE", fps)
    greek = _text(se, "HT_Greek", CH_TEXT, start, length, settings.greek_line.replace("\\n", "\n"),
                  h * 0.040, (0.92, 0.90, 0.86), 0.5, font)
    _fade(greek, [(start + 0.10 * length, 0.0), (start + 0.38 * length, 1.0),
                  (start + 0.72 * length, 1.0), (start + 0.94 * length, 0.0)])

    # the three shots
    all_images = True
    for kind in timeline.SHOTS:
        start, slot_len = timeline.slot_frames(kind, fps)
        need = timeline.shot_length(kind, fps)
        scene = bpy.data.scenes.get(common.SCENE_NAMES[kind])
        if scene is None or not getattr(settings, kind.lower() + "_enabled"):
            notes.append("%s: not built - black in the edit" % kind.title())
            continue
        images = rendered_frames(settings, kind)
        if images:
            s = strips(se).new_image(name="HT_" + kind.title(), filepath=images[0],
                                     channel=CH_SHOT, frame_start=start)
            for p in images[1:need]:
                s.elements.append(os.path.basename(p))
            set_enum(s, "alpha_mode", "STRAIGHT")
        else:
            all_images = False
            s = strips(se).new_scene(name="HT_" + kind.title(), scene=scene,
                                     channel=CH_SHOT, frame_start=start)
            notes.append("%s: frames not rendered yet - using a live scene strip (preview only; "
                         "simulations only show in rendered frames)" % kind.title())
        if s.frame_final_duration > need:
            s.frame_final_duration = need
        s.blend_type = "ALPHA_OVER"

    # 12-20 s ends in white: a short safety dissolve guarantees a clean full white
    start, length = timeline.slot_frames("SNOW", fps)
    wash_len = timeline.frames(timeline.WHITE_ASSIST, fps)
    end_start, end_len = timeline.slot_frames("END", fps)
    wash = _colour(se, "HT_WhiteOut", CH_WASH, start + length - wash_len, wash_len + end_len, (1.0, 1.0, 1.0))
    _fade(wash, [(start + length - wash_len, 0.0), (start + length - 1, 1.0)])

    # 20-25 s: hold the white, then logo, version and date
    ink = (0.07, 0.08, 0.10)
    t0 = end_start + timeline.frames(1.0, fps)
    logo_path = bpy.path.abspath(settings.logo_path) if settings.logo_path else ""
    if logo_path and os.path.isfile(logo_path):
        logo = strips(se).new_image(name="HT_Logo", filepath=logo_path, channel=CH_TEXT,
                                    frame_start=end_start)
        logo.frame_final_duration = end_len
        logo.blend_type = "ALPHA_OVER"
        try:
            img = bpy.data.images.load(logo_path, check_existing=True)
            scale = (0.26 * settings.res_y) / max(img.size[1], 1)
            logo.transform.scale_x = logo.transform.scale_y = scale
            logo.transform.offset_y = 0.08 * settings.res_y * settings.preset()["percent"] / 100.0
        except (RuntimeError, AttributeError):
            pass
    else:
        logo = _text(se, "HT_Logo", CH_TEXT, end_start, end_len, " ".join(settings.title_text),
                     h * 0.115, ink, 0.56, font)
    _fade(logo, [(t0, 0.0), (t0 + timeline.frames(0.9, fps), 1.0)])
    t1 = t0 + timeline.frames(0.7, fps)
    version = _text(se, "HT_Version", CH_TEXT + 1, end_start, end_len, settings.version_text,
                    h * 0.050, ink, 0.435, font)
    _fade(version, [(t1, 0.0), (t1 + timeline.frames(0.8, fps), 1.0)])
    t2 = t1 + timeline.frames(0.5, fps)
    date = _text(se, "HT_Date", CH_TEXT + 2, end_start, end_len, settings.date_text,
                 h * 0.026, (0.25, 0.27, 0.30), 0.375, font)
    _fade(date, [(t2, 0.0), (t2 + timeline.frames(0.8, fps), 1.0)])

    # sound (all optional)
    t_start, t_len = timeline.slot_frames("TITLE", fps)
    _sound(se, "HT_Snd_Wind", settings.sound_wind, CH_SOUND, t_start, t_len)
    for kind, path in (("WATER", settings.sound_roar), ("ROCK", settings.sound_rock)):
        s0, _ = timeline.slot_frames(kind, fps)
        _sound(se, "HT_Snd_" + kind.title(), path, CH_SOUND, s0, timeline.shot_length(kind, fps))
    s0, s_len = timeline.slot_frames("SNOW", fps)
    release = s0 + timeline.frames(timeline.SNOW_STILL, fps)
    _sound(se, "HT_Snd_Crack", settings.sound_crack, CH_SOUND + 1, release, s_len)
    _sound(se, "HT_Snd_Rumble", settings.sound_rumble, CH_SOUND, release, total - release + 1)
    _sound(se, "HT_Snd_WindOut", settings.sound_wind, CH_SOUND + 2, end_start, end_len)

    # rendered frames already carry their look: pass them through untouched
    vs = master.view_settings
    if all_images:
        set_enum(vs, "view_transform", "Standard")
        set_enum(vs, "look", "None")
        vs.exposure, vs.gamma = 0.0, 1.0
    else:
        set_enum(vs, "view_transform", "AgX", "Filmic")
    r.filepath = os.path.join(common.project_dir(settings), "hesiod_teaser_")
    set_video_output(master)
    return notes
