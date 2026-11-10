# Hesiod Teaser

A Blender add-on that sets up the three simulated shots of the Hesiod 0.7 teaser
on Hesiod terrain, bakes them, renders them and cuts the 25-second film.
You plug in a terrain, press four buttons, and get an MP4.

| Time | Picture | How it is made |
| --- | --- | --- |
| 0–4 s | Black, the Greek line fades in and out | Sequencer text |
| 4–8 s | **Water**: a surge down a gully hits the lens, hard cut to black | Mantaflow FLIP liquid + whitewater particles |
| 8–12 s | **Rock**: a rockfall, dust swallows the frame, cut to black | Bullet rigid bodies + gravel particles + Mantaflow smoke |
| 12–20 s | **Snow**: a still slope for two seconds, the slab releases, the powder cloud rolls over the camera to white | Layered snowpack, fracturing slab, Mantaflow smoke |
| 20–25 s | Hold the white, then logo, "0.7" and the date | Sequencer |

Requires Blender 4.2 LTS or newer (developed against 5.2 LTS, also run on 4.5 LTS). Renders with Cycles.

## Install

1. In Blender: **Edit → Preferences → Add-ons → ▾ → Install from Disk…**
2. Pick `hesiod_teaser.zip` from this repository and enable *Hesiod Teaser*.
3. The panel is in the 3D viewport sidebar (**N**) under **Hesiod Teaser**.

## Quick start

1. **Save your .blend.** Caches, frames and the film go into `hesiod_teaser/` next to it.
2. **Bring in the terrain** with the Hesiod Blender bridge (`BlenderBridge` node → *Connect* in the Hesiod tab).
   In the teaser panel press the magnifier next to *Tile* to pick the streamed `TerrainTile`.
3. Set **Real Width**. The bridge streams a tile 1 m across, so this number is what gives the
   simulations their scale. 2–4 km works well. **Height Scale** exaggerates the relief if your terrain is gentle.
4. Open **Titles and Edit** and set the **Greek Line** and the **Date** (both ship as placeholders, see below).
5. Press the buttons top to bottom:
   **1 Build All Shots → 2 Bake All Simulations → 3 Render All Shots → 4 Export Film**.

Do a pass at **Preview** quality first to check framing and timing (minutes), then switch to **Final** and
repeat from step 1. No terrain yet? Set *Terrain* to **Built-in Stand-in** and everything works on a procedural mountain.

For long bakes and renders, run it from a terminal instead so Blender's window is not blocked:

```
blender -b my_teaser.blend -P scripts/teaser_cli.py -- --all --quality FINAL
blender -b my_teaser.blend -P scripts/teaser_cli.py -- --bake --render --shots water
```

`--build`, `--bake`, `--render`, `--final` can be combined freely; `--all` is all four. The .blend is saved
after every step, so an interrupted run can be picked up with the remaining steps.

## What gets built

Each shot is its own scene (`HT_Water`, `HT_Rock`, `HT_Snow`). The scene you started in becomes the edit.

**The stage.** For every shot the add-on reads the terrain into a heightfield, finds a suitable spot on it
(a channel that collects flow for the water, a steep face for the rock, an open 32–39° slope with a run-out for
the snow), and resamples that spot into a small high-resolution patch at real-world scale: +Y uphill, 1 unit = 1 m.
The patch is graded out to the full terrain as one seamless mesh, so the Hesiod landscape is what you see behind
the action. Only the few metres in front of the lens are simulated. To choose the spot yourself, put any object
(an Empty is fine) on the tile and set it as the shot's **Location**.

