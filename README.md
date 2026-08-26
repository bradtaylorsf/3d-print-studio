# 3D Print Studio

A local, Claude Code–native workspace for designing 3D-printable models by **iterating with
an AI sidekick in a live viewer** — drop in a reference image, get a parametric first
version in minutes, steer it with words and screenshots, then send it to your slicer with
one click.

```
you:    [drops photo of a ring onto the web page]
you:    "make me this, size 7"
claude: writes projects/ring/design.py, runs it
viewer: hot-reloads the model — you orbit it, hit 📸 on the angle that's wrong
you:    "the cracks are too symmetrical"
claude: edits one function, reruns — viewer updates in ~2s, camera stays put
you:    [clicks 🖨 slice] → model opens in your slicer
```

No mesh-editing GUI required. The geometry source of truth is a small Python script per
project that Claude (or you) edits.

## What's in the box

| Path | What it is |
|---|---|
| `studio/` | The viewer: a zero-dependency Python server + three.js page (vendored, no CDN/build step) |
| `projects/<name>/` | One folder per model: `design.py`, live `model.stl`, `refs/`, `source/`, `final/`, `previews/` |
| `skills/` | Claude Code skills: the iterate loop, image→model, slicing, supports, mesh repair, troubleshooting, printer onboarding, contributing |
| `MANIFEST.md` | Index of every project and its status |
| `CLAUDE.md` / `AGENTS.md` | Instructions Claude Code (or any agent) loads to work in this repo |

## Setup

