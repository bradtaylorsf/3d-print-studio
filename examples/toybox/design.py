#!/usr/bin/env python3
"""design.py — Toybox dragon, from refs/gen_a_friendly_dragon.png.

A chunky friendly dragon for young kids: one fat egg body with the
head blended straight onto it, a cream belly oval, two big eyes, two horns and
a little crest, a row of rounded back plates, stubby arms with claw tips, two
feet with toe claws, and a tail that curves down and lands on the bed.

Four colour bodies, exported to parts/ so each can be painted separately:

    body_green      body + head + arms + feet + tail
    belly_cream     the belly oval, a flush inlay (not a bump)
    horns_spikes    horns, crest, back plates, tail plates, toe + arm claws
    eyes_black      the two eyes, also flush inlays

Print notes baked into the geometry
-----------------------------------
  * FLARE_LIMIT is the whole design rule: nothing may grow outward as it rises
    faster than 45 deg. The body silhouette, the feet, the toe claws and the
    tail tip are all revolves/spheres cut at the bed with centre height under
    0.707 * radius, which is exactly that limit; the tail is a tube whose
    steepest segment leans 42 deg; the back plates are flat fins whose lower
    edge leans FIN_LEAN. So it prints on the K2 in PLA with NO supports.
  * Back plates are FINS, not cones. A cone pointing up-and-back has to lean
    ~58 deg to clear the body at all, and a leaning tube's underside overhangs
    by exactly its lean. A flat fin in the YZ plane has vertical sides and one
    sloped lower edge, so it can reach out as far as it likes at 43 deg.
  * No horizontal snout. The reference's front views have a round head and no
    muzzle, and a muzzle is the one feature on a head this shape that would
    have to be supported. Two big eyes carry the face instead.
  * Belly and eyes are flush colour INLAYS, cut out of the body by a shape
    closed with a flat plane behind, so each is a slab several mm thick — not
    a lens that tapers to nothing at its rim.
  * The tail is a third foot: it lands on the bed as a flat pad, so the
    footprint is a wide tripod and the toy cannot rock.
  * Nothing is pointy. The thinnest tip is a 3.6 mm rounded fin edge.

Run:  .venv/bin/python projects/toybox/design.py
"""
import json
import os

import numpy as np
import shapely.geometry as sg
import trimesh
from scipy.interpolate import PchipInterpolator
from trimesh.creation import box, cylinder, extrude_polygon, icosphere, revolve
from trimesh.transformations import rotation_matrix, translation_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = "manifold"
SECT = 80                 # revolve segments
TUBE_SECT = 28            # loft segments for arms / tail / horns
MIN_FEATURE = 1.2         # mm — nothing on the model may be thinner
FLARE_LIMIT = 45.0        # deg from vertical — the no-support budget

# ---- body + head: one revolved silhouette --------------------------------
# (z, radius). Bottom-up: base disc, belly bulge, soft waist at the neck, head
# bulge, crown. Every rise in radius is <= 45 deg (dr/dz <= 1).
BODY_PTS = [(0.0, 17.0), (3.0, 18.6), (6.0, 20.0), (10.0, 21.4), (14.0, 22.3),
            (18.0, 22.8), (22.0, 22.9), (26.0, 22.6), (30.0, 21.9),
            (34.0, 21.0), (37.0, 20.2), (40.0, 20.0), (43.0, 20.4),
            (46.0, 21.2), (50.0, 22.2), (54.0, 22.8), (58.0, 22.9),
            (61.0, 22.4), (64.0, 21.2), (66.0, 19.8), (68.0, 17.6),
            (70.0, 14.4), (71.5, 11.0), (72.5, 7.5), (73.2, 4.0),
            (73.6, 0.0)]
CROWN_Z = BODY_PTS[-1][0]

# ---- feet ----------------------------------------------------------------
FOOT_C = (11.0, -14.0, 4.0)   # mirrored in x; sphere cut flat at the bed
FOOT_R = 9.5
TOE_R = 4.2
TOE_Z = 2.6                   # <= 0.707 * TOE_R keeps the pad edge under 45 deg
TOES = [(6.5, -21.5), (15.5, -19.5)]   # mirrored in x; kept apart so they only
                                       # meet through the foot, never tangentially

