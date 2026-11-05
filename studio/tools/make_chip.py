#!/usr/bin/env python3
"""make_chip.py — turn a picture into a printable one-colour token chip.

    .venv/bin/python studio/tools/make_chip.py IMAGE --name dinosaur --out <project dir>

Takes any PNG/JPG — a generated image, or a photo of a drawing on paper —
lifts the subject off the background, forces every feature up to a width the
printer can actually print, and drops it onto a chip that fits a token-board
socket (dimensions come from chip_geometry.py — never redefined here).

    --name NAME      output name (default: the image's filename)
    --out DIR        project directory to write into (default: the image's
                     project, i.e. the parent of its refs/ folder)
    --fast           re-snap for a 0.28 mm chip-only job, ~30 % less print time.
                     ONLY for a chip-only plate. Never for a plate with a board.
    --copies N       lay N chips out on one plate (default 2 — one to seat,
                     one to pocket). The colour change is shared, so 4 chips
                     cost barely more than 1.
    --invert         force subject/background the other way round
    --thicken MM     grow every feature by this much before printing
    --keep N         keep only the N biggest pieces (default 6)

Writes final/token_chip_<name>_28mm.stl and previews/token_chip_<name>.png,
and prints a REPORT — thinnest feature, pieces kept, pieces dropped, the
colour-change layer, and whether it is print-safe. Read the report. A chip
that fails MIN_FEATURE will print as a smear or not at all.
"""
import argparse
import os
import sys

import cv2
import numpy as np
import shapely.geometry as sg
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chip_geometry as D                                    # noqa: E402

# The chip face the art has to live on, minus a ring so nothing runs off the edge.
ART_D = D.CHIP_D - 4.0        # 24 mm of usable face on a 28 mm chip
MIN_FEATURE = 0.9             # mm. Below ~0.8 (2 walls at 0.4) it will not print.
MIN_AREA_FRAC = 0.004         # drop specks under this fraction of the art circle
THIN_TOL = 0.030              # up to 3 % of the area may be sub-nozzle — those are tips
MAX_GROW = 1.20               # mm. Past this the art stops looking like itself.
WORK_PX = 1000                # working resolution for the mask


# ------------------------------------------------------------------ mask ---
BG_TOL = 10       # max per-channel distance from the border colour that still reads as background
SHADOW_TOL = 60   # standalone pieces closer than this to the border colour are drop shadows


