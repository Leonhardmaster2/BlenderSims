"""The cut, in seconds. Edit here if the script changes."""

# (key, start s, end s)
SLOTS = (
    ("TITLE", 0.0, 4.0),    # black, the Greek line fades in and out
    ("WATER", 4.0, 8.0),    # surge hits the lens, hard cut to black
    ("ROCK", 8.0, 12.0),    # rockfall, dust swallows the frame, cut to black
    ("SNOW", 12.0, 20.0),   # still slope for two seconds, slab releases, to white
    ("END", 20.0, 25.0),    # hold the white, then logo, version and date
)

BLACK_TAIL = 0.33       # seconds of black after the hard cut, inside the slot
SNOW_STILL = 2.0        # seconds the slope holds still before the slab releases
WHITE_ASSIST = 0.5      # seconds of safety dissolve to white at the end of SNOW
SHOTS = ("WATER", "ROCK", "SNOW")


def slot(key):
    for k, a, b in SLOTS:
        if k == key:
            return a, b
    raise KeyError(key)


def frames(seconds, fps):
    return int(round(seconds * fps))


def slot_frames(key, fps):
    """(first edit frame, length in frames) of a slot; the edit starts at frame 1."""
    a, b = slot(key)
    return 1 + frames(a, fps), frames(b, fps) - frames(a, fps)


def shot_length(key, fps):
    """Frames of rendered picture a simulated shot needs."""
    _, n = slot_frames(key, fps)
    if key in ("WATER", "ROCK"):
        n -= frames(BLACK_TAIL, fps)
    return n


def total_frames(fps):
    return frames(SLOTS[-1][2], fps)
