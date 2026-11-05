#!/usr/bin/env python3
"""
meshtools.py — print-prep helpers for the studio's configured printer.

A small CLI around trimesh/numpy so an agent can inspect, repair, orient, scale,
hollow, split, convert, and preview meshes without an external mesh editor.

Fit checks use the design envelope from studio/config.py (printer.bed_mm minus
printer.margin_mm in studio.config.json) — the same numbers the studio's
"fits" badge uses. Run outside the repo, it falls back to the default
Creality K2's 255 x 255 x 255 mm.

Run it with the repo's interpreter (.venv/bin/python, which ./install.sh
creates); a bare system python3 usually lacks trimesh and numpy.

Usage:
    python3 meshtools.py info IN
    python3 meshtools.py repair IN OUT
    python3 meshtools.py scale IN OUT (--height MM | --factor F)
    python3 meshtools.py layflat IN OUT
    python3 meshtools.py rotate IN OUT [--x DEG] [--y DEG] [--z DEG]
    python3 meshtools.py addbase IN OUT [--shape disc|box] [--diameter MM]
                                        [--width MM] [--depth MM] [--thickness MM]
    python3 meshtools.py hollow IN OUT --wall MM
    python3 meshtools.py split IN OUTDIR
    python3 meshtools.py convert IN OUT
    python3 meshtools.py preview IN OUT.png
"""
import argparse
import os
import sys

# numpy inside the guard too: under a bare system python3 it is the first
# import to fail, and the hint below never printed.
try:
    import numpy as np
    import trimesh
except ImportError:
    sys.exit("trimesh/numpy not installed. Run this with the repo's .venv/bin/python "
             "(./install.sh creates it), or: pip install -r requirements.txt")

# realpath, not abspath: agents often run this through the .claude/skills/stl-prep
# symlink, and the repo root is only three levels up from the real file.
HERE = os.path.realpath(__file__)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
FALLBACK_ENVELOPE = (255.0, 255.0, 255.0)   # the default K2: 260 mm bed minus a 5 mm margin


def _envelope():
    """Design envelope (X, Y, Z) in mm from studio/config.py, or the K2 default.
    Loaded by file path so a copy of this script outside the repo still works
    and an unrelated module named `config` can never shadow the studio's."""
    path = os.path.join(REPO, "studio", "config.py")
    # only when this file really is <repo>/skills/stl-prep/meshtools.py: a copy
    # dropped anywhere else must not execute whatever studio/config.py happens
    # to sit three directories up from it
    if os.path.normcase(HERE) != os.path.normcase(
            os.path.join(REPO, "skills", "stl-prep", "meshtools.py")):
        return FALLBACK_ENVELOPE
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("studio_config", path)
        cfgmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfgmod)
        env = [float(v) for v in cfgmod.envelope_mm(cfgmod.get())][:3]
        if len(env) == 3 and all(v > 0 for v in env):
            return tuple(env)
    except Exception:
        pass
    return FALLBACK_ENVELOPE


ENVELOPE = _envelope()


def _envelope_label():
    x, y, z = ENVELOPE
    return f"{x:g}^3" if x == y == z else f"{x:g}x{y:g}x{z:g}"


def _load(path):
    m = trimesh.load(path, force="mesh")
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(tuple(m.dump()))
    return m


def _fit_report(m):
    ext = m.bounding_box.extents
    fits = all(e <= lim for e, lim in zip(ext, ENVELOPE))
    return ext, fits


def cmd_info(a):
    m = _load(a.IN)
    ext, fits = _fit_report(m)
    print(f"File:        {a.IN}")
    print(f"Bounding box (mm):  X={ext[0]:.2f}  Y={ext[1]:.2f}  Z={ext[2]:.2f}")
    print(f"Fits {_envelope_label()} envelope: "
          f"{'YES' if fits else 'NO — exceeds the envelope, needs scaling, rotating or splitting'}")
    print(f"Triangles:   {len(m.faces):,}")
    print(f"Vertices:    {len(m.vertices):,}")
    print(f"Watertight:  {m.is_watertight}")
    print(f"Winding consistent: {m.is_winding_consistent}")
    try:
        bodies = m.split(only_watertight=False)
        print(f"Disconnected bodies: {len(bodies)}")
    except Exception:
        print("Disconnected bodies: n/a (install scipy or networkx for body counting)")
    try:
        vol_cm3 = m.volume / 1000.0
        print(f"Volume:      {vol_cm3:.1f} cm^3")
        # very rough PLA: ~1.24 g/cm^3; at ~15% infill solid-equivalent is much less.
        print(f"  ~solid PLA mass: {vol_cm3 * 1.24:.0f} g (100% infill upper bound)")
    except Exception:
        print("Volume:      n/a (not watertight)")
    if not m.is_watertight or not m.is_winding_consistent:
        print(">> Recommend: run `repair` before slicing.")


