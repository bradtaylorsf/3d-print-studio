# 3D Print Studio

A kid says what they want. The studio draws **4 pictures**, they pick one, and it becomes a
**printable coin in a second** or a **3D toy in a few minutes** — painted, and opened in your
slicer. It runs on your own computer, with your own Claude Code (and, if you like, a local
ComfyUI or Google's Nano Banana for the pictures).

```
kid:     🎤 "a dragon eating a taco!"
studio:  draws 4 options (~30 s) and says "I drew 4 pictures of a dragon eating a taco!
         Which one do you like best?"
kid:     taps the round, happy one
kid:     🪙 Make my coin!  → a 28 mm multi-colour coin, ~1 s, traced, no AI
   or    🤖 Make me 3D     → headless Claude Code (Opus 5.5) builds a chunky toy, ~5–15 min
kid:     taps a colour, taps a part — paints it
kid:     🖨️ Send to 3D printer! → it opens in the slicer: "Go get a grown-up to help you from here."
```

Grown-ups get the same studio as a design workspace: drop in a reference picture, let your
coding agent write a parametric `design.py`, watch the model hot-reload in a live viewer, and
steer with words and screenshots. No mesh-editing GUI required.

## Set it up with your agent

Paste this into Claude Code, Codex, or any coding agent that can run commands:

```
Set up https://github.com/bradtaylorsf/3d-print-studio for me — follow its SETUP.md.
```

The agent clones the repo, asks you **one question** — who should draw the pictures (Claude
Code, a local ComfyUI, or Nano Banana) — plus what kid mode should call you, then installs,
checks everything, and opens the studio. Allow ~5 minutes (the ComfyUI route adds a ~20 GB
download). [`SETUP.md`](SETUP.md) is the exact runbook it follows.

## Or install it yourself

```bash
git clone https://github.com/bradtaylorsf/3d-print-studio.git
cd 3d-print-studio
./install.sh
```

Or in one line (clones into `~/3d-print-studio`, or `$STUDIO_DIR`, then runs the installer):

```bash
curl -fsSL https://raw.githubusercontent.com/bradtaylorsf/3d-print-studio/main/install.sh | bash
```

The installer checks git and Python, creates `.venv`, installs `requirements.txt`, finds (or
offers to install) the Claude Code CLI, asks how to draw pictures, writes
`studio.config.json`, and runs the setup doctor. It is safe to re-run — that's also how you
update (`git pull && ./install.sh`) or switch picture backends. To uninstall, delete the
folder (plus `~/.config/3d-print-studio/`, `~/ComfyUI` if the installer put it there, and
`~/Applications/3D Print Studio.app` if you made one).

Then start it any time:

```bash
./start.sh            # opens http://localhost:8765/?kid=1
./start.sh --port 8766 --no-browser   # another port; don't open a browser
```

On a Mac you can **double-click `Studio.command`** in Finder instead, or run
`studio/make_app.sh` once to get a **3D Print Studio.app** for your Dock.

### Installer flags

Everything the interactive installer asks can be passed as flags — this is what agents use:

```bash
./install.sh --images claude --yes --grown-up "Mom" --kid-ages "4 to 7"
```

| Flag | What it does |
|---|---|
| `--images claude\|comfyui\|nano\|auto` | Who draws the pictures (skips the question) |
| `--yes`, `-y` | No questions: anything not given keeps its current value (or the default on a first install) |
| `--grown-up "NAME"` | What kid mode calls the helping adult ("Go get Mom to help you from here.") — default `a grown-up` |
| `--kid-ages "4 to 7"` | Who the toys are for; shapes the drawings and how chunky the builds are — default `5 to 9` |
| `--comfyui-url URL` | Use a ComfyUI you already run (e.g. `http://127.0.0.1:8188`) |
| `--install-comfyui` | Install ComfyUI and the Z-Image Turbo models (~20 GB) via `scripts/setup_comfyui.sh` |
| `--comfyui-workspace DIR` | Where ComfyUI lives, or goes (default `~/ComfyUI`) |
| `--python PATH` | The Python 3.10+ to build `.venv` with (or `STUDIO_PYTHON=…`) |
| `--start` / `--no-start` | Start the studio when the install finishes, or don't (default: ask; `--yes` never starts it) |
| `-h`, `--help` | Every option |

With the curl one-liner, pass flags after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/bradtaylorsf/3d-print-studio/main/install.sh | bash -s -- --images claude --yes
```

## Who draws the pictures?

You pick once at install; grown-up mode can also switch per ask. Whatever you pick, **coins
need no AI at all**, and **Make me 3D always uses your Claude Code CLI**.

| | **Claude Code (Opus 5.5)** — default | **ComfyUI** on this computer | **Nano Banana** (Google) |
|---|---|---|---|
| Speed, 4 pictures | ≈ 25–35 s (drawn in parallel) | ≈ 1–2 min on Apple Silicon (one after another); much slower on CPU | ≈ 10–20 s |
| Cost | Uses your Claude plan's usage; ≈ $0.07 a picture at API list price | Free per picture | Pay-per-picture on your Gemini API key (check Google's current pricing) |
| Hardware | None — no GPU, no downloads | A GPU or Apple Silicon, ~20 GB of models | None |
| Needs | Claude Code CLI, logged in | ComfyUI + Z-Image Turbo (the installer can set both up) | A Gemini API key |
| Style | Flat vector sticker art, with a short name per option — traces cleanly into coins | Illustrated sticker art | Illustrated sticker art, the most detailed |
| Your words go to | Anthropic, through your own CLI | Nowhere — stays on your machine | Google |

Each Claude picture is a separate headless `claude -p` call with a different take (classic,
extra cute, action pose, surprise twist). Claude answers with an SVG, which the studio
sanitizes and rasterizes; the SVG is kept in `vectors/` so a Make me 3D build can read the
exact shapes and colours.

## Requirements

- **Python 3.10+** and **git**
- **[Claude Code](https://claude.com/claude-code)**, logged in for headless use: run `claude`
  once in a terminal and `/login`. (A signed-in Claude desktop app is not enough.) The
  installer offers to install the CLI if it's missing.
- **A slicer** for the 🖨 button — Creality Print by default; any slicer works
  (`printer.slicer`).
- **macOS** is tested; **Linux** works; **Windows** via WSL.
- For voice: a browser with speech recognition (Chrome, Edge, Safari). Firefox works with
  typing.

## Kid mode 🧸

Open `http://localhost:8765/?kid=1` (`./start.sh` opens it for you), or click **🧸** in
grown-up mode.

1. **✨ I want…**, then **🎤 Tell me!** — tap and talk (the words appear as they speak, and
   when they stop the studio starts drawing), or type it and tap **🎨 Draw it!**.
2. **Pick your favorite** — 4 pictures in a 2×2 grid (with a short name under each when Claude
   drew them). The studio reads its reply out loud (🔊/🔇 toggles the voice).
3. **🪙 Make my coin!** — about a second, no AI: the picture is traced into a 28 mm coin with up
   to 4 colour regions. Or **🤖 Make me 3D** — a headless Claude Code session builds a chunky,
   support-free toy split into paintable parts; a banner counts while it works and the model
   hot-loads when it lands (~5–15 min).
4. **Paint it** — tap a colour, tap a part. Colours are saved with the project.
5. **🖨️ Send to 3D printer!** — opens the model in your slicer and tells them to go get the
   grown-up.

One picture can have both a coin and a toy; its tile shows a 🪙/🤖 badge per build, and the
buttons flip to **Redo** when that kind exists. Grown-up mode adds the backend picker, a setup
banner when something needs fixing, a **3d files** browser, and 🗂 archive buttons (archiving
moves things to `projects/.archive/` — nothing is ever deleted).

## Designing with your agent

Run your agent in the repo folder (`claude`). [`AGENTS.md`](AGENTS.md) is its contract and
`skills/` are its methods: the studio iterate loop, image → model, coins, slicing and supports,
mesh repair, troubleshooting, printer onboarding, contributing.

```
you:     [drops a photo of a ring onto the page]
you:     "make me this, size 7"
agent:   writes projects/ring/design.py, runs it
viewer:  hot-reloads the model — you orbit it, hit 📸 on the angle that's wrong
you:     "the cracks are too symmetrical"
agent:   edits one function, reruns — the viewer updates in ~2 s, camera stays put
you:     "finish it" → repaired, verified, exported to final/, slicer settings quoted
you:     [clicks 🖨 slice] → the model opens in your slicer
```

In Claude Code, `/setup` re-runs the guided setup, and *"set up my printer"* starts printer
onboarding.

## Check your setup

```bash
.venv/bin/python scripts/doctor.py           # ✅/❌ for each check, with the fix
.venv/bin/python scripts/doctor.py --deep    # + one tiny real Claude call to prove the login works
.venv/bin/python scripts/doctor.py --json    # machine-readable, for agents
```

It exits 0 when pictures, Make me 3D and coins are all ready (a missing slicer is only a
warning). It runs before the install too — `python3 scripts/doctor.py`. The studio shows the
same report at `GET /api/setup`.

Adding ComfyUI later, or fetching its models again: `bash scripts/setup_comfyui.sh` —
`--url URL` uses one that's already running, `--workspace DIR` (default `~/ComfyUI`),
`--gpu auto|m-series|nvidia|amd|cpu`, `--models-only`, `--no-launch`, `--yes`, and `--dry-run`
(shows every step and download, changes nothing).

## Configuration

`studio.config.json` at the repo root, per machine and gitignored; `install.sh` creates it
from [`studio.config.example.json`](studio.config.example.json). Precedence is
**defaults < `studio.config.json` < environment**, and the server re-reads the file when it
changes — no restart needed. Edit it by hand or with `scripts/configure.py`:

```bash
.venv/bin/python scripts/configure.py show                       # the effective config
.venv/bin/python scripts/configure.py get printer.bed_mm
.venv/bin/python scripts/configure.py set image_backend nano kid.grown_up "Grandpa"
.venv/bin/python scripts/configure.py unset comfyui.url             # back to the default (probe the ports)
.venv/bin/python scripts/configure.py path                         # where the config file is
```

A hand-edited value of the wrong type (`"options": "four"`) falls back to its default, and the
doctor and the setup banner say which key it was.

| Key | Default | What it does |
|---|---|---|
| `image_backend` | `"claude"` (written by `install.sh`) | Who draws: `claude`, `comfyui`, `nano`, or `auto` (Nano Banana if a key exists, else a running ComfyUI, else Claude). A config without this key means `auto` |
| `options` | `4` | Pictures per ask (1–8) |
| `projects_dir` | `""` | Where projects live; empty = `projects/` in the repo |
| `claude.bin` | `""` | Path to the `claude` CLI; empty = `PATH`, the usual install locations, then the Claude desktop app's copy |
| `claude.draw_model` | `"claude-opus-5-5"` | Model that draws the pictures |
| `claude.build_model` | `"claude-opus-5-5"` | Model that builds Make me 3D toys |
| `claude.build_timeout_min` | `30` | A build still running after this is stopped (Opus builds take ~5–20 min) |
| `comfyui.url` | `""` | ComfyUI address; empty = probe `127.0.0.1` ports 8188, 8000, 8189 |
| `comfyui.workspace` | `""` | The ComfyUI folder, set by `setup_comfyui.sh`; when that script installed ComfyUI, `start.sh` launches it for you |
| `comfyui.unet` | `"z_image_turbo_bf16.safetensors"` | Z-Image Turbo diffusion model |
| `comfyui.clip` | `"qwen_3_4b.safetensors"` | Text encoder |
| `comfyui.vae` | `"z_image_ae.safetensors"` | VAE (upstream's `ae.safetensors` is accepted too) |
| `comfyui.steps` | `8` | Sampling steps |
| `nano.model` | `"gemini-2.5-flash-image"` | Gemini image model |
| `nano.key_file` | `"~/.config/3d-print-studio/gemini_key"` | File holding the Gemini key (one line) |
| `printer.name` | `"Creality K2"` | Shown in the viewer ("fits Creality K2") |
| `printer.bed_mm` | `[260, 260, 260]` | Build volume X, Y, Z in mm — sizes the viewer grid and the fit check |
| `printer.margin_mm` | `5` | Design envelope = bed − margin (255³ on a K2) |
| `printer.slicer` | `"Creality Print"` | What 🖨 opens: a macOS app name, or a command/path on Linux |
| `kid.grown_up` | `"a grown-up"` | What kid mode calls the helping adult |
| `kid.ages` | `"5 to 9"` | Who the toys are for |

Environment overrides: `STUDIO_IMAGE_BACKEND`, `STUDIO_OPTIONS`, `STUDIO_PROJECTS_DIR`,
`STUDIO_CLAUDE_BIN`, `STUDIO_DRAW_MODEL`, `STUDIO_MAKE3D_MODEL`, `STUDIO_COMFYUI_URL`,
`STUDIO_NANO_MODEL`, `STUDIO_SLICER_APP`, `STUDIO_GROWN_UP`, and `STUDIO_CONFIG` (path of the
config file). The Gemini key is read from `GEMINI_API_KEY` or `GOOGLE_API_KEY` before
`nano.key_file` — but a studio launched from Finder or the Dock doesn't see your shell's
variables, so the key file is the reliable place.

The launcher, installer and server read a few more: `PORT` and `STUDIO_NO_BROWSER=1`
(`start.sh`), `STUDIO_DIR` and `STUDIO_REPO_URL` (`install.sh`, for a fork), `STUDIO_MODELS_URL`
(`setup_comfyui.sh`, a model mirror), and `STUDIO_ALLOWED_HOSTS` (the server — see below).

## Safety & privacy

- **Local only.** The server listens on `127.0.0.1` — other devices on your network can't
  reach it. It also answers only requests addressed to `localhost` / `127.0.0.1` / `[::1]` /
  `*.localhost`, and refuses POSTs from any other web page, including other local dev servers
  (CSRF and DNS-rebinding protection: Make me 3D runs an agent with permission prompts off).
  Behind a tunnel or port-forwarder you set up yourself, allow its hostname with
  `STUDIO_ALLOWED_HOSTS=name[,name]`. The studio has no accounts, analytics or telemetry.
  Projects stay in your projects folder, which this repo gitignores.
- **What leaves your computer:** a picture request goes only to the backend you chose
  (Anthropic through your Claude Code, Google for Nano Banana, nowhere for ComfyUI). Make me
  3D sends the chosen picture and the build instructions through your Claude Code; the build
  agent keeps Claude Code's built-in tools, so it may also search or fetch the web. Coins are
  traced entirely on your machine. Importing from a 🔗 url fetches that url.
- **Make me 3D runs an agent with permission prompts off.** Each build is a headless
  `claude -p` session with `--permission-mode bypassPermissions`, working in this repo as
  your user. Its instructions keep it inside the project folder, but that's an instruction,
  not a sandbox. Run the studio on a computer and account you're comfortable with; every
  build's log is in `<project>/.make3d.log`, and builds stop after `claude.build_timeout_min`.
- **Filtering kids' requests is the drawing model's job.** The Claude prompt tells it to draw
  a friendly, wholesome version of anything that isn't right for young children; Nano Banana
  has Google's safety filters; **a local ComfyUI has no filter** — it draws what the words
  say. Keep a grown-up nearby.
- **Voice** uses the browser's own speech recognition. The studio never receives or stores
  audio, but the browser's engine may: Chrome sends speech to Google's servers, Safari to
  Apple's. Typing works everywhere. Read-aloud uses the browser's built-in voices.
- **Usage:** Claude pictures and Make me 3D builds count against your Claude plan (or your
  API bill, if your CLI is logged in with an API key). A build is a full agent session —
  minutes of Opus — so it uses far more than a picture.

## Printers

The repo ships tuned for a **Creality K2** (260 × 260 × 260 mm, CFS multi-colour) with
**Creality Print 7.1.1** and **PLA**: the `k2-slicing`, `k2-supports` and
`print-troubleshooting` skills and [`printers/creality-k2/profile.md`](printers/creality-k2/profile.md).
Any FDM printer works. Tell your agent *"set up my printer"*: the `printer-setup` skill
interviews you, researches the machine, writes `printers/<slug>/profile.md` (slug = the printer name, lowercased with hyphens, e.g. `creality-k2`), and sets the
`printer.*` keys — or set them yourself:

```bash
.venv/bin/python scripts/configure.py set printer.name "Prusa MK4" printer.bed_mm '[250,210,220]' printer.slicer "PrusaSlicer"
```

## What's in the box

| Path | What it is |
|---|---|
| `install.sh`, `start.sh`, `Studio.command` | Install, start, and the Finder double-click launcher |
| `studio/` | The studio: a zero-dependency Python server, the three.js viewer (vendored — no CDN, no build step), the picture backends (`imagegen.py`), the coin tracer (`tools/`), and `config.py` |
| `scripts/` | `doctor.py`, `configure.py`, `setup_comfyui.sh`, `smoke_test.py`, `check_privacy.py` |
| `skills/` | The agent skills (plain markdown); symlinked into `.claude/skills/` for Claude Code |
| `printers/` | One knowledge base per printer |
| `examples/` | Starter projects copied into an empty projects folder on first run |
| `projects/` | Your creations, one folder per model (gitignored) |
| `AGENTS.md`, `CLAUDE.md`, `SETUP.md` | Instructions for agents |

## Contributing

This project runs **problem-first**: PRs that start from a demonstrated problem get merged;
PRs that start from a solution looking for a problem usually don't. In Claude Code say
*"I want to contribute"*, or read [`skills/contributing/SKILL.md`](skills/contributing/SKILL.md):
problem → research → hypothesis → smallest experiment → build & verify → PR.

House rules: stdlib-only server, no build step, no npm, skills as plain markdown, Python
3.10+. Before a PR, run `python3 scripts/smoke_test.py` (starts the server on a throwaway
projects folder and pokes every core endpoint, spending nothing) and
`python3 scripts/check_privacy.py` (flags home-directory paths and personal files).

Good first contributions: profiles for more printers (`printer-setup` output), new
image → model strategies, Windows slicer-button support, a Web Worker STL parser.

## License & credits

[MIT](LICENSE). An independent hobby project — not an official product of, or endorsed by,
Anthropic, Google, Creality or the ComfyUI project. Product names are their owners'
trademarks.

Built on: [Claude Code](https://claude.com/claude-code) (bring your own CLI and plan) ·
[three.js](https://threejs.org) (MIT, vendored in `studio/static/three/`) ·
[trimesh](https://trimesh.org) · [manifold3d](https://github.com/elalish/manifold) ·
[resvg](https://github.com/linebender/resvg) via `resvg_py` · [OpenCV](https://opencv.org) ·
[scikit-image](https://scikit-image.org) · [Shapely](https://shapely.readthedocs.io) ·
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) +
[Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo) (installed separately, under
their own licenses) · Google's Gemini image model ("Nano Banana").