def raw_subject(path, invert=None, fill=False):
    """Image -> boolean foreground mask at the image's own size.

    Uses alpha when the file has a real one. On a flat-colour background the
    background is whatever MATCHES THE BORDER COLOUR — a brightness threshold
    (the old way) carved the cream belly and white eye out of a light-background
    sticker along with the background itself. Otsu stays as the fallback for
    photos and uneven backgrounds, with the background decided by the border
    pixels rather than assumed — generated art comes both ways round.

    fill=True keeps enclosed background-coloured pockets (an eye, an open
    mouth) as part of the subject — what a multi-colour coin wants. Without it
    they stay holes — what a one-colour silhouette chip wants."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"could not read {path}")

    used_alpha = False
    bg_dist = None
    if img.ndim == 3 and img.shape[2] == 4 and img[:, :, 3].min() < 250:
        mask = img[:, :, 3] > 127
        used_alpha = True
    else:
        bgr = img[:, :, :3] if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        border = np.concatenate([bgr[0], bgr[-1], bgr[:, 0], bgr[:, -1]]
                                ).reshape(-1, 3).astype(np.int16)
        bg = np.median(border, axis=0)
        if (np.abs(border - bg).max(axis=1) <= BG_TOL).mean() >= 0.7:
            bg_dist = np.abs(bgr.astype(np.int16) - bg).max(axis=2)
            mask = bg_dist > BG_TOL
        else:
            g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            g = cv2.GaussianBlur(g, (5, 5), 0)
            _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            mask = th > 0
            # Border majority is the background. Flip so the subject is True.
            b = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
            if b.mean() > 0.5:
                mask = ~mask

    if invert:
        mask = ~mask
    if fill and not used_alpha:
        # Background is only what touches the image border; enclosed pockets
        # become subject again. Real alpha is deliberate — its holes stay.
        _, lab = cv2.connectedComponents((~mask).astype(np.uint8), connectivity=4)
        edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        mask = ~(~mask & np.isin(lab, edge[edge != 0]))
    if bg_dist is not None and mask.any():
        # A sticker's drop shadow passes the colour test (it is darker than the
        # background) but it is not art: drop standalone pieces whose colour
        # stays CLOSE to the background — never the biggest piece.
        n, lab, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8)
        if n > 2:
            big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            for i in range(1, n):
                if i != big and bg_dist[lab == i].mean() < SHADOW_TOL:
                    mask[lab == i] = False
    if not mask.any():
        raise SystemExit("mask is empty — nothing to put on the chip")
    return mask, used_alpha


def load_mask(path, invert=None, fill=False):
    """raw_subject, squared off and normalised to WORK_PX for tracing."""
    mask, used_alpha = raw_subject(path, invert, fill)

    # Square it off around the subject so the art is centred, then normalise size.
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = mask[y0:y1, x0:x1]
    side = max(crop.shape)
    pad = np.zeros((side, side), bool)
    oy, ox = (side - crop.shape[0]) // 2, (side - crop.shape[1]) // 2
    pad[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
    m = cv2.resize(pad.astype(np.uint8), (WORK_PX, WORK_PX),
                   interpolation=cv2.INTER_NEAREST) > 0
    return m, used_alpha


def disc(r_px):
    k = max(1, int(round(r_px)) * 2 + 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def thin_fraction(mask, mm_per_px, min_feature=MIN_FEATURE):
    """How much of the shape is narrower than the nozzle can lay down.

    Opening with a disc of radius w/2 erases anything narrower than w, so what
    the opening loses IS the unprintable part, by definition. That is a far
    steadier number than probing the distance transform for a minimum — every
    pointed tip is thin at the very tip, and a tip is fine; an extended thin
    limb is not. A few percent means tips. A lot means limbs."""
    if not mask.any():
        return 1.0
    r = (min_feature / 2.0) / mm_per_px
    op = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, disc(r)).astype(bool)
    return float((mask & ~op).sum()) / float(mask.sum())


def narrowest_mm(mask, mm_per_px):
    """Informational: width of the narrowest sustained limb, read off the true
    medial axis with endpoints excluded so tapering tips do not dominate."""
    from skimage.morphology import skeletonize
    d = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    skel = skeletonize(mask)
    nb = cv2.filter2D(skel.astype(np.uint8), -1,
                      np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.uint8))
    core = skel & (nb >= 2)                      # drop 1-neighbour endpoints
    vals = d[core if core.any() else skel]
    return float(np.percentile(vals, 5) * 2 * mm_per_px) if vals.size else 0.0


def drop_specks(mask, keep):
    """Keep the biggest `keep` pieces that clear the minimum-area floor."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    areas = sorted(((stats[i, cv2.CC_STAT_AREA], i) for i in range(1, n)),
                   reverse=True)
    floor = MIN_AREA_FRAC * np.pi * (WORK_PX / 2.0) ** 2
    keepers = [i for a, i in areas[:keep] if a >= floor]
    if not keepers:
        raise SystemExit("every piece was below the minimum size — nothing to print")
    return np.isin(lab, keepers), len(areas), len(keepers)


def clean(mask, mm_per_px, thicken=0.0, keep=6):
    """Close pinholes, drop specks, THEN grow thin limbs.

    Order matters and it bit once: thickening first turns a field of noise
    specks into blobs big enough to clear the area floor, so the noise survives
    as art. Drop first, grow second."""
    px = 1.0 / mm_per_px
    rep = {}

    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE,
                            disc(0.25 * px)).astype(bool)
    mask, found, kept = drop_specks(mask, keep)
    rep["pieces_found"], rep["pieces_kept"] = found, kept
    rep["pieces_dropped"] = found - kept

    rep["thin_raw"] = thin_fraction(mask, mm_per_px)
    rep["narrowest_raw"] = narrowest_mm(mask, mm_per_px)

    grown = 0.0
    if thicken > 0:
        mask = cv2.dilate(mask.astype(np.uint8), disc(thicken * px)).astype(bool)
        grown = thicken
    else:
        # Grow in small steps only until the unprintable fraction is tips-only.
        while (thin_fraction(mask, mm_per_px) > THIN_TOL) and grown < MAX_GROW:
            mask = cv2.dilate(mask.astype(np.uint8), disc(0.10 * px)).astype(bool)
            grown += 0.10
    rep["thickened"] = round(grown, 2)

    mask, _, _ = drop_specks(mask, keep)
    rep["thin_final"] = thin_fraction(mask, mm_per_px)
    rep["narrowest_final"] = narrowest_mm(mask, mm_per_px)
    rep["coverage"] = float(mask.mean())
    return mask, rep