# ---- arms ----------------------------------------------------------------
# hang down-and-out, then taper to a small rounded claw so the only ceiling on
# the model is a 5 mm dome
ARM_PATH = [(15.0, -4.0, 41.0), (19.0, -5.0, 35.0), (21.5, -6.0, 29.0),
            (22.5, -6.5, 24.0), (23.0, -6.5, 20.0)]
ARM_R = [7.5, 6.8, 5.8, 4.4, 2.4]
ARM_CLAW_Z = 26.0             # below this the arm is the accent colour

# ---- tail ----------------------------------------------------------------
# root buried in the body, then a monotone down-and-back sweep; no segment
# leans more than 43 deg, and the tip is a sphere cut flat on the bed
TAIL_PATH = [(0.0, 12.0, 32.0), (0.0, 17.5, 26.0), (0.0, 23.0, 20.0),
             (0.0, 27.5, 14.0), (0.0, 31.0, 8.0), (0.0, 33.0, 3.2)]
TAIL_R = [9.2, 8.5, 7.4, 6.3, 5.4, 4.8]

# ---- horns + crest -------------------------------------------------------
HORN_PATH = [(8.5, 3.0, 58.0), (10.0, 4.5, 70.0), (11.5, 6.0, 80.0)]
HORN_R = [4.4, 3.4, 2.3]
CREST_PATH = [(0.0, 2.0, 60.0), (0.0, 4.0, 71.0), (0.0, 6.0, 79.0)]
CREST_R = [4.6, 3.8, 2.6]
CREST_T = 3.6                 # the crest is a flat fin, this thick

# ---- back + tail plates (fins) -------------------------------------------
FIN_T = 4.0                   # plate thickness
FIN_ROUND = 1.8               # corner/tip radius -> 3.6 mm blunt tip
FIN_LEAN = 43.0               # deg from vertical for the lower edge
SPINE_Z = [24.0, 30.0, 36.0, 42.0, 48.0, 54.0, 60.0]
SPINE_L = 13.0
TAIL_FIN_AT = [1, 2, 3]       # indices into TAIL_PATH
TAIL_FIN_L = 10.0

# ---- belly inlay (cream) -------------------------------------------------
BELLY_A = 12.0            # half width in x
BELLY_C = 13.5            # half height in z
BELLY_Z = 26.0            # centre height
BELLY_Y = -15.0           # flat back face of the inlay

# ---- eye inlays (black) --------------------------------------------------
EYE_R = 4.0
EYE_X = 9.0
EYE_Z = 58.0
EYE_Y = -15.0             # flat back face of the inlay

COLORS = {
    "body_green": "#5FBF57",
    "belly_cream": "#F5E7B2",
    "horns_spikes": "#A0522D",
    "eyes_black": "#1E1E1E",
}

DEBRIS = []               # boolean slivers dropped by clean(), reported at the end

_r_body = PchipInterpolator(*zip(*BODY_PTS))


def r_body(z):
    """Body radius at height z, clamped outside the silhouette."""
    return float(np.clip(_r_body(np.clip(z, 0.0, CROWN_Z)), 0.0, None))


# ---------------------------------------------------------------- geometry
def loft(pts, radii, sections=TUBE_SECT):
    """Watertight tube through pts with per-point radii (parallel transport)."""
    pts = np.asarray(pts, dtype=float)
    radii = np.asarray(radii, dtype=float)
    n = len(pts)
    tan = np.zeros((n, 3))
    tan[1:-1] = pts[2:] - pts[:-2]
    tan[0] = pts[1] - pts[0]
    tan[-1] = pts[-1] - pts[-2]
    tan /= np.linalg.norm(tan, axis=1)[:, None]

    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(tan[0] @ ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    u0 = np.cross(tan[0], ref)
    frames = [u0 / np.linalg.norm(u0)]
    for i in range(1, n):
        v = frames[-1] - tan[i] * float(frames[-1] @ tan[i])
        if np.linalg.norm(v) < 1e-9:
            v = np.cross(tan[i], ref)
        frames.append(v / np.linalg.norm(v))
    u = np.array(frames)
    w = np.cross(tan, u)

    ang = np.linspace(0.0, 2.0 * np.pi, sections, endpoint=False)
    cos_a, sin_a = np.cos(ang)[:, None], np.sin(ang)[:, None]
    verts = np.vstack([pts[i] + radii[i] * (cos_a * u[i] + sin_a * w[i])
                       for i in range(n)])

    faces = []
    for i in range(n - 1):
        a, b = i * sections, (i + 1) * sections
        for j in range(sections):
            k = (j + 1) % sections
            faces.append([a + j, b + j, b + k])
            faces.append([a + j, b + k, a + k])
    c0, c1 = len(verts), len(verts) + 1
    verts = np.vstack([verts, pts[0][None, :], pts[-1][None, :]])
    last = (n - 1) * sections
    for j in range(sections):
        k = (j + 1) % sections
        faces.append([c0, k, j])
        faces.append([c1, last + j, last + k])

    m = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=True)
    m.fix_normals()
    return m