def cmd_repair(a):
    m = _load(a.IN)
    m.merge_vertices()
    m.update_faces(m.unique_faces())
    m.update_faces(m.nondegenerate_faces())
    m.remove_infinite_values()
    trimesh.repair.fix_normals(m)
    trimesh.repair.fix_winding(m)
    trimesh.repair.fix_inversion(m)
    try:
        trimesh.repair.fill_holes(m)
    except Exception:
        pass
    m.export(a.OUT)
    print(f"Repaired -> {a.OUT}  | watertight={m.is_watertight} winding={m.is_winding_consistent}")


def cmd_scale(a):
    m = _load(a.IN)
    if a.height:
        cur = m.bounding_box.extents[2]
        f = a.height / cur
    elif a.factor:
        f = a.factor
    else:
        sys.exit("Provide --height MM or --factor F")
    m.apply_scale(f)
    ext, fits = _fit_report(m)
    m.export(a.OUT)
    print(f"Scaled x{f:.4f} -> {a.OUT}")
    print(f"New box (mm): X={ext[0]:.2f} Y={ext[1]:.2f} Z={ext[2]:.2f}  fits={'YES' if fits else 'NO'}")
    if min(ext) < 0.8:
        print(">> WARNING: a dimension < 0.8 mm — thin features may not print.")


def _drop_to_bed(m):
    m.apply_translation(-m.bounds[0])  # min corner to origin
    # center X/Y on bed origin-ish (Creality Print will recenter; just zero Z)
    return m


def cmd_layflat(a):
    m = _load(a.IN)
    # rest on largest stable facet as a first guess
    try:
        transforms, _ = trimesh.poses.compute_stable_poses(m)
        if len(transforms):
            m.apply_transform(transforms[0])
    except Exception:
        pass
    _drop_to_bed(m)
    m.export(a.OUT)
    ext = m.bounding_box.extents
    print(f"Laid flat -> {a.OUT}  box(mm) X={ext[0]:.2f} Y={ext[1]:.2f} Z={ext[2]:.2f}")
    print(">> Confirm orientation visually with `preview`; this is a heuristic.")


def cmd_rotate(a):
    m = _load(a.IN)
    for axis, deg in ((0, a.x), (1, a.y), (2, a.z)):
        if deg:
            R = trimesh.transformations.rotation_matrix(np.radians(deg), np.eye(3)[axis])
            m.apply_transform(R)
    _drop_to_bed(m)
    m.export(a.OUT)
    print(f"Rotated (x={a.x} y={a.y} z={a.z}) + dropped to bed -> {a.OUT}")


def cmd_addbase(a):
    m = _load(a.IN)
    _drop_to_bed(m)
    cx, cy = m.centroid[0], m.centroid[1]
    t = a.thickness
    if a.shape == "disc":
        d = a.diameter or max(m.bounding_box.extents[0], m.bounding_box.extents[1]) * 1.2
        base = trimesh.creation.cylinder(radius=d / 2.0, height=t, sections=128)
    else:
        w = a.width or m.bounding_box.extents[0] * 1.2
        dp = a.depth or m.bounding_box.extents[1] * 1.2
        base = trimesh.creation.box(extents=(w, dp, t))
    base.apply_translation([cx, cy, t / 2.0])
    # lift model so it sits on top of the base, with slight overlap to fuse
    m.apply_translation([0, 0, t - 0.4])
    out = trimesh.util.concatenate([base, m])
    out.export(a.OUT)
    print(f"Added {a.shape} base (t={t}mm) -> {a.OUT}")