# --------------------------------------------------------------- polygon ---
def mask_to_polygon(mask, mm_per_px, simplify_mm=0.06):
    """Contours -> shapely, holes attached to their parents, centred on the
    origin in mm."""
    cs, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP,
                                cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        raise SystemExit("no contours found")
    hier = hier[0]

    def ring(c):
        return [(p[0][0] * mm_per_px, -p[0][1] * mm_per_px) for p in c]

    polys = []
    for i, c in enumerate(cs):
        if hier[i][3] != -1 or len(c) < 3:
            continue
        holes = [ring(cs[j]) for j in range(len(cs))
                 if hier[j][3] == i and len(cs[j]) >= 3]
        p = sg.Polygon(ring(c), holes)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty and p.area > 0:
            polys.append(p)
    if not polys:
        raise SystemExit("no usable contours")

    geom = polys[0] if len(polys) == 1 else sg.MultiPolygon(
        [g for p in polys for g in (p.geoms if hasattr(p, "geoms") else [p])])
    geom = geom.simplify(simplify_mm, preserve_topology=True)

    x0, y0, x1, y1 = geom.bounds
    k = ART_D / max(x1 - x0, y1 - y0)
    geom = D.so.transform(lambda x, y, z=None: (x * k, y * k), geom)
    x0, y0, x1, y1 = geom.bounds
    return D.so.transform(
        lambda x, y, z=None: (x - (x0 + x1) / 2, y - (y0 + y1) / 2), geom)


# --------------------------------------------------------------- preview ---
def preview(src, chip, face, out, name, rep):
    """Source image beside the chip it became — the only honest check that the
    thing still looks like what the kid asked for."""
    import warnings
    warnings.filterwarnings("ignore")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    BLACK, WHITE = np.array([.40, .40, .45]), np.array([.96, .96, .97])
    L = np.array([.40, -.50, .77])
    L = L / np.linalg.norm(L)

    fig = plt.figure(figsize=(9, 4.6), facecolor="white")

    ax = fig.add_subplot(1, 2, 1)
    im = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if im.ndim == 3:
        im = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2RGB)
    ax.imshow(im, cmap=None if im.ndim == 3 else "gray")
    ax.set_axis_off()
    ax.set_title("source image", color="#444", fontsize=9)

    ax = fig.add_subplot(1, 2, 2, projection="3d", facecolor="white")
    zmid = chip.triangles[:, :, 2].mean(axis=1)
    base = np.where((zmid > face + 1e-6)[:, None], WHITE, BLACK)
    inten = (.45 + .55 * np.clip(chip.face_normals @ L, 0, 1))[:, None]
    ax.add_collection3d(Poly3DCollection(chip.triangles, shade=False,
                                         facecolors=np.clip(base * inten, 0, 1),
                                         edgecolors="none"))
    b, c = chip.bounds, chip.centroid
    s = max(b[1] - b[0]) / 2 + 1
    ax.set_xlim(c[0] - s, c[0] + s)
    ax.set_ylim(c[1] - s, c[1] + s)
    ax.set_zlim(c[2] - s, c[2] + s)
    ax.view_init(elev=62, azim=-90)
    ax.set_axis_off()
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:
        pass
    ax.set_title(f"{name} — {D.CHIP_D:.0f} mm chip\n"
                 f"grown {rep['thickened']:.2f} mm · "
                 f"{rep['thin_final'] * 100:.1f} % sub-nozzle",
                 color="#444", fontsize=9)

    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------ main ---