Requirements: Python 3.10+, [Claude Code](https://claude.com/claude-code), a 3D printer's
slicer installed locally. macOS is tested; Linux works except the one-click slicer button.

```bash
git clone https://github.com/bradtaylorsf/3d-print-studio.git
cd 3d-print-studio
./start.sh
```

That's it. First run sets up the Python environment (a few minutes); every run after starts
the server and opens http://localhost:8765/ in your browser. On a Mac you can also just
**double-click `Studio.command` in Finder** — same thing, no terminal needed.

### Running on another computer

Everything that matters travels with the repo — the studio, every project, the picture
library, the creations, the skills. `git clone` + `./start.sh` is the whole setup. The
few things that are per-machine:

- **Make-me-3D builds** spawn a headless `claude -p` session. The studio finds the CLI
  on PATH, via `$STUDIO_CLAUDE_BIN`, or bundled inside the Claude desktop app — but the
  CLI must be **logged in for headless use** on this machine: run `claude` in any
  terminal once and `/login`. (The desktop app being signed in is NOT enough — a build
  that dies instantly with "Not logged in" in `.make3d.log` means exactly this.)
- **Picture generation** needs either a Gemini key in `$GEMINI_API_KEY` or
  `~/.config/3d-prints/gemini_key` (Nano Banana), or a local ComfyUI answering on
  port 8000/8188 (Z-Image Turbo stack). With neither, the library and coins still
  work — you just can't draw NEW pictures.
- **🖨 Send to printer** opens Creality Print, so that machine needs it installed.

There is no npm install, no build step, no cloud dependency — three.js is vendored in
`studio/static/three/`.

**Want a Dock icon?** Run `studio/make_app.sh` — it builds **3D Print Studio.app** into
`~/Applications` (icon and all, from `studio/static/icon.svg`). Drag it to your Dock or
launch it from Spotlight/Alfred; it starts the server if needed and opens the page.

### Kid mode 🧸

Click the **🧸** button (or open `http://localhost:8765/?kid=1`) and the UI becomes the
kid flow — big buttons, no jargon:

1. **✨ I want…** — they say what they want, the studio draws it (Nano Banana if a key
   is present, else the local ComfyUI): a turnaround sheet, three views of a chunky toy
   version, two or three candidates to choose from.
2. **Pick your favorite** — tap a picture.
3. **✨ Make me 3D!** — a headless Claude instance builds `design.py` → `model.stl` from
   the chosen image, split into colourable parts. A banner counts while the robot works;
   the model hot-loads into the viewer when it lands.
4. **Paint it** — pick a color dot, tap a part. Colors persist to `parts/parts.json`.
5. **🖨️ Send to 3D printer!** — opens the model in Creality Print, then tells them:
   *"Go get a grown-up to help you from here."*

One picture can have **both a coin and a toy** — each build gets its own project
(`<image>_coin` / `<image>_toy`), and the picture's tile shows a 🪙/🤖 badge per build.
Open a picture and the pane lists its builds (*see my coin*, *see my toy*); the make
buttons flip to **Redo** when that kind already exists and rebuild it in place. In
grown-up mode the pane also has 🗂 archive buttons — for the picture or any of its
builds — which move things to `projects/.archive/` (nothing is ever deleted; move it
back by hand to restore).

Grown-up mode keeps the full controls, plus a **3d files** browser in the sidebar (click
any parts/final/source STL to view it, ⬅ back to live), a ✕ on the image pane, and the
same ✨ generate / 🤖 make-3D buttons.

**Nano Banana:** put a Gemini API key in `$GEMINI_API_KEY` or
`~/.config/3d-prints/gemini_key` (one line, the key). Without it, generation falls back
to the local ComfyUI automatically (Z-Image Turbo, ~30 s for two candidates — ComfyUI
must be running; the studio probes ports 8000/8188/8189).

## Getting started

1. **Run Claude Code in the repo folder** (`claude`). It picks up `CLAUDE.md` and the skills.
2. **Onboard your printer** (first time): say *"set up my printer"* — the `printer-setup`
   skill interviews you, researches your machine, and writes a `printers/<model>/`
   knowledge base. (This repo ships tuned for a Creality K2 + Creality Print; that's all
   replaceable.)
3. **Start designing**: ask Claude to *"start the studio"*, then either
   - click **+ new** in the page, drop in an image (or use **🔗 url**), and tell Claude to
     take a look, or
   - just describe what you want in chat.
4. **Steer**: orbit the live model, click **📸 capture** on anything wrong and tell Claude
   what you see. Every change hot-reloads without resetting your camera.
5. **Print**: say *"finish it"* — Claude repairs/verifies the mesh, exports to `final/`,
   and quotes slicer settings. **🖨 slice** opens the model in your slicer.

### Notes for agents

You are expected to do the geometry work yourself — `AGENTS.md` is your contract. In short:
inspect meshes before advising, keep `design.py` parametric (dimensions as named constants),
work in bed coordinates (Z ≥ 0), verify watertightness before calling anything print-ready,
and read the relevant `skills/*/SKILL.md` before acting. The studio server's API
(`studio/server.py` docstring) lets you see exactly what the user sees.

## Contributing

This project runs **problem-first**: PRs that start from a demonstrated problem get merged;
PRs that start from a solution looking for a problem usually don't.

The workflow is packaged as a skill — in Claude Code, say *"I want to contribute"* or read
[`skills/contributing/SKILL.md`](skills/contributing/SKILL.md) yourself. It walks you (or
your agent) through the lifecycle:

1. **Problem** — write down who hurts, when, with evidence (a transcript, a failed print, a
   confusing session). No solutions yet.
2. **Research** — check existing skills/code/issues; reproduce the problem locally.
3. **Hypothesis** — *"We believe \<change\> will \<outcome\>, measured by \<signal\>."*
4. **Smallest experiment** — the least code that tests the hypothesis.
5. **Build & verify** — match repo conventions (stdlib-only server, no build step,
   skills as plain markdown); prove it works end-to-end.
6. **PR** — the skill generates the branch, commit, and a PR body that carries the
   problem/hypothesis/evidence, so review starts from *why*, not *what*.

Good first contributions: profiles for more printers (`printer-setup` output), new
image→model strategies, Linux/Windows slicer-button support, a Web Worker STL parser.

## License & credits

Built with [Claude Code](https://claude.com/claude-code). Viewer uses
[three.js](https://threejs.org) (MIT, vendored). Mesh tooling:
[trimesh](https://trimesh.org) + [manifold3d](https://github.com/elalish/manifold).
