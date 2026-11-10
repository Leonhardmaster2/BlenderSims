"""Fast numpy mesh construction (grids, solids, prisms, boulders)."""

import math

import bpy
import numpy as np


def mesh_from_arrays(name, verts, quads=None, tris=None):
    """Create a mesh datablock from vertex and face index arrays."""
    old = bpy.data.meshes.get(name)
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    me = bpy.data.meshes.new(name)
    verts = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    quads = np.zeros((0, 4), dtype=np.int32) if quads is None else np.asarray(quads, dtype=np.int32).reshape(-1, 4)
    tris = np.zeros((0, 3), dtype=np.int32) if tris is None else np.asarray(tris, dtype=np.int32).reshape(-1, 3)
    nq, nt = len(quads), len(tris)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(nq * 4 + nt * 3)
    me.loops.foreach_set("vertex_index", np.concatenate([quads.ravel(), tris.ravel()]))
    me.polygons.add(nq + nt)
    starts = np.concatenate([np.arange(nq, dtype=np.int32) * 4,
                             nq * 4 + np.arange(nt, dtype=np.int32) * 3])
    me.polygons.foreach_set("loop_start", starts)
    try:
        totals = np.concatenate([np.full(nq, 4, dtype=np.int32), np.full(nt, 3, dtype=np.int32)])
        me.polygons.foreach_set("loop_total", totals)
    except (AttributeError, TypeError, RuntimeError):
        pass  # 4.1+: derived from loop_start
    me.update(calc_edges=True)
    me.validate(verbose=False)
    return me


def grid_quads(nx, ny, offset=0, flip=False):
    j, i = np.mgrid[0:ny - 1, 0:nx - 1]
    a = (j * nx + i).ravel() + offset
    q = np.stack([a, a + 1, a + nx + 1, a + nx], axis=1)
    return q[:, ::-1] if flip else q


def grid_coords(nx, ny, x0, y0, cell):
    j, i = np.mgrid[0:ny, 0:nx]
    return x0 + i * cell, y0 + j * cell


def surface_mesh(name, z, x0, y0, cell, skirt=0.0, face_mask=None):
    """Open height-field surface. ``skirt`` drops a vertical curtain at the rim.

    ``face_mask`` (ny-1, nx-1 bool) removes quads where it is False.
    Vertex order is row-major, so per-vertex arrays can be set with ravel().
    """
    ny, nx = z.shape
    x, y = grid_coords(nx, ny, x0, y0, cell)
    verts = np.stack([x, y, z], axis=-1).reshape(-1, 3)
    quads = grid_quads(nx, ny)
    if face_mask is not None:
        quads = quads[face_mask.ravel()]
    if skirt > 0.0:
        rim = np.concatenate([np.arange(nx), nx - 1 + nx * np.arange(1, ny),
                              (ny - 1) * nx + np.arange(nx - 2, -1, -1),
                              nx * np.arange(ny - 2, 0, -1)])
        low = verts[rim].copy()
        low[:, 2] -= skirt
        base = len(verts)
        n = len(rim)
        k = np.arange(n)
        side = np.stack([rim[k], base + k, base + (k + 1) % n, rim[(k + 1) % n]], axis=1)
        verts = np.concatenate([verts, low])
        quads = np.concatenate([quads, side])
    return mesh_from_arrays(name, verts, quads)


def solid_mesh(name, z, x0, y0, cell, floor_z):
    """Closed, watertight solid under a height field (for fluid / rigid collision)."""
    ny, nx = z.shape
    x, y = grid_coords(nx, ny, x0, y0, cell)
    top = np.stack([x, y, z], axis=-1).reshape(-1, 3)
    bot = top.copy()
    bot[:, 2] = floor_z
    n = nx * ny
    quads = [grid_quads(nx, ny), grid_quads(nx, ny, offset=n, flip=True)]
    rim = np.concatenate([np.arange(nx), nx - 1 + nx * np.arange(1, ny),
                          (ny - 1) * nx + np.arange(nx - 2, -1, -1),
                          nx * np.arange(ny - 2, 0, -1)])
    k = np.arange(len(rim))
    r0, r1 = rim[k], rim[(k + 1) % len(rim)]
    quads.append(np.stack([r0, r0 + n, r1 + n, r1], axis=1))
    return mesh_from_arrays(name, np.concatenate([top, bot]), np.concatenate(quads))


