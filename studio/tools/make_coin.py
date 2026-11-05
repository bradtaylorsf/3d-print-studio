#!/usr/bin/env python3
"""make_coin.py — image -> multi-colour snap-in token coin. SECONDS, not minutes.

    .venv/bin/python studio/tools/make_coin.py IMAGE --name dragon --out <project dir>

No AI in the loop: the image is traced deterministically. The subject is cut
off the background, its colours are clustered into up to 4 flat regions, and
each region becomes its own relief part on a coin body that fits a token-board
socket (all dimensions imported from chip_geometry.py — never redefined here).

Output (a project folder, ready for the studio and the CFS):
    parts/coin_body.stl        the coin — kid paints it any colour
    parts/coin_c1..c4.stl      one part per traced colour region
    parts/parts.json           display colours lifted FROM THE IMAGE
    model.stl                  merged preview
    final/token_coin_<name>_28mm.stl

The studio's per-part painting then IS the colour picker: tap a colour, tap a
region. Up to 4 filaments total on the CFS (body + 3 regions is the sweet
spot; a 4-region image leaves the body sharing a slot with one region).
"""
import argparse
import os
import sys

import cv2
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chip_geometry as D                                    # noqa: E402
import make_chip as MC                                       # noqa: E402

MAX_COLORS = 4
DARK_T = 96        # luminance below this inside the subject = linework
LINE_GROW = 0.28   # mm of dilation that makes hairline art printable (0.45 ate dense webs)
# Linework is a first-class layer, extracted BEFORE colour clustering and
# dilated to printable width BEFORE anything else claims space — k-means plus
# the generic per-region clean() reduced a superhero's web pattern to dots: the thin
# lines were grown to printable width and then clipped straight back wherever
# they had grown into the already-placed red fill (which is everywhere, for
# lines that live inside a fill). Same approach as the board characters'
# faces, which print correctly.