def tube(pts, radii):
    """Lofted tube finished with a dome instead of a flat disc."""
    pts = [np.asarray(p, dtype=float) for p in pts]
    radii = list(radii)
    d = pts[-1] - pts[-2]
    d /= np.linalg.norm(d)
    centre, r = pts[-1].copy(), radii[-1]
    for th in np.radians([22.0, 44.0, 64.0, 80.0]):
        pts.append(centre + d * r * np.sin(th))
        radii.append(r * np.cos(th))
    return loft(pts, radii)


def fin(attach_yz, length, thick=FIN_T, lean=FIN_LEAN, round_r=FIN_ROUND):
    """A flat plate in the x=0 plane, leaning back out of the surface.

    The lower edge runs at `lean` deg from vertical (the whole overhang budget
    for this feature); the two base corners sit `d` mm inside the surface so
    they never become exterior geometry.
    """
    y0, z0 = attach_yz
    a, c, b = 0.50 * length, 0.62 * length, 0.62 * length
    d = np.tan(np.radians(lean)) * (a + c) - b
    poly = sg.Polygon([(y0 - d, z0 - a),
                       (y0 + b, z0 + c),
                       (y0 - d, z0 + 0.30 * length)])
    poly = poly.buffer(round_r, join_style=1, resolution=10)
    m = extrude_polygon(poly, thick)
    m.apply_transform(np.array([[0.0, 0.0, 1.0, -thick / 2.0],
                                [1.0, 0.0, 0.0, 0.0],
                                [0.0, 1.0, 0.0, 0.0],
                                [0.0, 0.0, 0.0, 1.0]]))
    return m


def mirror_x(mesh):
    m = mesh.copy()
    m.apply_scale([-1.0, 1.0, 1.0])
    m.fix_normals()
    return m


def ball(centre, radius, subdiv=3):
    m = icosphere(subdivisions=subdiv, radius=radius)
    m.apply_translation(centre)
    return m


def body_mesh():
    zs = np.arange(0.0, CROWN_Z, 0.4)
    line = [(0.0, 0.0)]
    line += [(r_body(float(z)), float(z)) for z in zs]
    line += [(0.0, CROWN_Z)]
    return revolve(np.asarray(line), sections=SECT)


def belly_cutter():
    c = cylinder(radius=1.0, height=200.0, sections=96)
    c.apply_scale([BELLY_A, BELLY_C, 1.0])
    c.apply_transform(rotation_matrix(np.pi / 2.0, [1, 0, 0]))
    c.apply_translation([0.0, 0.0, BELLY_Z])
    front = box(extents=[300.0, 200.0, 300.0])
    front.apply_translation([0.0, BELLY_Y - 100.0, 100.0])
    return trimesh.boolean.intersection([c, front], engine=ENG)


def eye_cutter():
    out = []
    for sx in (-1.0, 1.0):
        c = cylinder(radius=EYE_R, height=120.0, sections=64)
        c.apply_transform(rotation_matrix(np.pi / 2.0, [1, 0, 0]))
        c.apply_translation([sx * EYE_X, 0.0, EYE_Z])
        out.append(c)
    front = box(extents=[300.0, 200.0, 300.0])
    front.apply_translation([0.0, EYE_Y - 100.0, 100.0])
    return trimesh.boolean.intersection(
        [trimesh.boolean.union(out, engine=ENG), front], engine=ENG)


def clean(mesh, label):
    """Drop the sliver triangles booleans leave at tangential intersections."""
    m = mesh.copy()
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    keep, dropped_faces, dropped_vol = [], 0, 0.0
    for c in m.split(only_watertight=False):
        if c.is_watertight and abs(c.volume) > 1e-3:
            keep.append(c)
        else:
            dropped_faces += len(c.faces)
            dropped_vol += abs(c.volume)
    if dropped_faces:
        DEBRIS.append((label, dropped_faces, len(m.faces), dropped_vol))
    out = trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]
    out.merge_vertices()
    return out