def cmd_hollow(a):
    m = _load(a.IN)
    if not m.is_watertight:
        print(">> Mesh not watertight; repairing first.")
        trimesh.repair.fix_normals(m)
        trimesh.repair.fill_holes(m)
    try:
        inner = m.copy()
        # approximate shell: scale inner cavity down; good enough for filament saving
        # better hollows need voxel offset; offer that if user needs precision.
        import trimesh.proximity  # noqa
        shrink = 1.0 - (2.0 * a.wall / max(m.bounding_box.extents))
        inner.apply_scale(max(shrink, 0.05))
        inner.apply_translation(m.centroid - inner.centroid)
        inner.invert()
        shell = trimesh.util.concatenate([m, inner])
        shell.export(a.OUT)
        print(f"Hollowed (~{a.wall}mm wall, approximate) -> {a.OUT}")
        print(">> For FDM, consider just using 10% infill instead of true hollowing.")
    except Exception as e:
        sys.exit(f"Hollow failed: {e}. For FDM, use low infill in the slicer instead.")


def cmd_split(a):
    m = _load(a.IN)
    bodies = m.split(only_watertight=False)
    os.makedirs(a.OUTDIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.IN))[0]
    for i, b in enumerate(bodies, 1):
        p = os.path.join(a.OUTDIR, f"{base}_part{i}.stl")
        b.export(p)
        print(f"  part {i}: {p}  box(mm)={np.round(b.bounding_box.extents,2)}")
    print(f"Split into {len(bodies)} bodies -> {a.OUTDIR}")


def cmd_convert(a):
    m = _load(a.IN)
    m.export(a.OUT)
    print(f"Converted {a.IN} -> {a.OUT}")


def cmd_preview(a):
    m = _load(a.IN)
    try:
        png = m.scene().save_image(resolution=(900, 900))
        with open(a.OUT, "wb") as f:
            f.write(png)
        print(f"Preview -> {a.OUT}")
    except Exception:
        # headless fallback via matplotlib
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        fig = plt.figure(figsize=(6, 6))
        ax = fig.add_subplot(111, projection="3d")
        ax.add_collection3d(Poly3DCollection(m.triangles, alpha=0.6, edgecolor="none"))
        b = m.bounds
        ax.set_xlim(b[0][0], b[1][0]); ax.set_ylim(b[0][1], b[1][1]); ax.set_zlim(b[0][2], b[1][2])
        ax.set_box_aspect(np.array(m.bounding_box.extents, dtype=float))
        plt.savefig(a.OUT, dpi=110, bbox_inches="tight")
        print(f"Preview (matplotlib) -> {a.OUT}")


def main():
    p = argparse.ArgumentParser(description="Mesh prep tools for 3D printing "
                                            f"(fit checks against {_envelope_label()} mm)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("info"); s.add_argument("IN"); s.set_defaults(fn=cmd_info)
    s = sub.add_parser("repair"); s.add_argument("IN"); s.add_argument("OUT"); s.set_defaults(fn=cmd_repair)
    s = sub.add_parser("scale"); s.add_argument("IN"); s.add_argument("OUT")
    s.add_argument("--height", type=float); s.add_argument("--factor", type=float); s.set_defaults(fn=cmd_scale)
    s = sub.add_parser("layflat"); s.add_argument("IN"); s.add_argument("OUT"); s.set_defaults(fn=cmd_layflat)
    s = sub.add_parser("rotate"); s.add_argument("IN"); s.add_argument("OUT")
    s.add_argument("--x", type=float, default=0); s.add_argument("--y", type=float, default=0)
    s.add_argument("--z", type=float, default=0); s.set_defaults(fn=cmd_rotate)
    s = sub.add_parser("addbase"); s.add_argument("IN"); s.add_argument("OUT")
    s.add_argument("--shape", choices=["disc", "box"], default="disc")
    s.add_argument("--diameter", type=float); s.add_argument("--width", type=float)
    s.add_argument("--depth", type=float); s.add_argument("--thickness", type=float, default=3.0)
    s.set_defaults(fn=cmd_addbase)
    s = sub.add_parser("hollow"); s.add_argument("IN"); s.add_argument("OUT")
    s.add_argument("--wall", type=float, default=2.0); s.set_defaults(fn=cmd_hollow)
    s = sub.add_parser("split"); s.add_argument("IN"); s.add_argument("OUTDIR"); s.set_defaults(fn=cmd_split)
    s = sub.add_parser("convert"); s.add_argument("IN"); s.add_argument("OUT"); s.set_defaults(fn=cmd_convert)
    s = sub.add_parser("preview"); s.add_argument("IN"); s.add_argument("OUT"); s.set_defaults(fn=cmd_preview)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