def cluster_colors(path, invert=False, k=MAX_COLORS):
    """Foreground mask (reusing make_chip's logic) + k-means colour clusters
    inside it. Returns list of (mask, hex) largest-first, in make_chip's
    normalised WORK_PX space."""
    # fill=True: enclosed background-coloured pockets (the eye, the mouth) are
    # regions of the subject on a coin, not holes through it.
    raw_fg, _ = MC.load_mask(path, invert, fill=True)   # normalised WORK_PX foreground

    # The colour image needs the SAME crop/pad/resize load_mask applied, so
    # take the subject bbox from the same original-size mask and repeat it.
    img = cv2.imread(path, cv2.IMREAD_COLOR)                 # BGR
    omask, _ = MC.raw_subject(path, invert, fill=True)
    ys, xs = np.where(omask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = img[y0:y1, x0:x1] if img is not None else None
    side = max(crop.shape[:2])
    pad = np.zeros((side, side, 3), np.uint8)
    oy, ox = (side - crop.shape[0]) // 2, (side - crop.shape[1]) // 2
    pad[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
    color = cv2.resize(pad, (MC.WORK_PX, MC.WORK_PX), interpolation=cv2.INTER_AREA)

    out = []
    # 1) dark linework: its own layer, pre-grown to printable width. It is
    #    placed FIRST in build_coin, so the fills are carved around it.
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    dark = (gray < DARK_T) & raw_fg
    cluster_fg = raw_fg
    if dark.sum() > 0.02 * raw_fg.sum():
        px_per_mm = MC.WORK_PX / MC.ART_D
        grown = cv2.dilate(dark.astype(np.uint8),
                           MC.disc(LINE_GROW * px_per_mm)).astype(bool) & raw_fg
        b, g, r = [int(v) for v in np.median(color[dark], axis=0)]
        out.append((grown, "#%02x%02x%02x" % (r, g, b)))
        cluster_fg = raw_fg & ~dark       # cluster colours on non-line pixels only
        k -= 1
    has_line = bool(out)

    # 2) the remaining flat colours
    px = color[cluster_fg]                                    # Nx3 BGR inside subject
    if len(px) < 50:
        if out:
            return out, has_line
        raise SystemExit("subject too small to trace")
    k = min(k, max(1, len(np.unique(px.reshape(-1, 3), axis=0))))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
    _, labels, centers = cv2.kmeans(px.astype(np.float32), k, None, crit, 4,
                                    cv2.KMEANS_PP_CENTERS)
    lab_img = np.full(raw_fg.shape, -1, np.int32)
    lab_img[cluster_fg] = labels.ravel()

    fills = []
    for i in range(k):
        m = lab_img == i
        if not m.any():
            continue
        b, g, r = centers[i]
        fills.append((m, "#%02x%02x%02x" % (int(r), int(g), int(b)), int(m.sum())))
    # smallest fill first: small features (eyes) claim their space before the
    # big background fill sweeps in
    fills.sort(key=lambda t: t[2])
    return out + [(m, hx) for m, hx, _ in fills], has_line


def build_coin(image, invert=False):
    """Returns (body_mesh, [(region_mesh, hex), ...], report_lines)."""
    mm_per_px = MC.ART_D / MC.WORK_PX
    regions, has_line = cluster_colors(image, invert)
    report = []

    # bare coin body — same profile the chips use, no relief
    r = D.CHIP_D / 2.0
    body = D.revolved([
        (0.0, 0.0), (r - D.CHIP_CHAMFER, 0.0), (r, D.CHIP_CHAMFER),
        (r, D.CHIP_H - D.CHIP_CHAMFER), (r - D.CHIP_CHAMFER, D.CHIP_H), (0.0, D.CHIP_H),
    ])
    body.merge_vertices()

    def tidy(mask, min_mm2=0.5):
        # keep every piece bigger than min_mm2 — a fill carved into many web
        # cells by the linework is DOZENS of small pieces, and clean()'s
        # keep-6-specks rule threw most of its red cells away
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        px_area = mm_per_px * mm_per_px
        keep = [i for i in range(1, n)
                if stats[i, cv2.CC_STAT_AREA] * px_area >= min_mm2]
        return np.isin(lab, keep) if keep else np.zeros_like(mask)

    placed = np.zeros((MC.WORK_PX, MC.WORK_PX), bool)
    parts = []
    for idx, (mask, hexcol) in enumerate(regions):
        m0 = mask & ~placed
        if not m0.any():
            continue
        if not has_line and MC.thin_fraction(m0, mm_per_px) > MC.THIN_TOL:
            # no linework layer and genuinely thin art: grow it printable.
            # WITH a linework layer, fills are cell fragments BOUNDED by the
            # lines — clean()'s despeckle threw most of them away and growth
            # cannot go anywhere; tidy() below is all they need.
            try:
                m, rep = MC.clean(m0, mm_per_px)
            except SystemExit:
                report.append(f"  region {idx + 1} {hexcol}: dropped (too small)")
                continue
            m = m & ~placed                                   # growth may not steal space
        else:
            # chunky already (pre-grown linework, or fill cells between lines)
            m = tidy(m0)
            rep = {"coverage": float(m.mean()), "thickened": 0.0}
        if not m.any():
            report.append(f"  region {idx + 1} {hexcol}: dropped (too small)")
            continue
        placed |= m
        try:
            geom = MC.mask_to_polygon(m, mm_per_px)
        except SystemExit:
            continue
        # mask_to_polygon rescales each region to fill ART_D — undo that: scale
        # relative to the region's true size instead so regions stay in place.
        parts.append((m, hexcol, rep))
        report.append(f"  region {idx + 1} {hexcol}: {rep['coverage'] * 100:.0f}% of frame, "
                      f"grown {rep['thickened']:.2f}mm")
    if not parts:
        raise SystemExit("nothing traceable in the image")
    return body, parts, report


def masks_to_meshes(parts):
    """All regions share ONE coordinate frame (the whole art circle), unlike
    make_chip which rescales a single mask to fill the face."""
    mm_per_px = MC.ART_D / MC.WORK_PX
    import shapely.geometry as sg
    import shapely.ops as so
    meshes = []
    for m, hexcol, _ in parts:
        cs, hier = cv2.findContours(m.astype(np.uint8), cv2.RETR_CCOMP,
                                    cv2.CHAIN_APPROX_SIMPLE)
        if hier is None:
            continue
        hier = hier[0]

        def ring(c):
            return [(p[0][0] * mm_per_px - MC.ART_D / 2,
                     -(p[0][1] * mm_per_px) + MC.ART_D / 2) for p in c]

        polys = []
        for i, c in enumerate(cs):
            if hier[i][3] != -1 or len(c) < 3:
                continue
            holes = [ring(cs[j]) for j in range(len(cs))
                     if hier[j][3] == i and len(cs[j]) >= 3]
            pl = sg.Polygon(ring(c), holes)
            if not pl.is_valid:
                pl = pl.buffer(0)
            if not pl.is_empty:
                polys.append(pl)
        if not polys:
            continue
        geom = so.unary_union(polys).simplify(0.06, preserve_topology=True)
        # open-close smoothing kills the sliver self-intersections that
        # region clipping leaves behind (they made non-watertight extrusions)
        geom = geom.buffer(-0.05).buffer(0.10).buffer(-0.05)
        if geom.is_empty:
            continue
        mesh = D.extrude_multi(geom, D.EMBOSS)
        mesh.apply_translation([0, 0, D.CHIP_H])
        mesh.merge_vertices()
        if not mesh.is_watertight:
            trimesh.repair.fill_holes(mesh)
        meshes.append((mesh, hexcol))
    return meshes


def _shown(path):
    """Relative to the cwd when that reads well, else absolute."""
    rel = os.path.relpath(os.path.abspath(path), os.getcwd())
    return os.path.abspath(path) if rel.startswith("..") else rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None, help="project dir (default: alongside image)")
    ap.add_argument("--invert", action="store_true")
    a = ap.parse_args()

    name = a.name or os.path.splitext(os.path.basename(a.image))[0].lower()
    name = "".join(c if c.isalnum() else "_" for c in name).strip("_")
    out = a.out or os.path.dirname(os.path.dirname(os.path.abspath(a.image)))

    body, parts, report = build_coin(a.image, a.invert)
    meshes = masks_to_meshes(parts)

    os.makedirs(f"{out}/parts", exist_ok=True)
    os.makedirs(f"{out}/final", exist_ok=True)

    colors = {"coin_body.stl": "#2f2f36"}
    body.export(f"{out}/parts/coin_body.stl")
    all_meshes = [body]
    for i, (mesh, hexcol) in enumerate(meshes):
        fn = f"coin_c{i + 1}.stl"
        mesh.export(f"{out}/parts/{fn}")
        colors[fn] = hexcol
        all_meshes.append(mesh)

    import json
    existing = {}
    pj = f"{out}/parts/parts.json"
    if os.path.exists(pj):
        try:
            existing = {k: v for k, v in json.load(open(pj)).items()
                        if isinstance(v, str) and v.startswith("#")}
        except Exception:
            pass
    existing.update(colors)
    json.dump(existing, open(pj, "w"), indent=2)

    merged = trimesh.util.concatenate(all_meshes)
    merged.export(f"{out}/model.stl")
    merged.export(f"{out}/final/token_coin_{name}_{D.CHIP_D:.0f}mm.stl")

    n, z, exact = D.change_layer()
    print(f"\n  coin            {name}   ({len(meshes)} colour regions + body)")
    for line in report:
        print(line)
    print(f"  size            {merged.extents[0]:.1f} x {merged.extents[1]:.1f}"
          f" x {merged.extents[2]:.2f} mm   fits socket (chip_d {D.CHIP_D})")
    print(f"  watertight      body={body.is_watertight} "
          f"regions={[m.is_watertight for m, _ in meshes]}")
    print(f"  relief band     Z {D.CHIP_H} → {D.CHIP_H + D.EMBOSS}  "
          f"(colour changes land after layer {n})")
    print(f"  -> {_shown(out)}/parts/  + model.stl\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