def _shown(path):
    """Relative to the cwd when that reads well, else absolute."""
    rel = os.path.relpath(os.path.abspath(path), os.getcwd())
    return os.path.abspath(path) if rel.startswith("..") else rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None, help="project dir (default: alongside the image's refs/)")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--copies", type=int, default=2)
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--thicken", type=float, default=0.0)
    ap.add_argument("--keep", type=int, default=6)
    a = ap.parse_args()

    name = a.name or os.path.splitext(os.path.basename(a.image))[0].lower()
    name = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    out_dir = os.path.abspath(a.out or os.path.dirname(os.path.dirname(os.path.abspath(a.image))))

    layer_h = 0.28 if a.fast else D.LAYER_H
    face = D.snap_face(layer_h) if a.fast else D.FACE
    emboss = round(max(3, int(D.EMBOSS / layer_h)) * layer_h, 4) if a.fast else D.EMBOSS

    mask, used_alpha = load_mask(a.image, a.invert)
    mm_per_px = ART_D / WORK_PX
    mask, rep = clean(mask, mm_per_px, a.thicken, a.keep)
    geom = mask_to_polygon(mask, mm_per_px)

    chip = D.build_chip(relief=geom, face=face, emboss=emboss)
    n_layer, z, exact = D.change_layer(face, layer_h)

    os.makedirs(f"{out_dir}/final", exist_ok=True)
    os.makedirs(f"{out_dir}/previews", exist_ok=True)
    os.makedirs(f"{out_dir}/parts", exist_ok=True)
    out = f"{out_dir}/final/token_chip_{name}_{D.CHIP_D:.0f}mm.stl"
    preview(a.image, chip, face, f"{out_dir}/previews/token_chip_{name}.png", name, rep)

    plate = []
    cols = min(a.copies, 4)
    for i in range(a.copies):
        c = chip.copy()
        c.apply_translation([(i % cols) * (D.CHIP_D + 6.0),
                             (i // cols) * (D.CHIP_D + 6.0), 0])
        plate.append(c)
    plated = trimesh.util.concatenate(plate)
    plated.export(out)
    chip.export(f"{out_dir}/parts/chip_{name}.stl")

    ok = (rep["thin_final"] <= THIN_TOL
          and chip.is_watertight and 0.04 < rep["coverage"] < 0.85)

    print(f"\n  chip            {name}")
    print(f"  source          {os.path.basename(a.image)}"
          f"   ({'alpha' if used_alpha else 'auto-threshold'})")
    print(f"  pieces          kept {rep['pieces_kept']} of {rep['pieces_found']}"
          f"   dropped {rep['pieces_dropped']} as too small")
    print(f"  narrowest limb  {rep['narrowest_raw']:.2f} mm raw"
          f"  ->  {rep['narrowest_final']:.2f} mm printed"
          f"   (grown {rep['thickened']:.2f} mm, floor {MIN_FEATURE})")
    print(f"  sub-nozzle area {rep['thin_raw'] * 100:.1f} %  ->  "
          f"{rep['thin_final'] * 100:.1f} %   (tolerance {THIN_TOL * 100:.0f} %)")
    print(f"  face coverage   {rep['coverage'] * 100:.0f} %")
    print(f"  chip            {chip.extents[0]:.1f} x {chip.extents[1]:.1f}"
          f" x {chip.extents[2]:.2f} mm   {len(chip.faces)} tri"
          f"   watertight={chip.is_watertight}")
    print(f"  layer / face    {layer_h} mm  /  {face} mm"
          f"   emboss {emboss} mm")
    print(f"  colour change   after layer {n_layer}  (Z {z:.2f} mm)"
          f"   {'exact' if exact else 'APPROX — check the preview'}")
    print(f"  plate           {a.copies} copies, "
          f"{plated.extents[0]:.0f} x {plated.extents[1]:.0f} mm")
    print(f"  -> {_shown(out)}")
    print(f"\n  PRINT-SAFE      {'YES' if ok else 'NO — see above'}\n")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
