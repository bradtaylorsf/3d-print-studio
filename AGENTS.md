# AGENTS.md — working in 3D Print Studio

This repo is a local workspace for **3D printing**: a live design viewer (`studio/`), a kid
flow that turns "I want a dragon" into four pictures and then into a printable coin or toy,
and a set of skills that teach an agent to do the mesh work itself. Any coding agent
(Claude Code, Codex, …) works here; this file is the contract. `CLAUDE.md` imports it.

You act as a hands-on sidekick. The goal is that the user rarely has to touch external mesh
tools — you **create, edit, repair, orient, scale, hollow, and split** STL/3MF files directly,
and hand back **print-ready** files plus the exact slicer settings to use. Do as much of the
work as possible; only ask the user to step in when a decision is genuinely theirs (scale,
which variant, color assignment, etc.).

Be concise and direct. Lead with the file and the settings, not a long preamble.

---

## First run

If `.venv/` or `studio.config.json` is missing, the repo isn't installed yet: follow
[`SETUP.md`](SETUP.md) (the `setup` skill does exactly that) — unless you are a headless
"Make me 3D" build (see below), which never installs anything. To check an existing install:

```bash
.venv/bin/python scripts/doctor.py            # ✅/❌ per check, with the fix for each
.venv/bin/python scripts/doctor.py --json     # the same, machine-readable
```

## The printer — read it, don't assume it

The printer facts come from two places:

1. **`studio.config.json`** (per machine, gitignored) — `printer.name`, `printer.bed_mm`
   `[X, Y, Z]`, `printer.margin_mm`, `printer.slicer`. The **design envelope** is the bed minus
   the margin on every axis. Read them with
   `.venv/bin/python scripts/configure.py get printer` (or `… show` for everything).
2. **`printers/<slug>/profile.md`** — the machine's spec table, its default print profile, and
   what is known to work on it.

**Shipped default: Creality K2** (K2 Combo — CoreXY, enclosed, passive chamber, CFS
multi-color), **260 × 260 × 260 mm bed → 255 × 255 × 255 mm envelope**, **Creality Print
7.1.1.4472**, **PLA**. Its profile is [`printers/creality-k2/profile.md`](printers/creality-k2/profile.md),
and the `k2-slicing` / `k2-supports` / `print-troubleshooting` skills are tuned for it.
For any other printer, run the `printer-setup` skill first: it writes
`printers/<slug>/profile.md` and sets the `printer.*` keys, and from then on those numbers win
over anything K2-specific in the skills.

For first prints of a new model, prefer the **center** of the bed.

---

## How to work

1. **Inspect first.** For any mesh, report bounding-box dimensions (mm), triangle count,
   watertight/manifold status, and whether it needs repair before doing anything else.
2. **Repair if needed.** Fix non-manifold edges, holes, flipped normals, and duplicate
   vertices before slicing advice. Never recommend settings for a broken mesh.
3. **Orient for the printer.** Pick an orientation that minimizes supports and puts the best
   surface up/out, then say why. Add a flat base/raft-friendly footprint when a model has a
   tiny or pointed contact area.
4. **Scale to fit & to purpose.** Confirm the model fits the design envelope (255³ mm on the
   default K2 — check `printer.bed_mm` / `printer.margin_mm`) and matches the user's intended
   real-world size. Call out anything that prints too thin (< 2 walls at 0.4 mm ≈ 0.8 mm).
5. **Propose the profile.** Start from the default print profile in
   `printers/<slug>/profile.md` and adjust it for this specific model (layer height, walls,
   infill, supports, adhesion). State the settings in your response when prepping a file.
6. **Plan supports** using the supports skill — figurines almost always need them; choose
   tree vs normal and call out where they'll mar the surface.
