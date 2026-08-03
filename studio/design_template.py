#!/usr/bin/env python3
"""design.py — parametric source for projects/<NAME>/.

Copy this into a project folder as design.py, adjust, then run:

    .venv/bin/python projects/<NAME>/design.py

Every run rewrites model.stl next to this file; the studio viewer
(http://localhost:8765/?project=<NAME>) hot-reloads it within ~2 s.

Conventions:
- All dimensions in mm, parameters grouped at the top.
- Keep the part in bed coordinates: XY footprint positive, Z >= 0
  (use the layflat step at the bottom).
- Multi-color: export several meshes into parts/<piece>.stl instead of
  model.stl, and optionally write parts.json = {"<piece>.stl": "#rrggbb"}.
"""
import os
import trimesh
import numpy as np

# ---- parameters (mm) ------------------------------------------------------
WIDTH = 40.0
DEPTH = 20.0
HEIGHT = 12.0
HOLE_D = 5.0
CORNER_R = 3.0   # unused in the starter shape; keep params even when unused

# ---- build ----------------------------------------------------------------
def build() -> trimesh.Trimesh:
    body = trimesh.creation.box(extents=[WIDTH, DEPTH, HEIGHT])
    hole = trimesh.creation.cylinder(radius=HOLE_D / 2, height=HEIGHT * 2)
    # boolean ops use the manifold3d engine (installed in .venv)
    part = body.difference(hole)
    return part

# ---- export ---------------------------------------------------------------
def export(m: trimesh.Trimesh):
    here = os.path.dirname(os.path.abspath(__file__))
    # drop onto the bed: min corner at origin, Z = 0
    m.apply_translation(-m.bounds[0])
    out = os.path.join(here, "model.stl")
    m.export(out)
    ext = m.bounds[1] - m.bounds[0]
    print(f"model.stl  {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm  "
          f"tris={len(m.faces):,}  watertight={m.is_watertight}")
    if not m.is_watertight:
        print(">> NOT WATERTIGHT — fix before printing (skills/stl-prep).")


if __name__ == "__main__":
    export(build())
