#!/usr/bin/env python3
"""chip_geometry.py — the token chip/coin contract, shared by make_chip.py and make_coin.py.

A token chip is a 28 mm round, chamfered disc with a flat face at Z = FACE and
raised art EMBOSS mm tall on top. A token board is a tray with round sockets the
chips drop into; a family can design its own board around these numbers. The
chips are deliberately wordless — a picture, not a label.

Why the numbers are what they are
---------------------------------
  Round chips    A hex chip has to be rotated to seat. Round drops in at any
                 angle, so a small child never has to aim.
  1.2 mm clear   Diametral clearance to the socket. Loose on purpose, plus a
                 1.5 mm chamfered lead-in, so the chip finds the hole by itself.
  2.4 mm proud   The chip stands proud of the socket by this much — enough for
                 small fingers to pinch it back out without a fingernail.
  6.05 mm face   Board and chip are the SAME height, so every raised feature in a
                 job starts at exactly one Z. That is what makes a two-colour job
                 a single filament change instead of twenty.
                 6.05 = 0.25 first layer + 29 x 0.20 — the change lands on the face.

Never change CHIP_D, FACE or EMBOSS to make one picture fit: every chip and
board already printed depends on them. Change the picture.
"""
import math

import numpy as np
import shapely.geometry as sg
import shapely.ops as so          # make_chip.py reaches this through `D.so`
import trimesh
from trimesh.creation import extrude_polygon

SECT = 64                 # revolve resolution

# ---- the single-colour-change contract ----------------------------------
# EVERYTHING raised in a job begins at Z = FACE. Nothing else may.
FACE = 6.05               # board top face AND chip top face
EMBOSS = 1.20             # raised height of the art -> second-colour band FACE..FACE+EMBOSS
LAYER_H = 0.20
FIRST_LAYER = 0.25

# ---- chip ----------------------------------------------------------------
CHIP_D = 28.0
CHIP_H = FACE
CHIP_CHAMFER = 0.6        # edge break so it is pleasant to hold

# ---- socket (for anyone building a board) --------------------------------
CLEAR = 1.2               # diametral clearance, chip -> socket
SOCKET_D = CHIP_D + CLEAR
SOCKET_DEPTH = 3.65       # leaves 2.4 mm of floor, and 2.4 mm of chip proud
LEAD_IN = 1.5             # chamfered mouth so the chip self-finds the hole


# --------------------------------------------------------------- motifs ---
def fit_centre(p, r):
    """Scale a motif so its largest dimension is 2r, then centre it on the origin."""
    x0, y0, x1, y1 = p.bounds
    k = (2 * r) / max(x1 - x0, y1 - y0)
    p = so.transform(lambda a, b, z=None: (a * k, b * k), p)
    x0, y0, x1, y1 = p.bounds
    return so.transform(
        lambda a, b, z=None: (a - (x0 + x1) / 2, b - (y0 + y1) / 2), p
    )


def motif_star(r=9.0, points=5, inner=0.42):
    v = []
    for i in range(points * 2):
        a = math.pi / 2 + i * math.pi / points
        rad = r if i % 2 == 0 else r * inner
        v.append((rad * math.cos(a), rad * math.sin(a)))
    return sg.Polygon(v)


def motif_heart(r=9.0):
    t = np.linspace(0, 2 * math.pi, 240)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    return fit_centre(sg.Polygon(np.column_stack([x, y])), r)


def motif_moon(r=9.0):
    full = sg.Point(0, 0).buffer(r, resolution=64)
    bite = sg.Point(r * 0.55, r * 0.30).buffer(r * 0.88, resolution=64)
    return full.difference(bite)


def motif_bolt(r=9.0):
    v = [(0.50, 1.00), (-0.50, 0.15), (0.05, 0.15), (-0.50, -1.00),
         (0.50, -0.15), (-0.05, -0.15)]
    return fit_centre(sg.Polygon(v), r * 0.95)


MOTIFS = {"star": motif_star, "heart": motif_heart, "moon": motif_moon, "bolt": motif_bolt}
CHIP_MOTIF = "star"


# ---------------------------------------------------------------- solids --
def extrude_multi(geom, height):
    """extrude_polygon, but tolerant of a MultiPolygon — i.e. of any art with
    more than one piece in it."""
    polys = list(geom.geoms) if isinstance(geom, sg.MultiPolygon) else [geom]
    return trimesh.util.concatenate(
        [extrude_polygon(p, height) for p in polys if not p.is_empty]
    )


def revolved(profile, sections=SECT):
    """profile: [(radius, z), ...] closed loop, revolved about Z."""
    return trimesh.creation.revolve(np.asarray(profile, dtype=float), sections=sections)


def socket_cutter(board_h=FACE):
    """One board socket: straight bore + chamfered mouth, running out through
    the top. Subtract it from a board body of height `board_h`."""
    r = SOCKET_D / 2.0
    z_floor = board_h - SOCKET_DEPTH
    return revolved([
        (0.0, z_floor),
        (r, z_floor),
        (r, board_h - LEAD_IN),
        (r + LEAD_IN, board_h),
        (r + LEAD_IN, board_h + 1.0),
        (0.0, board_h + 1.0),
    ])


def build_chip(motif=CHIP_MOTIF, relief=None, face=None, emboss=None):
    """A chip. `motif` names a built-in; `relief` overrides it with any shapely
    geometry already scaled in mm and centred on the origin — that is the hook
    make_chip.py uses to put a traced picture on a chip.

    `face`/`emboss` exist only so a chip-only job can be re-snapped to a
    different layer height. They MUST stay None for anything sharing a plate
    with a board, or the single-colour-change contract breaks.
    """
    h = FACE if face is None else face
    e = EMBOSS if emboss is None else emboss
    r = CHIP_D / 2.0
    body = revolved([
        (0.0, 0.0),
        (r - CHIP_CHAMFER, 0.0),
        (r, CHIP_CHAMFER),
        (r, h - CHIP_CHAMFER),
        (r - CHIP_CHAMFER, h),
        (0.0, h),
    ])
    geom = MOTIFS[motif](r=CHIP_D * 0.32) if relief is None else relief
    top = extrude_multi(geom, e)
    top.apply_translation([0, 0, h])
    out = trimesh.util.concatenate([body, top])
    out.merge_vertices()
    return out


def change_layer(face=None, layer_h=None, first_layer=None):
    """Which layer the filament change goes after, for a given layer height.
    Returns (layer_index, exact_z, is_exact)."""
    h = FACE if face is None else face
    lh = LAYER_H if layer_h is None else layer_h
    fl = FIRST_LAYER if first_layer is None else first_layer
    n = int(round((h - fl) / lh)) + 1
    z = fl + (n - 1) * lh
    return n, z, abs(z - h) < 1e-6


def snap_face(layer_h, first_layer=None, target=None):
    """Nearest chip height AT OR ABOVE `target` that lands exactly on a layer
    boundary for this layer height. A chip-only job can use this to print
    faster without the colour change drifting off the face."""
    fl = FIRST_LAYER if first_layer is None else first_layer
    t = FACE if target is None else target
    n = math.ceil((t - fl) / layer_h)
    return round(fl + n * layer_h, 4)


if __name__ == "__main__":
    chip = build_chip()
    n, z, exact = change_layer()
    print(f"token chip  {chip.extents[0]:.1f} x {chip.extents[1]:.1f} x {chip.extents[2]:.2f} mm"
          f"   watertight={chip.is_watertight}   colour change after layer {n} (Z {z:.2f})")
