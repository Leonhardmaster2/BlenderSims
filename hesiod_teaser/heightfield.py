"""Heightfield maths: terrain sources, slope / flow analysis, site finding.

Pure numpy apart from the two loaders, which need ``bpy`` (imported lazily)
so that the maths can be unit-tested outside Blender.
All horizontal distances are metres; ``h[j, i]`` is the height at
``(x0 + i * cell, y0 + j * cell)``.
"""

import math

import numpy as np

G = 9.81


# ----------------------------------------------------------------------------
# small numpy helpers
# ----------------------------------------------------------------------------

def gaussian_blur(a, sigma):
    """Separable gaussian blur with edge clamping (sigma in cells)."""
    if sigma <= 1e-3:
        return a.copy()
    r = max(1, int(math.ceil(3.0 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = a.astype(np.float64)
    for axis in (0, 1):
        n = out.shape[axis]
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        for t in range(2 * r + 1):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(t, t + n)
            acc += k[t] * p[tuple(sl)]
        out = acc
    return out


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def spectral_noise(shape, cell, lam_min, lam_max, hurst, rng):
    """Band-limited fractal noise (unit std, zero mean), built with an FFT.

    ``lam_min`` / ``lam_max`` are the shortest / longest wavelengths in metres.
    """
    ny, nx = shape
    fx = np.fft.rfftfreq(nx, d=cell)
    fy = np.fft.fftfreq(ny, d=cell)
    f = np.sqrt(fx[None, :] ** 2 + fy[:, None] ** 2)
    f[0, 0] = 1.0
    amp = f ** (-(hurst + 1.0))
    amp[(f < 1.0 / lam_max) | (f > 1.0 / max(lam_min, 2.0 * cell))] = 0.0
    amp[0, 0] = 0.0
    phase = rng.uniform(0.0, 2.0 * math.pi, size=f.shape)
    field = np.fft.irfft2(amp * np.exp(1j * phase), s=(ny, nx))
    sd = field.std()
    return field / sd if sd > 1e-12 else field


def worley(shape, cell, feature, rng):
    """Cellular noise: (distance to the nearest feature point / feature size,
    a random value per cell). Used to model cobbles, blocks and scree."""
    ny, nx = shape
    y, x = np.mgrid[0:ny, 0:nx] * (cell / feature)
    ci, cj = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    gw, gh = int(ci.max()) + 3, int(cj.max()) + 3
    px = rng.uniform(0.1, 0.9, (gh, gw))
    py = rng.uniform(0.1, 0.9, (gh, gw))
    val = rng.uniform(0.0, 1.0, (gh, gw))
    best = np.full(shape, 1e9)
    ident = np.zeros(shape)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            ii, jj = ci + di + 1, cj + dj + 1
            d = np.hypot(ii - 1 + px[jj, ii] - x, jj - 1 + py[jj, ii] - y)
            closer = d < best
            best = np.where(closer, d, best)
            ident = np.where(closer, val[jj, ii], ident)
    return best, ident


def bilinear(h, fi, fj):
    """Sample ``h`` at fractional indices (clamped at the borders)."""
    ny, nx = h.shape
    fi = np.clip(fi, 0.0, nx - 1.0)
    fj = np.clip(fj, 0.0, ny - 1.0)
    i0 = np.minimum(fi.astype(np.int64), nx - 2)
    j0 = np.minimum(fj.astype(np.int64), ny - 2)
    tx = fi - i0
    ty = fj - j0
    a = h[j0, i0] * (1 - tx) + h[j0, i0 + 1] * tx
    b = h[j0 + 1, i0] * (1 - tx) + h[j0 + 1, i0 + 1] * tx
    return a * (1 - ty) + b * ty


def _cubic_weights(t):
    t2, t3 = t * t, t * t * t
    return (-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0,
            -1.5 * t3 + 2.0 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2)


def bicubic(h, fi, fj):
    """Catmull-Rom sample of ``h`` (smooth, so close-ups show no grid creases)."""
    ny, nx = h.shape
    fi = np.clip(fi, 0.0, nx - 1.0)
    fj = np.clip(fj, 0.0, ny - 1.0)
    i1 = np.minimum(np.floor(fi).astype(np.int64), nx - 2)
    j1 = np.minimum(np.floor(fj).astype(np.int64), ny - 2)
    wx = _cubic_weights(fi - i1)
    wy = _cubic_weights(fj - j1)
    out = np.zeros(np.broadcast(fi, fj).shape)
    for b in range(4):
        jj = np.clip(j1 + b - 1, 0, ny - 1)
        row = np.zeros_like(out)
        for a in range(4):
            ii = np.clip(i1 + a - 1, 0, nx - 1)
            row += wx[a] * h[jj, ii]
        out += wy[b] * row
    return out


# ----------------------------------------------------------------------------
# Heightfield
# ----------------------------------------------------------------------------

class Heightfield:
    def __init__(self, h, cell, x0=0.0, y0=0.0):
        self.h = np.ascontiguousarray(h, dtype=np.float64)
        self.cell = float(cell)
        self.x0 = float(x0)
        self.y0 = float(y0)
        # optional: texture image + the object it came from (set by loaders)
        self.texture = None
        self.source_name = ""

    # -- geometry ----------------------------------------------------------
    @property
    def shape(self):
        return self.h.shape

    @property
    def width(self):
        return (self.h.shape[1] - 1) * self.cell

    @property
    def depth(self):
        return (self.h.shape[0] - 1) * self.cell

    @property
    def relief(self):
        return float(self.h.max() - self.h.min())

    def sample(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return bilinear(self.h, (x - self.x0) / self.cell, (y - self.y0) / self.cell)

    def sample_smooth(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return bicubic(self.h, (x - self.x0) / self.cell, (y - self.y0) / self.cell)

    def contains(self, x, y):
        return ((x >= self.x0) & (x <= self.x0 + self.width) &
                (y >= self.y0) & (y <= self.y0 + self.depth))

    def uv(self, x, y):
        """Planar 0..1 UV of a metric position (matches a grid's default UVs)."""
        return ((np.asarray(x) - self.x0) / max(self.width, 1e-9),
                (np.asarray(y) - self.y0) / max(self.depth, 1e-9))

    def smoothed(self, sigma_m):
        out = Heightfield(gaussian_blur(self.h, sigma_m / self.cell), self.cell, self.x0, self.y0)
        out.texture, out.source_name = self.texture, self.source_name
        return out

    def scaled_z(self, k):
        out = Heightfield(self.h * k, self.cell, self.x0, self.y0)
        out.texture, out.source_name = self.texture, self.source_name
        return out

    def decimated(self, max_res):
        n = max(self.h.shape)
        step = int(math.ceil(n / float(max_res)))
        if step <= 1:
            return self
        out = Heightfield(self.h[::step, ::step], self.cell * step, self.x0, self.y0)
        out.texture, out.source_name = self.texture, self.source_name
        return out

    def gradient(self):
        gy, gx = np.gradient(self.h, self.cell)
        return gx, gy

    def slope_deg(self):
        gx, gy = self.gradient()
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    def grad_at(self, x, y):
        gx, gy = self.gradient()
        fi = (np.asarray(x, dtype=np.float64) - self.x0) / self.cell
        fj = (np.asarray(y, dtype=np.float64) - self.y0) / self.cell
        return bilinear(gx, fi, fj), bilinear(gy, fi, fj)


# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------

def builtin_terrain(seed=7, width=2400.0, res=384, relief=760.0):
    """Procedural stand-in mountain used when no Hesiod terrain is plugged in.

    Ridged fractal relief with a few rounds of stream-power incision so that
    it has real gullies, steep faces and open slopes for the three shots.
    """
    rng = np.random.default_rng(seed)
    cell = width / (res - 1)
    yy, xx = np.mgrid[0:res, 0:res] / (res - 1.0)
    base = spectral_noise((res, res), cell, 4 * cell, width * 0.9, 0.95, rng)
    ridged = 1.0 - np.abs(spectral_noise((res, res), cell, 4 * cell, width * 0.45, 0.8, rng)) * 0.9
    # a massif whose crest runs across the tile, falling away to both sides
    crest = np.exp(-((yy - 0.62 + 0.10 * np.sin(xx * 5.0)) / 0.30) ** 2)
    h = crest * (0.72 + 0.20 * ridged + 0.10 * base) + 0.07 * base
    h -= h.min()
    h *= relief / h.max()
    for _ in range(4):
        acc = flow_accumulation(h)
        cut = np.log1p(acc) / math.log(res * res)
        h -= gaussian_blur(cut, 0.8) * relief * 0.035
        h = gaussian_blur(h, 0.9)
    h -= h.min()
    hf = Heightfield(h, cell)
    hf.source_name = "built-in"
    return hf


def from_object(obj, width_m, height_scale=1.0, max_res=1024):
    """Read a terrain mesh (e.g. a Hesiod bridge ``TerrainTile``) into metres."""
    import bpy

    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        m = np.array(obj.matrix_world, dtype=np.float64)
        co = co @ m[:3, :3].T + m[:3, 3]
        lo, hi = co.min(axis=0), co.max(axis=0)
        ext = hi - lo
        if ext[0] < 1e-9 or ext[1] < 1e-9:
            raise ValueError("Terrain object '%s' has no horizontal extent" % obj.name)
        s = width_m / ext[0]

        grid = _try_regular_grid(co, lo, ext, n)
        if grid is None:
            grid = _raycast_grid(me, m, lo, ext, max_res)
        h = (grid - lo[2]) * s * height_scale
    finally:
        ev.to_mesh_clear()

    cell = width_m / (h.shape[1] - 1)
    hf = Heightfield(h, cell).decimated(max_res)
    hf.source_name = obj.name
    hf.texture = _object_texture(obj)
    return hf


def _try_regular_grid(co, lo, ext, n):
    """Fast path: the mesh is a regular nx*ny grid (what the bridge streams)."""
    xs = np.unique(np.round((co[:, 0] - lo[0]) / ext[0], 5))
    nx = len(xs)
    if nx < 2 or n % nx != 0:
        return None
    ny = n // nx
    if ny < 2:
        return None
    fi = (co[:, 0] - lo[0]) / ext[0] * (nx - 1)
    fj = (co[:, 1] - lo[1]) / ext[1] * (ny - 1)
    i = np.rint(fi).astype(np.int64)
    j = np.rint(fj).astype(np.int64)
    if np.abs(fi - i).max() > 0.02 or np.abs(fj - j).max() > 0.02:
        return None
    flat = j * nx + i
    if len(np.unique(flat)) != n:
        return None
    grid = np.empty(n, dtype=np.float64)
    grid[flat] = co[:, 2]
    return grid.reshape(ny, nx)


def _raycast_grid(me, m, lo, ext, max_res):
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    n = len(me.vertices)
    res = int(min(max_res, max(128, math.sqrt(n) * 1.5)))
    nx = res
    ny = max(2, int(round(res * ext[1] / ext[0])))
    verts = [tuple(np.array(v.co) @ m[:3, :3].T + m[:3, 3]) for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=False)
    down = Vector((0.0, 0.0, -1.0))
    top = lo[2] + ext[2] + 10.0
    grid = np.full((ny, nx), np.nan)
    for j in range(ny):
        y = lo[1] + ext[1] * j / (ny - 1)
        for i in range(nx):
            x = lo[0] + ext[0] * i / (nx - 1)
            hit = tree.ray_cast(Vector((x, y, top)), down)
            if hit[0] is not None:
                grid[j, i] = hit[0].z
    if np.isnan(grid).all():
        raise ValueError("Could not sample the terrain mesh (no surface found from above)")
    # fill holes with the lowest point so that missing areas read as flat ground
    grid[np.isnan(grid)] = np.nanmin(grid)
    return grid


def _object_texture(obj):
    """The image the Hesiod bridge streams into the tile's material, if any."""
    for slot in getattr(obj, "material_slots", []):
        mat = slot.material
        if mat is None or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                return node.image
    return None


def from_image(path, width_m, relief_m, max_res=1024):
    """Load a heightmap image (PNG/TIFF/EXR, any bit depth); white = high."""
    import bpy

    img = bpy.data.images.load(bpy.path.abspath(path), check_existing=False)
    try:
        try:
            img.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
        w, hgt = img.size
        if w < 2 or hgt < 2:
            raise ValueError("Heightmap '%s' could not be read" % path)
        px = np.empty(w * hgt * img.channels, dtype=np.float32)
        img.pixels.foreach_get(px)
        h = px.reshape(hgt, w, img.channels)[:, :, 0].astype(np.float64)
    finally:
        bpy.data.images.remove(img)
    h -= h.min()
    if h.max() > 1e-12:
        h *= relief_m / h.max()
    hf = Heightfield(h, width_m / (w - 1)).decimated(max_res)
    hf.source_name = bpy.path.basename(path)
    return hf


# ----------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------

_NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def flow_accumulation(h):
    """D8 flow accumulation (number of upstream cells draining through each cell)."""
    ny, nx = h.shape
    pad = np.pad(h, 1, mode="edge")
    best = np.zeros((ny, nx))
    jj, ii = np.mgrid[0:ny, 0:nx]
    rec = (jj * nx + ii)
    for dj, di in _NEIGHBOURS:
        drop = (h - pad[1 + dj:1 + dj + ny, 1 + di:1 + di + nx]) / math.hypot(dj, di)
        idx = np.clip(jj + dj, 0, ny - 1) * nx + np.clip(ii + di, 0, nx - 1)
        m = drop > best
        best[m] = drop[m]
        rec[m] = idx[m]
    order = np.argsort(h, axis=None)[::-1].tolist()
    recl = rec.ravel().tolist()
    acc = [1.0] * (ny * nx)
    for i in order:
        r = recl[i]
        if r != i:
            acc[r] += acc[i]
    return np.array(acc).reshape(ny, nx)


def _border_mask(hf, margin_m):
    ny, nx = hf.shape
    m = int(math.ceil(margin_m / hf.cell))
    m = min(m, max(1, min(nx, ny) // 2 - 1))
    mask = np.zeros((ny, nx), dtype=bool)
    mask[m:ny - m, m:nx - m] = True
    return mask


def _bell(x, centre, width):
    return np.exp(-((x - centre) / width) ** 2)


class Site:
    """A chosen spot on the terrain: position, uphill heading, vertical boost."""

    def __init__(self, x, y, yaw, z_boost=1.0, slope=0.0, note=""):
        self.x, self.y, self.yaw = float(x), float(y), float(yaw)
        self.z_boost = float(z_boost)
        self.slope = float(slope)
        self.note = note

    def __repr__(self):
        return "Site(x=%.1f, y=%.1f, yaw=%.1f deg, slope=%.1f deg, z_boost=%.2f)" % (
            self.x, self.y, math.degrees(self.yaw), self.slope, self.z_boost)


def _uphill_yaw(hf_s, x, y):
    gx, gy = hf_s.grad_at(x, y)
    gx, gy = float(gx), float(gy)
    if math.hypot(gx, gy) < 1e-9:
        return 0.0
    # yaw is the rotation about Z that turns stage +Y onto the uphill direction
    return math.atan2(-gx, gy)


def _mean_slope_along(hf_s, yaw, dist):
    """Slope (deg) measured over ``dist`` metres uphill of every cell."""
    ny, nx = hf_s.shape
    jj, ii = np.mgrid[0:ny, 0:nx]
    x = hf_s.x0 + ii * hf_s.cell
    y = hf_s.y0 + jj * hf_s.cell
    gx, gy = hf_s.gradient()
    g = np.hypot(gx, gy) + 1e-9
    ux, uy = gx / g, gy / g
    up = hf_s.sample(x + ux * dist, y + uy * dist)
    return np.degrees(np.arctan2(up - hf_s.h, dist))


def find_site(hf, kind, analysis_res=384):
    """Pick a location for a shot. ``kind`` is 'WATER', 'ROCK' or 'SNOW'.

    If the terrain is too gentle for the shot a vertical boost (applied to the
    whole terrain in that shot only) is returned alongside the position.
    """
    a = hf.decimated(analysis_res)
    if kind == "WATER":
        target, tol, reach, margin, sig = 19.0, 8.0, 40.0, 60.0, 1.5 * a.cell
    elif kind == "ROCK":
        target, tol, reach, margin, sig = 46.0, 8.0, 60.0, 90.0, max(6.0, 1.0 * a.cell)
    else:
        target, tol, reach, margin, sig = 36.0, 5.0, 150.0, 260.0, max(12.0, 1.5 * a.cell)
    margin = min(margin, 0.3 * min(a.width, a.depth))
    s = a.smoothed(sig)
    mask = _border_mask(a, margin)

    acc_term = None
    if kind == "WATER":
        acc = flow_accumulation(s.h)
        acc_term = np.log1p(acc)
        acc_term /= max(acc_term.max(), 1e-9)

    best = None
    for boost in (1.0, 1.25, 1.6, 2.0, 2.6, 3.4, 4.5):
        sb = s.scaled_z(boost)
        slope = _mean_slope_along(sb, 0.0, reach)
        score = _bell(slope, target, tol)
        if kind == "WATER":
            score = score * (0.15 + acc_term ** 2)
        elif kind == "SNOW":
            # an open, even slope: penalise curvature
            gx, gy = sb.gradient()
            curv = np.abs(np.gradient(gx, sb.cell, axis=1)) + np.abs(np.gradient(gy, sb.cell, axis=0))
            score = score * np.exp(-gaussian_blur(curv, 2.0) * 60.0)
            # and it needs a slope continuing below it for the run-out
            below = _mean_slope_along(sb, 0.0, -reach)  # negative = downhill
            score = score * smoothstep(8.0, 22.0, -below)
        score = np.where(mask, score, 0.0)
        j, i = np.unravel_index(int(np.argmax(score)), score.shape)
        quality = float(_bell(slope[j, i], target, tol))
        cand = (quality, boost, i, j, float(slope[j, i]))
        if best is None or quality > best[0] + 0.15:
            best = cand
        if quality > 0.6:
            break
    quality, boost, i, j, slope_here = best
    x = a.x0 + i * a.cell
    y = a.y0 + j * a.cell
    yaw = _uphill_yaw(s, x, y)
    note = "" if boost == 1.0 else "terrain height boosted x%.2f for this shot" % boost
    return Site(x, y, yaw, boost, slope_here, note)


def trace_descent(hf_s, x, y, step, max_len, inertia=0.6):
    """Follow the fall line downhill. Returns (points[n,2], arc_length[n])."""
    pts = [(x, y)]
    dx, dy = 0.0, 0.0
    n = int(max_len / step)
    xmin, xmax = hf_s.x0, hf_s.x0 + hf_s.width
    ymin, ymax = hf_s.y0, hf_s.y0 + hf_s.depth
    for _ in range(n):
        gx, gy = hf_s.grad_at(x, y)
        gx, gy = float(gx), float(gy)
        g = math.hypot(gx, gy)
        if g > 1e-6:
            nx_, ny_ = -gx / g, -gy / g
        else:
            nx_, ny_ = dx, dy
        dx = inertia * dx + (1.0 - inertia) * nx_
        dy = inertia * dy + (1.0 - inertia) * ny_
        d = math.hypot(dx, dy)
        if d < 1e-6:
            break
        dx, dy = dx / d, dy / d
        x += dx * step
        y += dy * step
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            break
        pts.append((x, y))
    pts = np.array(pts)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])) if len(pts) > 1 else np.zeros(0)
    return pts, np.concatenate([[0.0], np.cumsum(seg)])


def voellmy(path_s, path_z, dt, n_steps, mu=0.2, xi=1800.0, v0=0.0, v_min=0.0, delay=0.0):
    """Integrate a sliding mass along a path with Voellmy friction.

    Returns the travelled arc length for each time step (length ``n_steps``).
    ``delay`` is a release delay in seconds. Once moving, speed never drops
    below ``v_min`` (a powder cloud keeps coasting on the flat).
    """
    out = np.zeros(n_steps)
    s, v = 0.0, v0
    s_end = float(path_s[-1])
    slopes = np.gradient(path_z, path_s) if len(path_s) > 1 else np.zeros(1)
    sub = 4
    h = dt / sub
    for k in range(n_steps):
        if k * dt >= delay:
            for _ in range(sub):
                tan_t = -float(np.interp(s, path_s, slopes))
                theta = math.atan(tan_t)
                a = G * (math.sin(theta) - mu * math.cos(theta)) - (G / xi) * v * v
                v = max(v + a * h, v_min if (v > 0.0 or a > 0.0) else 0.0)
                s = min(s + v * h, s_end)
        out[k] = s
    return out
