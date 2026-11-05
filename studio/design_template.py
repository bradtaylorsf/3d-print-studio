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
- Fit: the export checks the printer's design envelope from
  studio.config.json (255 x 255 x 255 mm on the shipped Creality K2 default).
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
def envelope_mm():
    """The configured printer's design envelope (bed minus margin), from the
    repo's studio/config.py — found above this file, or above the working
    directory (a projects folder kept outside the repo; builds run from the
    repo root). Loaded by path, so a stray `config` module can't stand in.
    255³ (the shipped K2 default) when it can't be found."""
    import importlib.util
    for start in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        d = start
        while True:
            cand = os.path.join(d, "studio", "config.py")
            if os.path.isfile(cand):
                try:
                    spec = importlib.util.spec_from_file_location("studio_config", cand)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    return mod.envelope_mm(mod.get())
                except Exception:
                    break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return [255.0, 255.0, 255.0]


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
    env = envelope_mm()
    if any(e > v for e, v in zip(ext, env)):
        print(f">> BIGGER THAN THE PRINTER ENVELOPE "
              f"({env[0]:g} x {env[1]:g} x {env[2]:g} mm) — scale or split it.")


if __name__ == "__main__":
    export(build())