A heightmap cannot hold metre-scale detail, so the patch gets some added: the gully and its stones for the water,
broken rock for the rockfall, the snowpack for the avalanche. If the chosen spot is too flat, too steep or has a bulge
that would hide the action from the camera, the patch's broad profile is corrected just enough for the shot to work.
If the whole terrain is too gentle, its height is boosted for that shot only (the scene's `ht_site` property says so).

**Water.** A channel is cut along the fall line, with a rock sill and a basin behind it. The inflow sits in the basin,
out of sight, wells up and is driven over the sill, so the first thing the camera sees is water coming over the lip.
The camera body is an obstacle, so the surge piles up against the lens. FLIP solver, fractional obstacles,
spray/foam/bubble particles, speed vectors for motion blur. The water has absorption and scattering; *Turbidity* goes
from clear meltwater to silty flood.

**Rock.** Boulders (procedural, angular, convex-hull rigid bodies) get a short shove and then tumble down the terrain
collider under Bullet. A gravel particle system bounces down the same collider. Both emit into a smoke domain whose dust
is heavier than air, so it runs downhill as a density current, helped by a gentle downslope wind.
Rigid bodies and gravel are simulated at build time, so the cut is timed before you bake any smoke.

**Snow.** The snowpack is real geometry on the terrain, thinner on steep ground where rock shows through.
The slab is a set of blocks that slide off when it releases, exposing the bed surface. The snow material shows
stratigraphy wherever the pack is cut: new snow, a blue wind slab, a thin dark melt-freeze crust, and the weak
layer it fails on, visible in the crown wall and on the sides of the blocks. Before release the slope is a single
untouched mesh (the pit is a shape key that switches on at the release frame), so the still two seconds are really still.
The powder cloud is a smoke sim fed by a moving dense core: emitters that follow the terrain's actual fall lines,
with their speed integrated from a Voellmy friction model, so the avalanche accelerates and steers like one.

**Light and colour.** Physical sky with a sun whose position is checked against the real terrain skyline, so a
neighbouring ridge cannot leave the set in shadow. Each shot has its own AgX look, exposure and white balance.
Shots render to 16-bit PNG with the look baked in; the edit passes them through unchanged.

## Timing

Simulations do not hit their marks by themselves, so each shot is re-timed to its bake (automatically after a bake,
or with the clock button):

- **Water**: finds the frame the liquid reaches the lens and moves the shot's frame range so the hard cut lands on it.
- **Rock**: finds the frame the dust closes over the lens and cuts there (before the smoke is baked: a few frames after
  the first boulder reaches the camera).
- **Snow**: the timeline is fixed (two seconds still, white at the end), so instead the camera slides along its fall
  line to where the cloud front is at the arrival time.

The edit also dissolves to white over the last half second of the snow shot, so the end card always starts from clean white.

## Things you must set

- **Greek Line** is a placeholder: the opening of Hesiod's *Theogony* (116–117), "First of all Chaos came to be, and
  then broad-breasted Earth". Replace it with your line; `\n` makes a line break. Blender's default sequencer font has
  polytonic Greek; if you set a **Font**, make sure it does too.
- **Date** ships as `DATE TBA`.
- **Logo Image** is optional; without it the end card sets the logo text in type.
- **Sound** is optional: five file slots (wind, roar, rockfall, crack, rumble) that are placed on the timeline for you.

## Files

```
hesiod_teaser/            the add-on
  heightfield.py          terrain sources, flow / slope analysis, site finding, Voellmy model
  stage.py                the resampled, graded terrain patch a shot plays on
  shots/water.py rock.py snow.py
  materials.py lighting.py
  edit.py                 the sequencer cut
  pipeline.py             build / bake / re-time / render / export
scripts/teaser_cli.py     the same pipeline from a terminal
scripts/package.py        rebuilds hesiod_teaser.zip
tests/e2e.py              tiny end-to-end run (build, bake, render, export)
tests/terrain_sources.py  Hesiod tile and heightmap inputs
tests/compat.py           quick check on another Blender version
```

`<your blend>/hesiod_teaser/cache/<shot>/` holds the simulation caches, `render/<shot>/` the frames, and the exported
film is `hesiod_teaser_0001-0600.mp4` (600 frames at the default 24 fps).

## Good to know

- **Simulations only show in rendered frames in the edit.** Until a shot is rendered the edit uses a live scene strip
  as a stand-in, and Blender does not read fluid caches through scene strips. Render the shots, then *Assemble Edit*.
- **Rebuilding a shot deletes its bake.** Change look and render settings directly in the shot scene if you want to keep it.
- **Bake All / Render All block Blender** until they finish. The per-shot Bake and Render buttons run in the background
  with a progress bar.
- Smoke domains are deliberately not adaptive and use their own static copy of the terrain collider. Mantaflow
  re-voxelises a collider on every frame if it is a rigid body or the domain is adaptive, which made bakes ~100× slower.
- The quality presets set domain resolution, noise upres, samples and resolution percentage. Per-shot **Resolution**
  overrides the preset (0 = preset).

## What has and has not been tested

Run headless with Blender 5.2.3 LTS: `tests/e2e.py` does the whole thing on the built-in terrain at tiny settings
(build, bake, re-time, render every frame of all three shots, assemble, export the MP4), and `tests/terrain_sources.py`
checks a tile built the way the Hesiod bridge builds it (plus its texture, an anchor object and a heightmap file).
`tests/compat.py` (build, bake, re-time, one rendered frame per shot, assemble) also passes on 4.5.9 LTS.
The looks were judged from small, low-sample preview frames only.

Not tested: Final-quality bakes and renders (resolution changes things like the exact surge timing, which is what the
re-timing step is for), GPU rendering, Blender 4.2-4.4, the panel in an interactive Blender window including the
background (progress-bar) Bake and Render buttons, a live bridge connection, and sound strips. Expect to tune densities,
exposure and the simulation knobs to taste once you see full-resolution frames.

The tests ran against Blender's `bpy` Python module rather than the desktop application. In that module Mantaflow
needs a small initialisation fix (`tests/manta_fix.py`); the application does not, and the add-on itself does not use it.