def set_point_attribute(me, name, values):
    attr = me.attributes.get(name)
    if attr is None:
        attr = me.attributes.new(name, "FLOAT", "POINT")
    v = np.asarray(values, dtype=np.float32).ravel()
    if len(v) < len(me.vertices):
        v = np.concatenate([v, np.zeros(len(me.vertices) - len(v), dtype=np.float32)])
    attr.data.foreach_set("value", v[:len(me.vertices)])


def set_uv_from_points(me, name, u, v):
    """Per-vertex UVs written to a UV map (padded for skirt vertices)."""
    nv = len(me.vertices)
    u = np.asarray(u, dtype=np.float32).ravel()
    v = np.asarray(v, dtype=np.float32).ravel()
    if len(u) < nv:
        pad = nv - len(u)
        u = np.concatenate([u, np.zeros(pad, dtype=np.float32)])
        v = np.concatenate([v, np.zeros(pad, dtype=np.float32)])
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name)
    idx = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", idx)
    uv = np.stack([u[idx], v[idx]], axis=1).astype(np.float32)
    layer.data.foreach_set("uv", uv.ravel())


def shade_smooth(me):
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), dtype=bool))
    me.update()


def boulder_mesh(name, radius, rng, subdiv=3):
    """An angular, slightly flattened boulder (displaced, plane-cut icosphere)."""
    import bmesh
    from mathutils import noise, Vector

    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    off = Vector(rng.uniform(-50, 50, 3).tolist())
    stretch = np.array([rng.uniform(0.8, 1.25), rng.uniform(0.8, 1.2), rng.uniform(0.55, 0.9)])
    cuts = []
    for _ in range(int(rng.integers(4, 8))):
        n = rng.normal(size=3)
        n /= np.linalg.norm(n)
        cuts.append((n, rng.uniform(0.62, 0.9)))
    for v in bm.verts:
        p = np.array(v.co)
        for n, d in cuts:  # flatten against random planes -> facets
            over = float(p @ n) - d
            if over > 0.0:
                p = p - n * over
        q = Vector(p.tolist())
        disp = noise.fractal(q * 1.6 + off, 1.0, 2.0, 4) * 0.16
        p = p * (1.0 + disp) * stretch * radius
        v.co = p.tolist()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    shade_smooth(me)
    return me


def prism_mesh(name, top_xy, top_z, bottom_z, depth_top=0.0):
    """A closed prism from a convex polygon; returns mesh and per-vertex depth.

    ``top_xy`` (n,2) counter-clockwise, ``top_z`` / ``bottom_z`` (n,) heights.
    """
    n = len(top_xy)
    top = np.column_stack([top_xy, top_z])
    bot = np.column_stack([top_xy, bottom_z])
    verts = np.concatenate([top, bot])
    k = np.arange(n)
    sides = np.stack([k, k + n, (k + 1) % n + n, (k + 1) % n], axis=1)
    if n == 4:
        quads = np.concatenate([[[0, 1, 2, 3]], [[7, 6, 5, 4]], sides])
        me = mesh_from_arrays(name, verts, quads)
    else:
        tris = [[0, i, i + 1] for i in range(1, n - 1)] + [[n, n + i + 1, n + i] for i in range(1, n - 1)]
        me = mesh_from_arrays(name, verts, sides, tris)
    depth = np.concatenate([np.full(n, depth_top), top_z - bottom_z + depth_top])
    return me, depth


def ellipsoid_mesh(name, rx, ry, rz, subdiv=2):
    import bmesh

    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    for v in bm.verts:
        v.co.x *= rx
        v.co.y *= ry
        v.co.z *= rz
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def box_mesh(name, lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    q = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return mesh_from_arrays(name, v, q)
