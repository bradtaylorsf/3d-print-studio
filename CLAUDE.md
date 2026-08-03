# CLAUDE.md — 3D Printing Sidekick for the Creality K2

This project is a working folder for **3D printing**. Everything in here is created,
edited, repaired, oriented, and sliced with one target machine and one slicer in mind:

- **Printer:** Creality **K2** (K2 Combo — CoreXY, fully enclosed, passive enclosure + CFS)
- **Slicer:** **Creality Print v7.1.1.4472** (release)
- **Primary material:** **PLA**
- **What gets printed:** detailed **models & figurines**, **functional parts**, and
  **multi-color** prints via the **CFS** unit.

Claude acts as a hands-on sidekick here. The goal is that the user rarely has to touch external
mesh tools — Claude should **create, edit, repair, orient, scale, hollow, and split** STL/3MF
files directly, and hand back **print-ready** files plus the exact Creality Print settings to
use. Do as much of the work as possible; only ask the user to step in when a decision is genuinely
theirs (scale, which variant, color assignment, etc.).

---

## The machine: Creality K2

| Spec | Value |
|---|---|
| Motion system | CoreXY, fully enclosed |
| Build volume | **300 × 300 × 300 mm** |
| Nozzle | 0.4 mm (default), all-metal quick-change, max **300 °C** |
| Heated bed | PEI-coated flexible steel, up to **100 °C** |
| Chamber | **Passive enclosure (no active chamber heater)** |
| Max speed / accel | up to 600 mm/s / 20,000 mm/s² (real prints run far lower) |
| Extruder | Dual-gear direct drive, all-metal |
| Camera | Single 720p chamber camera (monitoring / time-lapse) |
| Multi-color | **CFS** unit (Combo): 4 filaments per CFS, up to 4 CFS = 16 channels |

**Practical envelope for design/orientation:** keep parts inside **295 × 295 × 295 mm** to
leave clearance. For first prints of a new model, prefer the **center** of the bed.

---

## Default print profile (PLA on K2)

These are safe **starting points**, not gospel. Treat them as the baseline Claude proposes,
then tune per model. Always state these in the response when prepping a file.

| Setting | Value (PLA) | Notes |
|---|---|---|
| Nozzle temp | 215–220 °C | 220 first layer is fine |
| Bed temp | 60 °C | 55–60 °C |
| Chamber | Passive — vent for PLA | The K2 enclosure isn't actively heated; for long PLA prints crack the door/top so trapped heat doesn't cause heat-creep clogs |
| Layer height | **0.20 mm** general, **0.12–0.16 mm** for figurine detail | 0.28 mm for fast/draft |
| First layer height | 0.25 mm | better adhesion |
| Walls / perimeters | 3 (figurines), 4 (functional) | |
| Top/bottom layers | 4 / 4 (≈0.8 mm) | |
| Infill | 10–15% (figurines), 25–40% (functional) | Gyroid or grid |
| Print speed | 150–250 mm/s typical | Slow detailed areas; K2 can go faster but quality drops |
| Outer wall speed | 60–120 mm/s | Slower = cleaner surface |
| Cooling fan | 100% (after layer 2–3) | PLA loves cooling |
| Retraction | ~0.5–1.0 mm (direct drive) | Keep low; direct drive needs little |
| Build plate adhesion | Brim for tall/small-footprint; skirt otherwise | |
| Build plate | Smooth/textured PEI; PLA releases best cooled | |

**Material reality check:** the user runs PLA. The K2 enclosure is passive (no chamber heater), which
suits PLA fine — keep cooling high and vent the enclosure on long prints to avoid heat creep. If a
future job uses PETG/ABS/ASA/TPU, adjust temps and cooling per that material; note the passive
enclosure makes large ABS/ASA prints more warp-prone than on the actively heated K2 Plus/Pro.

---

## File & folder conventions

Everything lives under `projects/<name>/` — one folder per model/idea, indexed in
[MANIFEST.md](MANIFEST.md) (keep the manifest updated when projects change status):

```
projects/<name>/
├── design.py     parametric source (when generative) — run it to rebuild model.stl
├── model.stl     the "live" model the studio viewer watches
├── parts/        multi-part STLs for multi-color CFS jobs (+ optional parts.json colors)
├── refs/         reference images + studio viewer captures
├── source/       original untouched downloaded meshes
├── final/        print-ready deliverables (STL / 3MF / gcode)
└── previews/     render PNGs and QA screenshots
```

Naming rules for files Claude produces:

- **Source mesh:** keep the original untouched in `source/`.
- **Edited/derived mesh:** describe the edit and key dimension, e.g.
  `fantasy_witch_with_base_135mm.stl`, `bracket_v2_hollowed.stl`.
- **Sliced output:** include material + time when known, e.g.
  `fantasy_witch_with_base_135mm_PLA_4h59m.gcode`.
