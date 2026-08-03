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

## Setup (5 minutes)

Requirements: Python 3.10+, [Claude Code](https://claude.com/claude-code), a 3D printer's
slicer installed locally. macOS is tested; Linux works except the one-click slicer button.

```bash
git clone https://github.com/bradtaylorsf/3d-print-studio.git
cd 3d-print-studio
python3 -m venv .venv
.venv/bin/pip install trimesh manifold3d numpy scipy shapely matplotlib pillow opencv-python-headless scikit-image
```

Start the studio:

```bash
.venv/bin/python studio/server.py
```

Open http://localhost:8765/ — that's the whole stack. three.js is vendored in
`studio/static/three/`; there is no npm install, no build step, no cloud dependency.

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
