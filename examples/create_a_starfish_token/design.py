#!/usr/bin/env python3
"""design.py — chunky happy-star token for projects/create_a_starfish_token/.

Reference: refs/gen_create_a_starfish_token_2.png — a friendly rounded 5-point
star sticker: white border, black outline, yellow fill, two dot eyes, a smile.

Rerun any time, from the repo root:
    .venv/bin/python projects/create_a_starfish_token/design.py

Three parts (paintable in the studio, printable single-plate multi-color on
the K2's CFS): white backing, black details (outline + eyes + mouth), yellow
fill. All are flat extrusions stacked in Z — no overhangs, no supports needed.
"""
import json
import os

import numpy as np
import trimesh
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

# ---- parameters (mm) -------------------------------------------------------
N_POINTS = 5              # star points
OUTER_RADIUS = 41.0        # star tip radius (before white border), before rounding
INNER_RADIUS = 17.0        # star valley radius -> short, fat, friendly points
TIP_ROUND = 3.5            # "opening" radius that blunts sharp tips
VALLEY_ROUND = 3.0         # "closing" radius that fills sharp valley notches

BORDER_WIDTH = 4.0         # white sticker-style border, buffered outward
OUTLINE_WIDTH = 4.5        # black ring width, buffered inward from star edge

BASE_THICKNESS = 4.0       # white backing slab: Z 0 -> BASE_THICKNESS
TOP_THICKNESS = 2.2        # black/yellow face layer thickness on top of base

EYE_RADIUS = 3.6
EYE_OFFSET_X = 9.2         # +/- from center
EYE_OFFSET_Y = 3.5         # above center
MOUTH_HALF_WIDTH = 8.0     # smile arc half-span
MOUTH_DROP = 6.3           # how far the smile dips below its chord
MOUTH_Y = -5.8             # smile center height (below center)
MOUTH_STROKE = 2.3         # smile line thickness (radius of the buffered stroke)

# ---- helpers ----------------------------------------------------------------
def star_polygon(n, r_outer, r_inner):
    """Classic sharp star polygon, tip pointing +Y, alternating outer/inner verts."""
    pts = []
    for i in range(n * 2):
        ang = np.pi / 2 + i * np.pi / n
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((r * np.cos(ang), r * np.sin(ang)))
    return Polygon(pts)


def chunky_star(n, r_outer, r_inner, tip_round, valley_round):
    """Sharp star -> blunt tips (morphological opening) -> filled valleys (closing)."""
    star = star_polygon(n, r_outer, r_inner)
    opened = star.buffer(-tip_round, join_style="round").buffer(tip_round, join_style="round")
    closed = opened.buffer(valley_round, join_style="round").buffer(-valley_round, join_style="round")
    return closed


def smile_polygon():
    """A thick, gently curved smile arc as a buffered polyline."""
    xs = np.linspace(-MOUTH_HALF_WIDTH, MOUTH_HALF_WIDTH, 15)
    # downward-opening arc (smile): dips by MOUTH_DROP at center
    ys = MOUTH_Y - MOUTH_DROP * (1 - (xs / MOUTH_HALF_WIDTH) ** 2)
    line = LineString(list(zip(xs, ys)))
    return line.buffer(MOUTH_STROKE, cap_style="round", join_style="round")


def extrude(poly, z0, z1):
    geoms = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
    meshes = []
    for g in geoms:
        if g.is_empty or g.area < 1e-6:
            continue
        m = trimesh.creation.extrude_polygon(g, height=(z1 - z0))
        meshes.append(m)
    mesh = trimesh.util.concatenate(meshes)
    mesh.apply_translation([0, 0, z0])
    return mesh


# ---- build ------------------------------------------------------------------
def build():
    star = chunky_star(N_POINTS, OUTER_RADIUS, INNER_RADIUS, TIP_ROUND, VALLEY_ROUND)
    white_shape = star.buffer(BORDER_WIDTH, join_style="round")
    inner_fill = star.buffer(-OUTLINE_WIDTH, join_style="round")

    eye_l = Point(-EYE_OFFSET_X, EYE_OFFSET_Y).buffer(EYE_RADIUS)
    eye_r = Point(EYE_OFFSET_X, EYE_OFFSET_Y).buffer(EYE_RADIUS)
    mouth = smile_polygon()
    face_features = unary_union([eye_l, eye_r, mouth])

    black_shape = unary_union([star.difference(inner_fill), face_features])
    yellow_shape = inner_fill.difference(face_features)

    white_mesh = extrude(white_shape, 0.0, BASE_THICKNESS)
    black_mesh = extrude(black_shape, BASE_THICKNESS, BASE_THICKNESS + TOP_THICKNESS)
    yellow_mesh = extrude(yellow_shape, BASE_THICKNESS, BASE_THICKNESS + TOP_THICKNESS)

    return {
        "white": white_mesh,
        "black": black_mesh,
        "yellow": yellow_mesh,
    }


# ---- export -----------------------------------------------------------------
COLORS = {
    "white": "#f5f0e6",
    "black": "#1a1a1a",
    "yellow": "#f4cf5e",
}


def export(parts):
    here = os.path.dirname(os.path.abspath(__file__))

    # merged preview for model.stl / bbox reporting
    merged = trimesh.util.concatenate(list(parts.values()))
    shift = -merged.bounds[0]
    merged.apply_translation(shift)
    merged.export(os.path.join(here, "model.stl"))

    parts_dir = os.path.join(here, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    parts_json = {}
    for name, mesh in parts.items():
        m = mesh.copy()
        m.apply_translation(shift)
        fname = f"{name}.stl"
        m.export(os.path.join(parts_dir, fname))
        parts_json[fname] = COLORS[name]
        ext = m.bounds[1] - m.bounds[0]
        print(f"parts/{fname:12s} {ext[0]:5.1f} x {ext[1]:5.1f} x {ext[2]:4.1f} mm  "
              f"tris={len(m.faces):,}  watertight={m.is_watertight}")

    with open(os.path.join(parts_dir, "parts.json"), "w") as f:
        json.dump(parts_json, f, indent=2)

    ext = merged.bounds[1] - merged.bounds[0]
    print(f"model.stl (merged) {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm  "
          f"tris={len(merged.faces):,}  watertight={merged.is_watertight}")
    if not all(m.is_watertight for m in parts.values()):
        print(">> NOT ALL PARTS WATERTIGHT — fix before printing.")


if __name__ == "__main__":
    export(build())
