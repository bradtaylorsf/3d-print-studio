# image-to-model — turn reference images into printable models

Use this skill when a project has reference images (in `projects/<name>/refs/`) and the goal
is a printable STL/3MF designed *from* them — "make this into a print", "design something
from this picture", a new image appears in refs and the user says "look at that".

## Step 1 — Read every image in refs/, then classify the job

Look at the images first. Decide which of these the target is, and say which you picked:

| Type | Signals in the image | Build strategy |
|---|---|---|
| **Flat cutout / stencil** | logo, silhouette, line art | threshold → vectorize outline (opencv/shapely) → extrude 2–6 mm |
| **Relief / plaque** | photo or drawing to hang/display | grayscale → heightmap → displaced grid on a base plate |
| **Multi-color plate** | line art with distinct color regions (like a coloring-book page) | split into per-color regions → one mesh per color in `parts/` + `parts.json`, deliver 3MF |
| **Functional part** | photo of an object to replace/fit (bracket, clip, connector) | parametric `design.py` from measured/asked dimensions — the image is for proportions |
| **Full 3D figurine** | character/object wanted "in the round" | hardest; single photo → relief or stylized parametric approximation; be honest about limits and offer the relief option |

## Step 2 — Ask only the questions the image can't answer

Batch them in ONE message; propose defaults so the user can just say "yes":

1. **Real-world size** — the one thing never inferable. Propose a number ("nameplate width
   160 mm?").
2. **Where it lives** — desk / wall (needs hanger hole?) / fits onto something (get the
   mating dimension).
3. **Colors** — single color, or CFS multi-color? If multi: which image colors map to which
   filament (≤ 4 per CFS).
4. **Anything load-bearing?** — decorative vs functional changes walls/infill later.

Skip questions when refs or chat already answer them. Never block on nice-to-knows —
default and note the assumption.

## Step 3 — Build v1 fast, iterate in the studio

- Scaffold per the design-studio skill; write `design.py` (or a one-off build script for
  relief/vectorize jobs — still saved in the project folder so it can be rerun).
- Useful toolbox already in `.venv`: `opencv-python-headless` (threshold, contours),
  `scikit-image` (marching squares), `shapely` (polygon cleanup, buffer), `trimesh`
  (`extrude_polygon`, booleans via manifold3d), `pillow`.
- Ship a rough v1 to the viewer within a few minutes, then refine from the user's reactions
  and captures. Don't polish before they've seen the silhouette at all.
- Sanity-check printability as you go: feature width ≥ 0.8 mm (2 walls), text emboss/deboss
  ≥ 0.4 mm deep, bridges < 10 mm, overhangs — flag anything that needs supports.

## Step 4 — Multi-piece / multi-color output

- One watertight mesh per color, all in **shared bed coordinates** so they stack correctly,
  exported to `parts/<piece>.stl` + `parts.json` with display hexes.
- Pieces must not z-fight: separate them in Z (base plate + inlay lines) or make regions
  butt cleanly in XY.
- Deliverable: 3MF via the k2-slicing skill's CFS workflow, plus channel assignments
  (which filament in which CFS slot).

## Finish

Repair/verify with stl-prep, copy deliverables to `final/`, update `MANIFEST.md`, quote K2
PLA settings per k2-slicing.
