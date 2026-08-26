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
.venv/bin/python studio/server.py
→ http://localhost:8765/?project=<name>
```

It is also registered in `.claude/launch.json` as `studio`, so Claude can open it with the
browser preview tool and *see the same page the user sees*.

## The loop

1. **Scaffold** — new idea: create `projects/<name>/` with `refs/`, copy
   `studio/design_template.py` → `projects/<name>/design.py`, adjust parameters/geometry,
   run it to produce `model.stl`. Hand the user the deep link.
2. **Steer** — the user looks at the live model and reacts. Inputs arrive several ways:
   - words ("the hook is too thick, halve it");
   - **captures**: the user clicks 📸 in the viewer → `refs/capture_<n>.png` (the toast gives them
     the path to paste, but if they say "look at my capture", just read the newest
     `capture_*.png` in the project's `refs/`);
   - **dropped files**: images → `refs/`; STL/3MF files → `source/` (an STL dropped into a
     project with no live model auto-copies to `model.stl` and displays);
   - **🔗 url button**: imports a public URL — images → `refs/`, meshes → `source/`.
   Read those images. They are the ground truth for what they mean. When new refs appear,
   apply the image-to-model skill.
   The user can also create projects themselves with the **+ new** button — an empty project
   appearing in `projects/` is an invitation to ask what they want built there.
3. **Edit & rerun** — change `design.py`, run it. The viewer reloads automatically —
   never tell the user to refresh. Iterate in small steps so they can react.
4. **Finish** — when they're happy: run the stl-prep inspect/repair pass, copy the deliverable
   to `final/<name>_<dim>mm.stl`, update `MANIFEST.md`, and quote K2 slice settings per
   the k2-slicing skill.

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
fits-295³ badge, volume. If watertight shows **NO**, fix the mesh before any slicing talk.

## Parametric vs mesh-editing

- **Parametric (preferred for new designs, functional parts, connectors):** everything in
  `design.py` (trimesh + manifold3d booleans). Keep all dimensions as named parameters so
  "make it 2 mm wider" is a one-line edit.
- **Mesh editing (downloaded figurines/models):** no design.py; operate on the mesh with
  `skills/stl-prep/meshtools.py` (scale/rotate/addbase/hollow/split/repair) and write the
  result to `model.stl` — same hot-reload applies.
- **Image → first version:** read the image(s) in `refs/`, decide silhouette/relief/
  parametric interpretation, build a rough v1 fast, and let the user steer from there. A quick
  wrong-ish v1 in the viewer beats a slow perfect one.

## Gotchas

- Bed coordinates: keep the model at Z ≥ 0 with a positive XY footprint (template's export
  does this) so the 300×300 grid and 295³ envelope in the viewer are honest.
- Export atomically when possible; the viewer debounces (two stable polls) so normal
  trimesh exports are fine.
- Server not running? `preview_start` name `studio`, or the command above. Port conflict:
  `--port <n>` and give the user the adjusted link.
- Don't leave test copies as `model.stl` when the session's real work lives elsewhere;
  the live model should always be the thing the user is iterating on.

## The kid flow and the generate/make3d API (added 2026-08-25)

The studio is now also the front-end for the kids' "ask → picture → 3D → paint → print"
loop. What agents need to know:

- `POST /api/projects/<n>/generate` `{"subject": "...", "provider": "auto|nano|comfy",
  "style": "turnaround|chip"}` — writes candidate images into `refs/`. `nano` is Nano
  Banana (`gemini-2.5-flash-image`, key in `$GEMINI_API_KEY` or
  `~/.config/3d-prints/gemini_key`); `comfy` is the local ComfyUI probed on **ports
  8000/8188/8189** — one known install runs on **8000**, and comfy-cli's `running: false` is not
  authoritative about it.
- `POST /api/projects/<n>/make3d` `{"image": "<refs file>"}` — spawns a headless
  `claude -p` in this repo that builds `design.py` → `model.stl` **and parts/*.stl split
  by colour region + parts/parts.json**. If YOU are that spawned instance: the split into
  paintable parts is not optional — a merged mesh cannot be painted in the studio.
- `POST /api/projects/<n>/colors` `{"part.stl": "#hex"}` — how the paint UI persists;
  `parts/parts.json` maps part file → display colour. **`parts/meta.json` is the print
  contract** (coin_board keeps its colour-change data there) — never write colours into
  meta.json or metadata into parts.json.
- `POST /api/server/restart` — the server re-execs itself; use after editing server.py.
- Part positions in `parts/` are display-only (the slicer re-arranges) — lay parts out
  side by side rather than letting them overlap at the origin.