def build():
    # --- green mass -------------------------------------------------------
    arm = tube(ARM_PATH, ARM_R)
    tail = tube(TAIL_PATH, TAIL_R)
    green_parts = [body_mesh(), arm, mirror_x(arm), tail]
    for sx in (-1.0, 1.0):
        green_parts.append(ball((sx * FOOT_C[0], FOOT_C[1], FOOT_C[2]), FOOT_R))

    # --- accent mass ------------------------------------------------------
    horn = tube(HORN_PATH, HORN_R)
    accent = [horn, mirror_x(horn)]

    crest = tube(CREST_PATH, CREST_R)
    slab = box(extents=[CREST_T, 200.0, 200.0])
    slab.apply_translation([0.0, 0.0, 60.0])
    accent.append(trimesh.boolean.intersection([crest, slab], engine=ENG))

    for z in SPINE_Z:
        accent.append(fin((r_body(z), z), SPINE_L))
    for i in TAIL_FIN_AT:
        _, py, pz = TAIL_PATH[i]
        r = TAIL_R[i]
        accent.append(fin((py + 0.55 * r, pz + 0.55 * r), TAIL_FIN_L))

    for sx in (-1.0, 1.0):
        for tx, ty in TOES:
            accent.append(ball((sx * tx, ty, TOE_Z), TOE_R))

    accent_solid = trimesh.boolean.union(accent, engine=ENG)

    # arm tips take the accent colour; they are already inside the green mass
    claw_box = box(extents=[300.0, 300.0, 200.0])
    claw_box.apply_translation([0.0, 0.0, ARM_CLAW_Z - 100.0])
    claws = trimesh.boolean.intersection(
        [trimesh.boolean.union([arm, mirror_x(arm)], engine=ENG), claw_box],
        engine=ENG)
    accent_cut = trimesh.boolean.union([accent_solid, claws], engine=ENG)

    # --- one solid, flat on the bed --------------------------------------
    solid = trimesh.boolean.union(green_parts + [accent_solid], engine=ENG)
    bed = box(extents=[400.0, 400.0, 400.0])
    bed.apply_transform(translation_matrix([0.0, 0.0, 200.0]))
    solid = clean(trimesh.boolean.intersection([solid, bed], engine=ENG), "model")

    # --- split into colour bodies ----------------------------------------
    belly_cut = belly_cutter()
    eyes_cut = eye_cutter()
    parts = {
        "belly_cream": trimesh.boolean.intersection([solid, belly_cut], engine=ENG),
        "eyes_black": trimesh.boolean.intersection([solid, eyes_cut], engine=ENG),
        "horns_spikes": trimesh.boolean.intersection([solid, accent_cut], engine=ENG),
        "body_green": trimesh.boolean.difference(
            [solid, accent_cut, belly_cut, eyes_cut], engine=ENG),
    }
    order = ["body_green", "belly_cream", "horns_spikes", "eyes_black"]
    return solid, {k: clean(parts[k], k) for k in order}


# ------------------------------------------------------------------ checks
def overhang_report(mesh, limit=FLARE_LIMIT, bed=0.6):
    n = mesh.face_normals
    ang = 90.0 - np.degrees(np.arccos(np.clip(-n[:, 2], -1.0, 1.0)))
    zmax = mesh.vertices[mesh.faces][:, :, 2].max(axis=1)
    above = zmax > bed
    bad = (ang > limit) & above
    return float(mesh.area_faces[bad].sum()), float(ang[above].max())


def max_flare():
    """Steepest outward flare of the revolved silhouette, deg from vertical."""
    z = np.linspace(0.0, CROWN_Z - 0.01, 4000)
    dr = np.gradient(_r_body(z), z)
    return float(np.degrees(np.arctan(dr.max())))


def inlay_min_thickness(a, c, z0, y_cut, x0=0.0):
    """Thinnest point of a plane-backed inlay cut into the revolved body."""
    ang = np.linspace(0.0, 2.0 * np.pi, 240)
    worst = 1e9
    for f in np.linspace(0.0, 1.0, 60):
        for x, z in zip(x0 + f * a * np.cos(ang), z0 + f * c * np.sin(ang)):
            rad = r_body(float(z))
            if abs(x) >= rad:
                return -1.0
            worst = min(worst, float(np.sqrt(rad ** 2 - x ** 2) + y_cut))
    return worst