7. **Multi-color:** for multi-material jobs (the K2's CFS: 4 filaments per unit), plan
   filament-channel assignments and color-change strategy, and prefer a 3MF that carries the
   per-object/per-color data.
8. **Hand back print-ready files** + a short, plain-language summary of settings and any risks.
9. **Verify.** Re-open/re-measure outputs, render a preview when useful, and sanity-check the
   numbers before declaring something print-ready.

---

## File & folder conventions

Projects live in the **projects directory** — `projects/` at the repo root unless
`projects_dir` in `studio.config.json` points elsewhere. One folder per model/idea:

```
projects/<name>/
├── design.py     parametric source (when generative) — run it to rebuild model.stl
├── model.stl     the "live" model the studio viewer watches
├── parts/        multi-part STLs for multi-color jobs (+ optional parts.json colors)
├── refs/         reference images, generated picture options, studio viewer captures
├── vectors/      SVG originals of pictures drawn by the Claude backend (same stem as refs/)
├── source/       original untouched downloaded meshes
├── final/        print-ready deliverables (STL / 3MF / gcode)
└── previews/     render PNGs and QA screenshots
```

Two special folders: `projects/library/refs/` is the shared picture pool kid mode works from,
and `projects/.archive/` is where the 🗂 archive buttons move things (nothing is ever
deleted — move a folder back by hand to restore). On first start with an empty projects
directory, the studio seeds it from `examples/`. If the repo has a `MANIFEST.md`, keep it
updated when projects change status.

Naming rules for files you produce:

- **Source mesh:** keep the original untouched in `source/`.
- **Edited/derived mesh:** describe the edit and key dimension, e.g.
  `fantasy_witch_with_base_135mm.stl`, `bracket_v2_hollowed.stl`.
- **Sliced output:** include material + time when known, e.g.
  `fantasy_witch_with_base_135mm_PLA_4h59m.gcode`.
- **3MF** is preferred over STL when color, per-object settings, or scene layout matter
  (multi-color jobs especially).
- Use lowercase, underscores, and a trailing dimension in mm where relevant.

Final deliverables go in the project's `final/` folder. QA screenshots and previews go in
`previews/`, never at repo root. Temporary scratch work goes in your own scratch/temp
directory, not in the repo.

## Studio — live design viewer

`studio/` is a local web app for iterating on designs with the user in the loop:

```bash
./start.sh                                   # → http://localhost:8765/?kid=1, opens the browser
.venv/bin/python studio/server.py [--port N] # just the server → http://localhost:8765/?project=<name>
.venv/bin/python studio/server.py --projects <dir>   # another projects folder (sets STUDIO_PROJECTS_DIR)
```

- The viewer watches `projects/<name>/model.stl` (or `parts/*.stl`) and **hot-reloads within
  ~2 s** whenever the file changes — edit `design.py`, rerun it, and the user sees the change
  live without losing their camera angle.
- The user can **drag reference images** onto the page (saved to `refs/`) and **capture
  screenshots** of the current angle (saved as `refs/capture_<n>.png`) — read those files when
  they mention them.
- **Kid mode** (`?kid=1`, or the 🧸 button): the user talks or types a wish, the studio draws
  `options` pictures (4 by default) with the configured image backend (`image_backend`:
  Claude Code, a local ComfyUI, or Nano Banana), the kid picks one, then either
  **🪙 Make my coin** (`studio/tools/make_coin.py`: a traced 28 mm multi-colour coin, ~1 s, no
  AI) or **🤖 Make me 3D** (a headless Claude Code build of a chunky, support-free toy).
- The HTTP API is listed in the `studio/server.py` docstring; `GET /api/setup` returns the same
  readiness report as `scripts/doctor.py --json`. You can see exactly what the user sees.
- The iterate loop, the `design.py` template (`studio/design_template.py`), the kid flow and
  troubleshooting live in `skills/design-studio/SKILL.md` — read it before any studio session.

### If you are a headless "Make me 3D" build

The studio started you with no human watching and with permission prompts off. Stay inside
the project folder you were given: write only there, use `.venv/bin/python`, don't install
software, and don't edit `studio/`, `skills/`, `scripts/`, the config, or other projects.
Export something printable early and improve it — a build that is killed at the timeout with
no `model.stl` or `parts/*.stl` on disk gave the child nothing.

---

## Skills

These live in `skills/<name>/SKILL.md`. Read the relevant one before acting.

- **setup** — install and configure this repo for a new user; runs [`SETUP.md`](SETUP.md).
- **design-studio** — the live-viewer iterate loop: start the studio server, scaffold a
  project + `design.py`, hot-reload edits, steer from the user's captures/refs; the kid flow
  and its API.
- **image-to-model** — turn reference images into printable models: classify the job
  (cutout / relief / multi-color plate / functional / figurine), ask the right questions,
  build fast v1s, plan multi-piece multi-color output.
- **token-coin** — a kid names a thing, it becomes a 28 mm printable coin: the picture
  prompt, `studio/tools/make_coin.py`, the print-safety report, and the single colour-change
  slice. Use for "make me a dinosaur one" or a photo of a drawing.
- **stl-prep** — create/edit/repair/orient/scale/hollow/split STL & 3MF files programmatically
  (`skills/stl-prep/meshtools.py`) so the user doesn't need external mesh tools. Use for any
  geometry work.
- **k2-slicing** — Creality Print 7.1.1.4472 settings & profiles for the K2, including the
  multi-color CFS workflow. Use when prepping slice settings or producing a slicing plan.
- **k2-supports** — support strategy: tree vs normal, overhang thresholds, placement, painting
  and blocking supports, easy-removal tips for figurines.
- **print-troubleshooting** — diagnose and fix failed or ugly prints (adhesion, stringing,
  warping, layer shifts, first-layer problems), tuned for the K2 + PLA.
- **printer-setup** — onboard a printer or new user: interview, research the machine, build
  the `printers/<slug>/` knowledge base and set the `printer.*` config keys.
- **contributing** — problem-driven lifecycle for any change or PR to this repo:
  problem → research → hypothesis → smallest experiment → build → verify → PR. Use it
  whenever someone wants to add/fix something or says "create a PR".

## Toolbox

- `.venv/bin/python` has the toolchain from `requirements.txt`: `trimesh`, `manifold3d`,
  `numpy`, `scipy`, `shapely`, `matplotlib`, `pillow`, `opencv-python-headless`,
  `scikit-image`, `resvg_py`. Use it for mesh inspection/repair/editing and previews.
- Render previews with trimesh/matplotlib or trimesh's scene PNG export.
- `skills/stl-prep/meshtools.py` — inspect / repair / orient / scale helpers.
- `studio/tools/make_coin.py IMAGE --name N --out <project dir>` — picture → coin.
- `scripts/doctor.py`, `scripts/configure.py` — setup checks and config edits.
- The slicer runs on the user's machine; you prepare files and exact settings, the user
  imports and slices (the studio's 🖨 button opens the displayed model in `printer.slicer`).

## Changing the repo

Follow the `contributing` skill. House rules: the server is stdlib-only; no build step and no
npm (three.js is vendored in `studio/static/three/`); skills are plain markdown; Python code
stays 3.10+ compatible; comments explain *why*. Claude work goes through the user's own
`claude` CLI — the studio has no AI SDKs or API keys of its own (Nano Banana's Gemini key is
the one exception, and it's optional). Keep personal details out of tracked files: put
machine- or person-specific notes in `CLAUDE.local.md` or `printers/<slug>/log.md`, which
the public repo gitignores and `scripts/check_privacy.py` refuses to ship.
