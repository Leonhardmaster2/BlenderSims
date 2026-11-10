"""Procedural Cycles materials: rock, wet rock, water, whitewater, layered
snow, and the dust / powder volumes. Everything is in metres (object space).
"""

import bpy

from .compat import new_material, set_input


class Tree:
    """Tiny helper to keep node-graph code readable."""

    def __init__(self, tree):
        self.tree = tree
        self._col = 0

    def node(self, kind, inputs=None, **props):
        n = self.tree.nodes.new(kind)
        n.location = (self._col * 190 - 1400, -150 * (self._col % 5))
        self._col += 1
        for key, value in props.items():
            try:
                setattr(n, key, value)
            except (AttributeError, TypeError, ValueError):
                pass
        for key, value in (inputs or {}).items():
            self.set(n, key, value)
        return n

    def set(self, node, key, value):
        sock = node.inputs[key] if isinstance(key, int) else node.inputs.get(key)
        if sock is None:
            return
        if hasattr(value, "is_linked") or isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, sock)
        else:
            try:
                sock.default_value = value
            except (TypeError, ValueError):
                pass

    def link(self, a, b):
        self.tree.links.new(a, b)

    # -- common building blocks ---------------------------------------------
    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        if c is not None:
            self.set(n, 2, c)
        return n.outputs[0]

    def mix(self, fac, a, b, blend="MIX"):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self.set(n, 0, fac)
        self.set(n, 6, a)
        self.set(n, 7, b)
        return n.outputs[2]

    def mixf(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT")
        self.set(n, 0, fac)
        self.set(n, 2, a)
        self.set(n, 3, b)
        return n.outputs[0]

    def ramp(self, fac, stops, interpolation="LINEAR"):
        n = self.node("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = interpolation
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = col if len(col) == 4 else (*col, 1.0)
        self.set(n, 0, fac)
        return n.outputs[0]

    def noise(self, vector, scale, detail=6.0, rough=0.55, distortion=0.0):
        n = self.node("ShaderNodeTexNoise", noise_dimensions="3D")
        self.set(n, "Vector", vector)
        self.set(n, "Scale", scale)
        self.set(n, "Detail", detail)
        self.set(n, "Roughness", rough)
        self.set(n, "Distortion", distortion)
        return n.outputs[0]

    def attr(self, name):
        n = self.node("ShaderNodeAttribute", attribute_name=name, attribute_type="GEOMETRY")
        return n.outputs[2]

    def map_range(self, value, a, b, c=0.0, d=1.0, smooth=True):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP" if smooth else "LINEAR")
        self.set(n, 0, value)
        self.set(n, 1, a)
        self.set(n, 2, b)
        self.set(n, 3, c)
        self.set(n, 4, d)
        return n.outputs[0]


def _output(t, surface=None, volume=None):
    out = t.node("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    if surface is not None:
        t.link(surface, out.inputs["Surface"])
    if volume is not None:
        t.link(volume, out.inputs["Volume"])
    return out


def _rock_layers(t, coords, texture=None, texture_mix=0.75, tint=(1.0, 1.0, 1.0)):
    """Shared rock look. Returns (colour, roughness, bump-height) sockets."""
    big = t.noise(coords, 0.045, 5.0, 0.6, 0.3)
    mid = t.noise(coords, 0.55, 7.0, 0.62, 0.2)
    fine = t.noise(coords, 7.0, 6.0, 0.7)

    # fracture lines: a warped, stretched cell pattern so it never reads as paving
    warp = t.node("ShaderNodeTexNoise", noise_dimensions="3D")
    t.set(warp, "Vector", coords)
    t.set(warp, "Scale", 0.35)
    t.set(warp, "Detail", 4.0)
    wv = t.node("ShaderNodeVectorMath", operation="MULTIPLY_ADD")
    t.link(warp.outputs[1], wv.inputs[0])
    t.set(wv, 1, (2.6, 2.6, 2.6))
    t.link(coords, wv.inputs[2])
    stretch = t.node("ShaderNodeMapping")
    t.link(wv.outputs[0], stretch.inputs["Vector"])
    t.set(stretch, "Scale", (0.55, 1.7, 2.6))
    t.set(stretch, "Rotation", (0.3, 0.2, 0.6))
    vor = t.node("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE")
    t.link(stretch.outputs[0], vor.inputs["Vector"])
    t.set(vor, "Scale", 0.45)
    crack_gate = t.map_range(t.noise(coords, 0.12, 3.0, 0.5), 0.52, 0.66)
    cracks = t.math("SUBTRACT", 1.0, t.math(
        "MULTIPLY", t.math("SUBTRACT", 1.0, t.map_range(vor.outputs[0], 0.0, 0.05, 0.0, 1.0)), crack_gate))

    # tilted, wobbly strata
    sep = t.node("ShaderNodeSeparateXYZ")
    t.set(sep, 0, coords)
    bed = t.math("ADD", sep.outputs[2], t.math("MULTIPLY", sep.outputs[0], 0.25))
    bed = t.math("ADD", bed, t.math("MULTIPLY", big, 6.0))
    strata = t.noise(t.node("ShaderNodeCombineXYZ", inputs={2: bed}).outputs[0], 1.3, 3.0, 0.5)

    tone = t.math("ADD", t.math("MULTIPLY", mid, 0.6), t.math("MULTIPLY", big, 0.4))
    tone = t.math("ADD", tone, t.math("MULTIPLY", t.math("SUBTRACT", strata, 0.5), 0.35))
    col = t.ramp(tone, [(0.30, (0.040, 0.038, 0.036)), (0.50, (0.115, 0.105, 0.096)),
                        (0.70, (0.240, 0.220, 0.195))])
    col = t.mix(1.0, col, (*tint, 1.0), "MULTIPLY")

    if texture is not None:
        uv = t.node("ShaderNodeUVMap", uv_map="HesiodUV")
        img = t.node("ShaderNodeTexImage", image=texture, interpolation="Cubic", extension="EXTEND")
        t.link(uv.outputs[0], img.inputs["Vector"])
        # keep the Hesiod colour, modulated by the procedural value for close-up detail
        detail = t.math("ADD", t.math("MULTIPLY", tone, 1.1), 0.45)
        tex = t.mix(1.0, img.outputs["Color"],
                    t.node("ShaderNodeCombineColor", inputs={0: detail, 1: detail, 2: detail}).outputs[0],
                    "MULTIPLY")
        col = t.mix(texture_mix, col, tex)

    # scree / dirt on ledges and flatter ground
    geo = t.node("ShaderNodeNewGeometry")
    nsep = t.node("ShaderNodeSeparateXYZ")
    t.link(geo.outputs["Normal"], nsep.inputs[0])
    flat = t.map_range(t.math("ADD", nsep.outputs[2], t.math("MULTIPLY", t.math("SUBTRACT", mid, 0.5), 0.3)),
                       0.74, 0.92)
    scree = t.ramp(fine, [(0.3, (0.085, 0.072, 0.058)), (0.7, (0.200, 0.172, 0.140))])
    if texture is None:
        col = t.mix(t.math("MULTIPLY", flat, 0.8), col, scree)
    col = t.mix(t.math("MULTIPLY", t.math("SUBTRACT", 1.0, cracks), 0.22), col, (0.02, 0.02, 0.02, 1.0))

    rough = t.math("ADD", 0.72, t.math("MULTIPLY", fine, 0.2))
    height = t.math("ADD", t.math("MULTIPLY", mid, 0.5), t.math("MULTIPLY", fine, 0.12))
    height = t.math("ADD", height, t.math("MULTIPLY", cracks, 0.12))
    height = t.math("ADD", height, t.math("MULTIPLY", strata, 0.25))
    return col, rough, height


def rock(name, texture=None, texture_mix=0.75, wet=False, tint=(1.0, 1.0, 1.0)):
    mat = new_material(name)
    t = Tree(mat.node_tree)
    coords = t.node("ShaderNodeTexCoord").outputs["Object"]
    col, rough, height = _rock_layers(t, coords, texture, texture_mix, tint)
    bsdf = t.node("ShaderNodeBsdfPrincipled")
    if wet:
        w = t.attr("ht_wet")
        col = t.mix(t.math("MULTIPLY", w, 0.62), col, (0.0, 0.0, 0.0, 1.0))
        rough = t.mixf(w, rough, 0.22)
        t.set(bsdf, "Coat Weight", t.math("MULTIPLY", w, 0.3))
        t.set(bsdf, "Coat Roughness", 0.05)
    bump = t.node("ShaderNodeBump", inputs={"Strength": 1.0, "Distance": 0.22})
    t.set(bump, "Height", height)
    t.set(bsdf, "Base Color", col)
    t.set(bsdf, "Roughness", rough)
    t.set(bsdf, "Normal", bump.outputs[0])
    _output(t, bsdf.outputs[0])
    return mat


def water(name, turbidity=0.3):
    """Cold, aerated torrent water. ``turbidity`` 0 = clear melt, 1 = silt flood."""
    mat = new_material(name)
    t = Tree(mat.node_tree)
    bsdf = t.node("ShaderNodeBsdfPrincipled", inputs={
        "Base Color": (1.0, 1.0, 1.0, 1.0), "Roughness": 0.035, "IOR": 1.333,
        "Transmission Weight": 1.0, "Specular IOR Level": 0.5})
    # micro ripples that the simulation grid cannot resolve
    coords = t.node("ShaderNodeTexCoord").outputs["Object"]
    bump = t.node("ShaderNodeBump", inputs={"Strength": 0.25, "Distance": 0.02})
    t.set(bump, "Height", t.noise(coords, 9.0, 3.0, 0.6))
    t.set(bsdf, "Normal", bump.outputs[0])

    clear = (0.52, 0.80, 0.83)
    silt = (0.50, 0.40, 0.27)
    k = max(0.0, min(1.0, turbidity))
    tint = tuple(clear[i] * (1 - k) + silt[i] * k for i in range(3))
    absorb = t.node("ShaderNodeVolumeAbsorption", inputs={"Color": (*tint, 1.0), "Density": 0.9 + 2.5 * k})
    scatter = t.node("ShaderNodeVolumeScatter", inputs={
        "Color": (0.80 - 0.1 * k, 0.88 - 0.2 * k, 0.86 - 0.35 * k, 1.0),
        "Density": 0.6 + 5.0 * k, "Anisotropy": 0.5})
    add = t.node("ShaderNodeAddShader")
    t.link(absorb.outputs[0], add.inputs[0])
    t.link(scatter.outputs[0], add.inputs[1])
    _output(t, bsdf.outputs[0], add.outputs[0])
    return mat


def whitewater(name):
    """Foam / spray / bubble particles: bright, soft, slightly translucent."""
    mat = new_material(name)
    t = Tree(mat.node_tree)
    bsdf = t.node("ShaderNodeBsdfPrincipled", inputs={
        "Base Color": (0.93, 0.96, 0.97, 1.0), "Roughness": 0.55,
        "Subsurface Weight": 1.0, "Subsurface Radius": (0.4, 0.5, 0.5), "Subsurface Scale": 0.05,
        "Specular IOR Level": 0.3})
    _output(t, bsdf.outputs[0])
    return mat


SNOW_LAYERS = [
    # (relative depth in the slab, tint) - what the crown wall and block sides show
    (0.00, (1.00, 1.00, 1.00)),   # new snow
    (0.24, (0.97, 0.98, 1.00)),
    (0.28, (0.60, 0.70, 0.85)),   # wind slab: denser, bluer
    (0.50, (0.66, 0.75, 0.88)),
    (0.54, (0.95, 0.96, 0.99)),   # older storm snow
    (0.68, (0.90, 0.92, 0.96)),
    (0.71, (0.32, 0.34, 0.38)),   # melt-freeze crust: a thin dark line
    (0.76, (0.84, 0.87, 0.92)),
    (0.88, (0.80, 0.83, 0.88)),
    (0.91, (0.40, 0.39, 0.38)),   # weak layer (depth hoar) the slab fails on
    (0.985, (0.46, 0.45, 0.44)),
    (1.00, (0.74, 0.79, 0.87)),   # bed surface: old, hard snow
]


def snow(name, slab_thickness=1.2, rock_texture=None):
    """Snow with visible stratigraphy wherever the pack is cut open.

    Layer depth comes from ``ht_depth`` (slab blocks) or, on the ground mesh,
    from how far the surface has dropped below ``ht_surf_z`` (the crown wall
    and bed surface after the slab releases). ``ht_rock`` = 1 exposes rock.
    """
    mat = new_material(name)
    t = Tree(mat.node_tree)
    coords = t.node("ShaderNodeTexCoord").outputs["Object"]
    geo = t.node("ShaderNodeNewGeometry")
    psep = t.node("ShaderNodeSeparateXYZ")
    t.link(geo.outputs["Position"], psep.inputs[0])

    drop = t.math("MAXIMUM", t.math("SUBTRACT", t.attr("ht_surf_z"), psep.outputs[2]), 0.0)
    depth = t.math("ADD", t.attr("ht_depth"), t.math("MULTIPLY", drop, t.attr("ht_ground")))
    wobble = t.math("MULTIPLY", t.math("SUBTRACT", t.noise(coords, 0.35, 3.0, 0.5), 0.5), 0.10)
    rel = t.math("ADD", t.math("DIVIDE", depth, max(slab_thickness, 0.05)), wobble)
    # only show strata where the pack is actually cut (depth > a few cm)
    cut = t.map_range(depth, 0.02, 0.10)
    layers = t.ramp(rel, SNOW_LAYERS)
    layer_col = t.mix(cut, (1.0, 1.0, 1.0, 1.0), layers)

    drift = t.noise(coords, 0.06, 4.0, 0.55, 0.4)
    base = t.ramp(drift, [(0.3, (0.86, 0.90, 0.96)), (0.7, (0.93, 0.95, 0.98))])
    col = t.mix(1.0, base, layer_col, "MULTIPLY")

    grain = t.noise(coords, 60.0, 2.0, 0.8)
    ripple = t.noise(coords, 0.8, 5.0, 0.6, 0.6)
    height = t.math("ADD", t.math("MULTIPLY", ripple, 0.35), t.math("MULTIPLY", grain, 0.02))
    height = t.math("ADD", height, t.math("MULTIPLY", drift, 0.8))
    bump = t.node("ShaderNodeBump", inputs={"Strength": 0.35, "Distance": 0.08})
    t.set(bump, "Height", height)

    snow_bsdf = t.node("ShaderNodeBsdfPrincipled", inputs={
        "Roughness": 0.42, "Subsurface Weight": 1.0,
        "Subsurface Radius": (0.36, 0.46, 0.60), "Subsurface Scale": 0.18,
        "Specular IOR Level": 0.35, "IOR": 1.31,
        "Sheen Weight": 0.15, "Sheen Roughness": 0.4})
    t.set(snow_bsdf, "Base Color", col)
    # cut faces scatter less, so the strata stay crisp instead of glowing away
    t.set(snow_bsdf, "Subsurface Weight", t.mixf(cut, 1.0, 0.25))
    t.set(snow_bsdf, "Roughness", t.math("ADD", 0.36, t.math("MULTIPLY", grain, 0.25)))
    t.set(snow_bsdf, "Normal", bump.outputs[0])

    rcol, rrough, rheight = _rock_layers(t, coords, rock_texture, 0.6, (0.8, 0.82, 0.88))
    rbump = t.node("ShaderNodeBump", inputs={"Strength": 0.9, "Distance": 0.15})
    t.set(rbump, "Height", rheight)
    rock_bsdf = t.node("ShaderNodeBsdfPrincipled")
    t.set(rock_bsdf, "Base Color", rcol)
    t.set(rock_bsdf, "Roughness", rrough)
    t.set(rock_bsdf, "Normal", rbump.outputs[0])

    # break the snow line up with noise so it does not follow the mask exactly
    edge = t.noise(coords, 0.25, 5.0, 0.65)
    fac = t.map_range(t.math("ADD", t.attr("ht_rock"), t.math("MULTIPLY", t.math("SUBTRACT", edge, 0.5), 0.5)),
                      0.40, 0.60)
    mix = t.node("ShaderNodeMixShader")
    t.link(fac, mix.inputs[0])
    t.link(snow_bsdf.outputs[0], mix.inputs[1])
    t.link(rock_bsdf.outputs[0], mix.inputs[2])
    _output(t, mix.outputs[0])
    return mat


def smoke_volume(name, colour, density, anisotropy, noise_scale=0.0, ambient=0.0):
    """Volume shader for a Mantaflow gas domain (reads the 'density' grid).

    ``ambient`` adds light in proportion to density. It stands in for the many
    scattering bounces inside a bright cloud, so the camera whites out inside
    a powder cloud instead of going dark, without needing dozens of bounces.
    The radiance deep inside the cloud tends towards ``ambient``.
    """
    mat = new_material(name)
    t = Tree(mat.node_tree)
    info = t.node("ShaderNodeVolumeInfo")
    dens = t.math("MULTIPLY", info.outputs["Density"], density)
    if noise_scale > 0.0:
        # break up the voxel look with a little sub-grid variation
        coords = t.node("ShaderNodeTexCoord").outputs["Object"]
        n = t.noise(coords, noise_scale, 4.0, 0.6)
        dens = t.math("MULTIPLY", dens, t.map_range(n, 0.25, 0.75, 0.55, 1.45))
    vol = t.node("ShaderNodeVolumePrincipled", inputs={
        "Color": (*colour, 1.0), "Anisotropy": anisotropy, "Density Attribute": "",
        "Blackbody Intensity": 0.0})
    t.set(vol, "Density", dens)
    if ambient > 0.0:
        t.set(vol, "Emission Color", (*colour, 1.0))
        t.set(vol, "Emission Strength", t.math("MULTIPLY", dens, ambient))
    _output(t, None, vol.outputs[0])
    return mat


def emission(name, colour, strength=1.0):
    mat = new_material(name)
    t = Tree(mat.node_tree)
    em = t.node("ShaderNodeEmission", inputs={"Color": (*colour, 1.0), "Strength": strength})
    _output(t, em.outputs[0])
    return mat