def main():
    pdir = os.path.join(HERE, "parts")
    os.makedirs(pdir, exist_ok=True)

    whole, parts = build()
    bad = []

    whole.export(os.path.join(HERE, "model.stl"))
    for name, m in parts.items():
        m.export(os.path.join(pdir, f"{name}.stl"))
    with open(os.path.join(pdir, "parts.json"), "w") as fh:
        json.dump({f"{n}.stl": COLORS[n] for n in parts}, fh, indent=2)

    # re-read from disk: manifold calls meshes watertight even when coincident
    # vertices are left unmerged, only a round trip catches that
    print(f"{'file':<26} {'size mm':>22} {'cm3':>7} {'shells':>7}  watertight")
    check = [("model.stl", os.path.join(HERE, "model.stl"))]
    check += [(f"{n}.stl", os.path.join(pdir, f"{n}.stl")) for n in parts]
    vols = {}
    for label, path in check:
        m = trimesh.load(path)
        e = np.sort(m.edges, axis=1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        shells = len(m.split(only_watertight=False))
        wt = m.is_watertight and m.is_winding_consistent and bool((cnt == 2).all())
        vols[label] = m.volume
        print(f"{label:<26} {m.extents[0]:6.1f} x{m.extents[1]:6.1f} x"
              f"{m.extents[2]:6.1f} {m.volume / 1000:7.1f} {shells:7d}  "
              f"{'YES' if wt else 'NO'}")
        if not wt:
            bad.append(f"{label} not watertight")
        if m.bounds[0][2] < -1e-6:
            bad.append(f"{label} dips below the bed")

    split = sum(v for k, v in vols.items() if k != "model.stl")
    err = abs(split - vols["model.stl"]) / vols["model.stl"]
    area, worst = overhang_report(trimesh.load(os.path.join(HERE, "model.stl")))
    belly_t = inlay_min_thickness(BELLY_A, BELLY_C, BELLY_Z, BELLY_Y)
    eye_t = inlay_min_thickness(EYE_R, EYE_R, EYE_Z, EYE_Y, x0=EYE_X)

    print()
    print(f"colour bodies    {len(parts)}   tris {len(whole.faces):,}")
    print(f"assembled        {whole.extents[0]:.1f} x {whole.extents[1]:.1f} x "
          f"{whole.extents[2]:.1f} mm   (K2 envelope 255^3)")
    print(f"parts vs whole   {err * 100:.3f}% volume error (parts tile it)")
    print(f"body flare       {max_flare():.1f} deg from vertical (budget "
          f"{FLARE_LIMIT:.0f})")
    print(f"overhang         worst {worst:.1f} deg, {area:.1f} mm2 over "
          f"{FLARE_LIMIT:.0f} deg above the bed")
    thin = [("belly inlay", belly_t), ("eye inlay", eye_t),
            ("fin plate", FIN_T), ("fin tip", 2 * FIN_ROUND),
            ("horn tip", 2 * HORN_R[-1]), ("crest fin", CREST_T),
            ("arm claw tip", 2 * ARM_R[-1])]
    print("thin features    " + ", ".join(f"{k} {v:.1f}" for k, v in thin)
          + f"   (min {MIN_FEATURE})")
    if min(v for _, v in thin) < MIN_FEATURE:
        bad.append("a feature is under the minimum thickness")
    print(f"footprint        body disc d{2 * r_body(0.0):.0f} + 2 feet d"
          f"{2 * np.sqrt(FOOT_R ** 2 - FOOT_C[2] ** 2):.0f} + 4 toes + tail pad")
    print(f"filament         {vols['model.stl'] / 1000:.0f} cm3 solid "
          f"(~{vols['model.stl'] / 1000 * 1.24:.0f} g at 100%)")
    for label, nf, tot, vol in DEBRIS:
        print(f"cleaned          {label}: dropped {nf} sliver tris of {tot} "
              f"({vol:.3f} mm3)")
        if nf > 0.01 * tot:
            bad.append(f"{label} lost {nf} faces to cleanup")
    if err > 0.002:
        bad.append(f"parts do not tile the model ({err * 100:.2f}%)")
    if not 60.0 <= max(whole.extents) <= 90.0:
        bad.append("largest dimension outside the 60-90 mm brief")
    for x in bad:
        print("  !! " + x)


if __name__ == "__main__":
    main()
