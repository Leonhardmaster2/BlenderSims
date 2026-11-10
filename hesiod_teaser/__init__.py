"""Hesiod Teaser - one-click setup of the Water / Rock / Snow teaser shots."""

bl_info = {
    "name": "Hesiod Teaser",
    "author": "Hesiod",
    "version": (0, 7, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > Hesiod Teaser",
    "description": "Builds, bakes, renders and cuts the Water / Rock / Snow teaser on Hesiod terrain",
    "category": "Render",
}

from . import props  # noqa: E402
from . import pipeline  # noqa: E402
from .pipeline import bake_shot, build_all, build_shot, render_shot, run_all  # noqa: E402,F401


def register():
    from . import ops, ui
    props.register()
    ops.register()
    ui.register()


def unregister():
    from . import ops, ui
    ui.unregister()
    ops.unregister()
    props.unregister()
