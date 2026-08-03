---
name: stl-prep
description: >-
  Create, inspect, repair, orient, scale, hollow, split, and merge STL and 3MF files
  programmatically for 3D printing on the Creality K2 — so the user does not need an external
  mesh editor. Use whenever the user wants to check/fix a mesh, resize a model to a real-world
  dimension, reorient to reduce supports, hollow a model to save filament, split a too-big model,
  add a base/raft platform, generate simple parametric geometry, or convert between STL and 3MF. Trigger on:
  "is this printable", "fix this mesh", "scale to", "make it fit", "hollow", "split", "add a base",
  "reorient", "repair", "watertight", "STL", "3MF", "too big for the bed".
---

# STL / 3MF Prep

This is the "do it for me" skill. Use Python (`trimesh`, `numpy-stl`, `numpy`) in the sandbox to
make files **print-ready for the K2** (build volume 300×300×300 mm; design to ≤295³ mm).
Always **keep the original file untouched** and write edits to a new descriptive filename
(see CLAUDE.md naming rules).

A ready-to-use helper script lives next to this skill: **`meshtools.py`**. Prefer it for common
operations; drop to inline trimesh for anything custom.

## Always start with inspection

Before any advice or edit, report:

- **Bounding box** in mm (X, Y, Z) and whether it fits 295³.
- **Triangle/vertex count.**
- **Watertight / manifold?** and **winding/normals consistent?**
- **Volume** (cm³) → rough filament estimate.
- **Number of disconnected bodies** (a "single" STL may be several parts).

```bash
python3 skills/stl-prep/meshtools.py info "path/to/model.stl"
```

If the mesh is not watertight or has flipped normals, **repair before recommending settings**.

## Common operations (via meshtools.py)

```bash
# Inspect
python3 skills/stl-prep/meshtools.py info MODEL.stl

# Repair: fill holes, fix normals/winding, merge dup verts, remove degenerate faces
python3 skills/stl-prep/meshtools.py repair MODEL.stl MODEL_repaired.stl

# Scale to an absolute height in mm (keeps aspect ratio), or by factor
python3 skills/stl-prep/meshtools.py scale MODEL.stl OUT.stl --height 135
python3 skills/stl-prep/meshtools.py scale MODEL.stl OUT.stl --factor 0.5

# Auto-orient guess + lay flat on bed (drops to Z=0, centers on bed)
python3 skills/stl-prep/meshtools.py layflat MODEL.stl OUT.stl

# Rotate (degrees about x/y/z) then lay flat
python3 skills/stl-prep/meshtools.py rotate MODEL.stl OUT.stl --x 90

# Add a flat cylindrical/box base so a pointed/tiny-footprint model has bed contact
python3 skills/stl-prep/meshtools.py addbase MODEL.stl OUT.stl --shape disc --diameter 80 --thickness 3

# Hollow to a shell to save filament (give wall thickness in mm)
python3 skills/stl-prep/meshtools.py hollow MODEL.stl OUT.stl --wall 2.0

# Split disconnected bodies into separate files (e.g. for per-color CFS)
python3 skills/stl-prep/meshtools.py split MODEL.stl OUTDIR/

# Convert formats (STL to/from 3MF, OBJ, PLY)
python3 skills/stl-prep/meshtools.py convert MODEL.stl MODEL.3mf

# Render a preview PNG for a visual sanity check
python3 skills/stl-prep/meshtools.py preview MODEL.stl MODEL_preview.png
```

## Orientation logic (reduce supports)

When choosing orientation, aim to:

1. Put the **largest flat face on the bed** for adhesion.
2. Get overhangs **as vertical as possible** (≤45° from vertical needs no support).
3. Put the **best/most-detailed surface up or outward**, not against supports.
4. For tall thin models, lower the center of mass or add a base (`addbase`).

`layflat` makes a reasonable first guess by resting the mesh on its largest stable facet, but
**confirm visually** with `preview` and explain the trade-off (supports vs surface quality vs
print time). Offer 1–2 alternative orientations when it's a judgment call.

## Scaling logic

- Always confirm the **intended real-world dimension** before scaling — figurine height, hole
  spacing for a functional part, etc.
- After scaling, re-check the bounding box fits 295³ and **flag thin features** (< 0.8 mm ≈ two
  0.4 mm walls won't print solid).
- STL/3MF have no inherent units in some exports — if a model imports at an absurd size, assume a
  mm↔inch or mm↔m mix-up and offer to rescale.

## Hollowing & filament saving

- Hollowing a display model with a 1.5–2.5 mm wall can cut filament dramatically. **Add drain/vent
  holes** for resin-style hollows; for FDM, infill already handles this, so prefer **low infill
  (10%) over true hollowing** unless the user specifically wants a shell.
- State the before/after volume and rough filament delta.

## Splitting for the bed or for color

- If a model exceeds 295 mm in any axis, **split it** into bed-sized chunks and note where to glue
  or add registration pins/keys. Cut along the least-visible plane.
- For **CFS multi-color**, split a single mesh into per-color bodies (or guide the user to paint
  colors in-slicer) and export a **3MF** that preserves the parts.

## Generating geometry from scratch

The user may not have a file at all. Use `trimesh.creation` / numpy to build parametric parts:
boxes, cylinders, tubes, plates with holes, simple brackets, name/text plates, stands, jigs,
templates. Always export
print-ready and run `info` to confirm it's watertight and fits the bed.

## Safety / correctness checks before declaring "print-ready"

- Watertight + consistent normals.
- Fits 295³ mm.
- No features < 0.8 mm that should be solid.
- Sensible orientation (and a preview rendered).
- New file saved with a descriptive name; original preserved.