- **3MF** is preferred over STL when color, per-object settings, or scene layout matter
  (multi-color CFS jobs especially).
- Use lowercase, underscores, and a trailing dimension in mm where relevant.

Final deliverables go in the project's `final/` folder. QA screenshots and previews go in
`previews/`, never at repo root. Temporary scratch work lives in the outputs scratchpad.

## Studio — live design viewer

`studio/` is a local web app for iterating on designs with the user in the loop:

```
.venv/bin/python studio/server.py     # → http://localhost:8765/?project=<name>
```

- The viewer watches `projects/<name>/model.stl` (or `parts/*.stl`) and **hot-reloads within
  ~2 s** whenever the file changes — Claude edits `design.py`, reruns it, the user sees the change
  live without losing their camera angle.
- The user can **drag reference images** onto the page (saved to `refs/`) and **capture screenshots**
  of the current angle (saved as `refs/capture_<n>.png`) — read those files when they mention them.
- The iterate loop, design.py template, and troubleshooting live in
  `skills/design-studio/SKILL.md` — read it before any studio session.

---

## How Claude should work in this project

1. **Inspect first.** For any mesh, report bounding-box dimensions (mm), triangle count,
   watertight/manifold status, and whether it needs repair before doing anything else.
2. **Repair if needed.** Fix non-manifold edges, holes, flipped normals, and duplicate
   vertices before slicing advice. Never recommend settings for a broken mesh.
3. **Orient for the K2.** Pick an orientation that minimizes supports and puts the best
   surface up/out, then say why. Add a flat base/raft-friendly footprint when a model has a
   tiny or pointed contact area.
4. **Scale to fit & to purpose.** Confirm the model fits 295³ mm and matches the user's intended
   real-world size. Call out anything that prints too thin (< 2 walls at 0.4 mm ≈ 0.8 mm).
5. **Propose the profile.** Give the PLA settings table above, adjusted for this specific
   model (layer height, walls, infill, supports, adhesion).
6. **Plan supports** using the supports skill — figurines almost always need them; choose
   tree vs normal and call out where they'll mar the surface.
7. **Multi-color:** for CFS jobs, plan filament-channel assignments and color-change strategy,
   and prefer a 3MF that carries the per-object/per-color data.
8. **Hand back print-ready files** + a short, plain-language summary of settings and any risks.
9. **Verify.** Re-open/re-measure outputs, render a preview when useful, and sanity-check the
   numbers before declaring something print-ready.

Be concise and direct in responses (the user's preference). Lead with the file and the settings,
not a long preamble.

---

## Skills available in this project

These live in `skills/` in the project root. Claude should **read the relevant `SKILL.md`**
when a task matches. To make them auto-load as first-class skills, move the `skills/` folder
contents into `.claude/skills/` (e.g. `.claude/skills/k2-slicing/SKILL.md`) — same files, just
the location Claude Code/Cowork scans automatically.

- **k2-slicing** — Creality Print 7.1.1.4472 settings & profiles for the K2, including the
  multi-color CFS workflow. Use when prepping slice settings or producing a slicing plan.
- **k2-supports** — support strategy: tree vs normal, overhang thresholds, placement, painting
  and blocking supports, easy-removal tips for figurines.
- **stl-prep** — create/edit/repair/orient/scale/hollow/split STL & 3MF files programmatically
  so the user doesn't need external mesh tools. Use for any geometry work.
- **print-troubleshooting** — diagnose and fix failed or ugly prints (adhesion, stringing,
  warping, layer shifts, first-layer problems), tuned for the K2 + PLA.
- **design-studio** — the live-viewer iterate loop: start the studio server, scaffold a
  project + `design.py`, hot-reload edits, use the user's captures/refs to steer the design.
- **image-to-model** — turn reference images into printable models: classify the job
  (cutout / relief / multi-color plate / functional / figurine), ask the right questions,
  build fast v1s, plan multi-piece CFS output.
- **printer-setup** — onboard a printer or new user: interview, research the machine,
  build `printers/<slug>/` knowledge base (profile, resources index, common problems,
  running what-worked log).
- **contributing** — problem-driven lifecycle for any change or PR to this repo:
  problem → research → hypothesis → smallest experiment → build → verify → PR. Use it
  whenever someone wants to add/fix something or says "create a PR".

---

## Toolbox (already available in the sandbox)

- `trimesh`, `numpy-stl`, `numpy` for mesh inspection/repair/editing.
- Render previews with trimesh/matplotlib or trimesh's scene PNG export.
- Creality Print itself runs on the user's machine; Claude prepares files and exact settings,
  the user imports/slices (or Claude generates G-code via CLI when that path is set up).

> Reminder: Creality Print version is pinned to **7.1.1.4472**. Menu names and option locations
> in the slicing skill reference that version. If the user upgrades, flag that the UI paths may move.
