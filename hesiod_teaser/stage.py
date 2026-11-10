"""A *stage* is the small, high-resolution piece of terrain a shot plays on.

It is resampled from the source heightfield into its own frame: the origin is
the chosen site, +Y points uphill, +Z is up and one unit is one metre. That
keeps every simulation domain axis-aligned and at real-world scale no matter
how the Hesiod tile is sized or oriented. The grid is graded: fine cells in
the working area, growing smoothly out to the full extent of the terrain, so
one seamless mesh serves as both the close-up ground and the distant backdrop.
"""

import math

import bpy
import numpy as np

from . import meshgen
from .heightfield import Heightfield, smoothstep


def _graded_axis(lo_fine, hi_fine, cell, lo_far, hi_far, cell_far, growth=1.07):
    n = int(round((hi_fine - lo_fine) / cell))
    fine = lo_fine + np.arange(n + 1) * cell

    def grow(start, end, sign):
        pts, c, p = [], cell, start
        while (end - p) * sign > 0.0 and len(pts) < 1200:
            c = min(c * growth, cell_far)
            p += sign * c
            pts.append(p)
        return pts

    left = grow(fine[0], lo_far, -1.0)[::-1]
    right = grow(fine[-1], hi_far, 1.0)
    return np.array(left + fine.tolist() + right), len(left), len(left) + len(fine)


class Stage:
    def __init__(self, hf, site, width, y_min, y_max, cell, blend=None, far_factor=1.5):
        self.src = hf.scaled_z(site.z_boost) if site.z_boost != 1.0 else hf
        self.site = site
        self.cos, self.sin = math.cos(site.yaw), math.sin(site.yaw)
        self.z0 = float(self.src.sample_smooth(site.x, site.y))
        self.width, self.y_min, self.y_max, self.cell = width, y_min, y_max, cell
        self.blend = blend if blend is not None else 0.12 * min(width, y_max - y_min)

        # extent of the whole source terrain in stage coordinates
        s = self.src
        cx = np.array([s.x0, s.x0 + s.width, s.x0 + s.width, s.x0])
        cy = np.array([s.y0, s.y0, s.y0 + s.depth, s.y0 + s.depth])
        fx, fy = self.from_source(cx, cy)
        far_cell = s.cell * far_factor
        self.xs, self.i0, self.i1 = _graded_axis(-width / 2, width / 2, cell,
                                                 fx.min(), fx.max(), far_cell)
        self.ys, self.j0, self.j1 = _graded_axis(y_min, y_max, cell,
                                                 fy.min(), fy.max(), far_cell)
        gx, gy = np.meshgrid(self.xs, self.ys)
        sx, sy = self.to_source(gx, gy)
        self.inside = s.contains(sx, sy)
        self.z = s.sample_smooth(sx, sy) - self.z0
        self.u, self.v = s.uv(sx, sy)
        self.attrs = {}

        # modifications fade out towards the rim of the fine area
        fxs, fys = self.xs[self.i0:self.i1], self.ys[self.j0:self.j1]
        dx = np.minimum(fxs - fxs[0], fxs[-1] - fxs)
        dy = np.minimum(fys - fys[0], fys[-1] - fys)
        self.weight = smoothstep(0.0, self.blend, np.minimum(dx[None, :], dy[:, None]))

    # -- frames --------------------------------------------------------------
    def to_source(self, x, y):
        return (self.site.x + x * self.cos - y * self.sin,
                self.site.y + x * self.sin + y * self.cos)

    def from_source(self, sx, sy):
        dx, dy = sx - self.site.x, sy - self.site.y
        return dx * self.cos + dy * self.sin, -dx * self.sin + dy * self.cos

    # -- fine area -----------------------------------------------------------
    @property
    def fine_shape(self):
        return (self.j1 - self.j0, self.i1 - self.i0)

    def fine_xy(self):
        return np.meshgrid(self.xs[self.i0:self.i1], self.ys[self.j0:self.j1])

    def fine(self):
        return self.z[self.j0:self.j1, self.i0:self.i1].copy()

    def apply(self, z_new, full_weight=False):
        """Write modified heights back, blended to the untouched rim."""
        cur = self.z[self.j0:self.j1, self.i0:self.i1]
        w = 1.0 if full_weight else self.weight
        self.z[self.j0:self.j1, self.i0:self.i1] = cur + w * (z_new - cur)

    def local(self, sigma_m=0.0):
        """The fine area as a uniform heightfield (stage coordinates)."""
        hf = Heightfield(self.fine(), self.cell, self.xs[self.i0], self.ys[self.j0])
        return hf.smoothed(sigma_m) if sigma_m > 0 else hf

    def height(self, x, y):
        return float(self.local_cache().sample(x, y))

    def local_cache(self):
        if getattr(self, "_local", None) is None:
            self._local = self.local()
        return self._local

    def invalidate(self):
        self._local = None

    def set_attr(self, name, fine_values, far_value=0.0):
        full = np.full(self.z.shape, far_value, dtype=np.float32)
        full[self.j0:self.j1, self.i0:self.i1] = fine_values
        self.attrs[name] = full

    def set_attr_full(self, name, values):
        self.attrs[name] = np.asarray(values, dtype=np.float32)

    def full_slope_deg(self):
        gy = np.gradient(self.z, self.ys, axis=0)
        gx = np.gradient(self.z, self.xs, axis=1)
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    # -- meshes ---------------------------------------------------------------
    def build_terrain(self, name):
        ny, nx = self.z.shape
        gx, gy = np.meshgrid(self.xs, self.ys)
        verts = np.stack([gx, gy, self.z], axis=-1).reshape(-1, 3)
        ins = self.inside
        keep = ins[:-1, :-1] & ins[:-1, 1:] & ins[1:, :-1] & ins[1:, 1:]
        quads = meshgen.grid_quads(nx, ny)[keep.ravel()]
        me = meshgen.mesh_from_arrays(name, verts, quads)
        meshgen.shade_smooth(me)
        meshgen.set_uv_from_points(me, "HesiodUV", self.u, self.v)
        for key, values in self.attrs.items():
            meshgen.set_point_attribute(me, key, values)
        obj = bpy.data.objects.new(name, me)
        return obj

    def build_collider(self, name, stride=2, floor_margin=3.0, pad=0.0):
        """Closed solid under the fine area, for fluid and rigid-body collision."""
        z = self.fine()[::stride, ::stride]
        cell = self.cell * stride
        me = meshgen.solid_mesh(name, z + pad, self.xs[self.i0], self.ys[self.j0], cell,
                                float(z.min()) - floor_margin)
        obj = bpy.data.objects.new(name, me)
        obj.display_type = "WIRE"
        obj.hide_render = True
        return obj
