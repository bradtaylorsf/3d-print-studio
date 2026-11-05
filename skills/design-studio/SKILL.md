---
name: design-studio
description: >-
  The live iterate loop with the studio viewer: start the studio server, scaffold a project and
  its parametric design.py, hot-reload edits, and steer from the user's captures and reference
  images. Also the agent's reference for the kid flow (talk → 4 pictures → pick → coin or
  "Make me 3D" → paint → slicer) and its HTTP API. Use when the user wants to design something
  new, iterate on a model visually, says "let's work on X in the studio", "start the viewer",
  "make me a first version I can look at", or when you are the headless "Make me 3D" build.
---

# design-studio — live iterate loop with the studio viewer

Use this skill whenever the user wants to design something new, iterate on a model visually,
or says things like "let's work on X in the studio", "start the viewer", "make me a first
version I can look at".

## What the studio is

A local web app (`studio/` in the repo) that shows the active project's model in an
interactive three.js viewer and **hot-reloads within ~2 s whenever the model file changes
on disk**. The user orbits/zooms freely; their camera never resets on reload.

Start it (or confirm it's running), then give the user the link:

```
./start.sh                              # installs on first run, then opens the kid page
.venv/bin/python studio/server.py       # just the server  [--port N] [--projects <dir>]
→ http://localhost:8765/?project=<name>     (grown-up mode, one project)
→ http://localhost:8765/?kid=1              (kid mode)
```

It is also registered in `.claude/launch.json` as `studio`, so an agent with a browser
preview tool can open it and *see the same page the user sees*.

Settings (printer bed, slicer, image backend, models, what kid mode calls the helping adult)
come from `studio.config.json` via `studio/config.py` — never hard-code them. The server
re-reads the file when it changes, so `scripts/configure.py set …` needs no restart.
`GET /api/setup` returns the live picture of what is configured and what is missing.

## The loop

1. **Scaffold** — new idea: create `projects/<name>/` with `refs/`, copy
   `studio/design_template.py` → `projects/<name>/design.py`, adjust parameters/geometry,
   run it to produce `model.stl`. Hand the user the deep link. (Projects live in
   `projects/` unless `projects_dir` in the config points elsewhere; on first start an
   empty projects directory is seeded from `examples/`.)
2. **Steer** — the user looks at the live model and reacts. Inputs arrive several ways:
   - words ("the hook is too thick, halve it");
   - **captures**: they click 📸 in the viewer → `refs/capture_<n>.png` (the toast gives
     them the path to paste, but if they say "look at my capture", just read the newest
     `capture_*.png` in the project's `refs/`);
   - **dropped files**: images → `refs/`; STL/3MF files → `source/` (an STL dropped into a
     project with no live model auto-copies to `model.stl` and displays);
   - **🔗 url button**: imports a public URL — images → `refs/`, meshes → `source/`.
   Read those images. They are the ground truth for what the user means. When new refs
   appear, apply the image-to-model skill.
   The user can also create projects with the **+ new** button — an empty project
   appearing in `projects/` is an invitation to ask what they want built there.
3. **Edit & rerun** — change `design.py`, run it. The viewer reloads automatically —
   never tell the user to refresh. Iterate in small steps so they can react.
4. **Finish** — when they're happy: run the stl-prep inspect/repair pass, copy the
   deliverable to `final/<name>_<dim>mm.stl`, update `MANIFEST.md` if the repo keeps one,
   and quote slice settings per the k2-slicing skill (or the active printer's
   `printers/<slug>/profile.md` if it isn't a K2).

## What the viewer watches

- `projects/<name>/model.stl` — single-part live model, **or**
- `projects/<name>/parts/*.stl` — multi-part (CFS multi-color); optional
  `parts.json` maps `"<file>.stl": "#rrggbb"` for display colors (also good CFS planning).
  `parts/` takes precedence over `model.stl` when both exist.

When a project has no live model, the viewer falls back to displaying the newest
`final/*.stl`, then `source/*.stl`, with a "showing final/ — no live model yet" note —
so every project is browsable. Fallback files are display-only context; never edit files
in `final/` or `source/` in place.

The sidebar shows server-computed stats per reload: bbox mm, triangles, watertight badge,
a "fits <printer>" badge (against the design envelope = `printer.bed_mm` minus
`printer.margin_mm`; 255³ on the default Creality K2), volume. If watertight shows **NO**,
fix the mesh before any slicing talk.

The **🖨 slice** button opens the displayed model in the configured slicer
(`printer.slicer`). A project can override what it opens with a `slice.json`:
`{"open": ["final/thing_4color.3mf"]}` (a 3MF with the filaments already assigned, say), or
`{"open": [], "message": "why there's nothing to slice"}`.

## Parametric vs mesh-editing

- **Parametric (preferred for new designs, functional parts, connectors):** everything in
  `design.py` (trimesh + manifold3d booleans). Keep all dimensions as named parameters so
  "make it 2 mm wider" is a one-line edit.
- **Mesh editing (downloaded figurines/models):** no design.py; operate on the mesh with
  `skills/stl-prep/meshtools.py` (scale/rotate/addbase/hollow/split/repair) and write the
  result to `model.stl` — same hot-reload applies.
- **Image → first version:** read the image(s) in `refs/`, decide silhouette/relief/
  parametric interpretation, build a rough v1 fast, and let the user steer from there. A
  quick wrong-ish v1 in the viewer beats a slow perfect one.

## Gotchas

- Bed coordinates: keep the model at Z ≥ 0 with a positive XY footprint (template's export
  does this) so the bed grid and envelope box in the viewer (both drawn from
  `printer.bed_mm` / `margin_mm`) are honest.
- Export atomically when possible; the viewer debounces (two stable polls) so normal
  trimesh exports are fine.
- Server not running? `preview_start` name `studio`, `./start.sh`, or the command above.
  Port conflict: `--port <n>` and give the user the adjusted link.
- Don't leave test copies as `model.stl` when the session's real work lives elsewhere;
  the live model should always be the thing the user is iterating on.

## The kid flow and its API

The studio is also the front-end for a child's "ask → picture → pick → 3D → paint → print"
loop. Kid mode (`?kid=1`): the child taps 🎤 and *says* what they want (the browser's own
speech recognition; the studio itself never handles the audio) or types it, the studio
draws **4 picture options** (`options` in the config), they pick one, then either
**🪙 Make my coin!** (a traced multi-colour coin in seconds — see the token-coin skill) or
**Make me 3D** (a full toy built by headless Claude Code in ~5–15 min). They paint each part
with colour dots, and **🖨 Send to 3D printer** opens the slicer — "go get <grown-up>" from
there (`kid.grown_up` in the config). Kid mode reads its replies aloud with the browser's
speech synthesis (🔊/🔇 toggles it); the 🎤 button hides where the browser has no speech
recognition. What agents need to know:

- `POST /api/projects/<n>/generate`
  `{"subject": "...", "provider"?: "auto|claude|comfyui|nano", "style"?: "sticker|turnaround|chip", "count"?: 4}`
  writes `count` candidate images into `refs/` as `gen_<slug>.png`, `gen_<slug>_2.png`, …
  and answers `{"provider", "images": [{"file", "url", "title"}], "errors", "reply"}` —
  `reply` is the sentence kid mode reads aloud. Partial success is success. A backend that
  isn't set up answers 503 with `"setup": true` and a `fix`, instead of spinning — that
  includes a Claude CLI that turns out to be logged out and a rejected Gemini key. Kid mode
  always sends `provider: "auto"` (the configured backend); grown-up mode has radios.
  The three picture backends (`image_backend` in the config; `auto` = Nano Banana if a key
  exists, else a running ComfyUI, else Claude):
  - **`claude`** — the user's own Claude Code CLI, run headless (`claude -p`, model
    `claude.draw_model`, default Opus 5.5), one call per option, each with a different
    take (classic / extra cute / action pose / playful twist). Claude answers with an
    **SVG**; the server sanitises it, rasterises it to the PNG in `refs/`, and keeps the
    vector as **`vectors/<same stem>.svg`** — exact shapes and flat colours you can read
    instead of tracing pixels. Each option gets a kid-friendly `title`. ~20–60 s.
    What survives sanitising: the canvas is pinned to 1024×1024; no `script`, `image`,
    `foreignObject`, `pattern`, `filter`, `desc`, `title` or `metadata` elements, no `on*`
    handlers, no external `href` or `url()` (internal `url(#id)` stays). A stale SVG for a
    reused file name is renamed `<stem>.orphan.svg`.
  - **`comfyui`** — a local ComfyUI running Z-Image Turbo (`comfyui.url`, or probed on
    127.0.0.1 ports 8188/8000/8189; `scripts/setup_comfyui.sh` installs it and the
    models). Free per picture. comfy-cli's `running: false` is not authoritative — curl
    `/system_stats` on the port before concluding it's down.
  - **`nano`** — Google Nano Banana (`nano.model`; key in `$GEMINI_API_KEY` or the file
    `nano.key_file`).
  `style: "sticker"` = flat colours, no shading — what the coin tracer wants; kid mode
  sends it. `style: "turnaround"` = the same subject from the front, side and
  three-quarter — what a "Make me 3D" build wants; grown-up mode sends it. `style: "chip"`
  = one solid silhouette, for the one-colour chip tool. The prompts are in
  `studio/imagegen.py`.
- `POST /api/projects/<n>/make3d` `{"image": "<refs file>"}` — spawns the user's own
  `claude -p` (model `claude.build_model`, killed after `claude.build_timeout_min`) in this
  repo; it builds `design.py` → `model.stl` **and parts/*.stl split by colour region +
  parts/parts.json**. If YOU are that spawned instance: export a rough model early (a
  child is watching the viewer), then refine; the split into paintable parts is not
  optional — a merged mesh cannot be painted in the studio; size and sturdiness follow
  the printer envelope and `kid.ages` you were given. When the chosen picture has a
  vector (Claude-drawn pictures do), the server copies it into the build project's
  `vectors/<stem>.svg` and the prompt says so — read it for the exact outlines and colours.
  The build runs in its own project, named in the response's `"project"` (see "Builds are
  per (image, kind)" below) — poll **that** project: `GET /api/projects/<project>/make3d`
  reports progress, `POST /api/projects/<project>/make3d/cancel` stops it, and the log is
  that project's `.make3d.log`. (Asking the project you posted to, e.g. `library`, just
  answers `idle`.)
- `POST /api/projects/<n>/coin` `{"image": "<refs file>"}` — runs
  `studio/tools/make_coin.py` (no AI, ~1 s). See the token-coin skill.
- **Builds are per (image, kind)** — one picture can have BOTH a coin (`.../coin`) and a
  toy (`.../make3d`), each in its own project (`<image>_coin` / `<image>_toy`, recorded in
  the project's `.creation.json`). Requesting the same kind again reuses that project —
  that IS the redo (stale part STLs move to `projects/.archive/redo_parts/` first, so a
  failed redo loses nothing). `GET /api/library` lists every
  picture with its `builds: [{project, kind, has_model}]`.
- **Archive, never delete**: `POST /api/library/archive` `{"image": ...}` retires a
  picture, `POST /api/projects/<n>/archive` a whole project — both move things into
  `projects/.archive/` (hidden from the API; restore by moving the folder back).
  `library` refuses to archive.
- `POST /api/projects/<n>/colors` `{"part.stl": "#hex"}` — how the paint UI persists;
  `parts/parts.json` maps part file → display colour. **`parts/meta.json` is the print
  contract** where a project keeps one (colour-change layers and the like) — never write
  colours into meta.json or metadata into parts.json.
- `GET /api/setup` — config + readiness (`ready.pictures`, `ready.make3d`, `ready.coins`,
  `problems[{what, fix}]`); `scripts/doctor.py` prints the same checks in a terminal.
  Grown-up mode shows a setup banner when something isn't ready.
- `GET /api/projects/<n>/info` — mesh stats per part plus `parts[].fits_bed`,
  `combined.fits_bed` and `envelope_mm` (the printer bed minus `printer.margin_mm`).
- `GET /api/projects/<n>/make3d` — `state`, `elapsed`, `timed_out`, `timeout_min`,
  `wrote_files`, `log_tail`.
- First run: an empty projects folder is seeded once from `examples/` and marked with
  `<projects>/.seeded`; delete the marker to seed an empty folder again.
- The server answers only `localhost` / `127.0.0.1` / `[::1]` / `*.localhost` hosts and
  refuses cross-site POSTs (403); `STUDIO_ALLOWED_HOSTS=name[,name]` allows a tunnel.
- `POST /api/server/restart` — the server re-execs itself; use after editing server.py.
- Part positions in `parts/` are display-only (the slicer re-arranges) — lay parts out
  side by side rather than letting them overlap at the origin.
