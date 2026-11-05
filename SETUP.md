# SETUP.md — the runbook an agent follows

You are a coding agent and the user said something like *"set up
https://github.com/bradtaylorsf/3d-print-studio for me"*. Follow these steps in order. The
whole thing should cost the user **one message of answers** and, at most, one `/login`.
Run every command from the repo root and use absolute paths if your shell doesn't keep its
working directory between calls.

## 0. Get the repo

If the current directory already has `install.sh` and `SETUP.md`, you're in a checkout — skip
this. Otherwise clone it (default location `~/3d-print-studio`, unless the user named one):

```bash
git clone https://github.com/bradtaylorsf/3d-print-studio.git ~/3d-print-studio
cd ~/3d-print-studio
```

## 1. Ask the user — once, in ONE message

Send exactly these questions together, then wait. Don't start installing first and ask
later; don't split them across messages.

> Two quick questions before I install 3D Print Studio:
>
> **1. How should the studio draw pictures?**
>   1) **Claude Code (Opus 5.5)** — no GPU, no extra downloads; ~30 s for 4 pictures; uses your
>      Claude plan (≈ $0.07 a picture at API prices). *(recommended)*
>   2) **ComfyUI, on this computer** — free per picture and fully local; needs a GPU or Apple
>      Silicon and ~20 GB of models. Do you already run one (give me its URL), or should
>      I install it?
>   3) **Google Nano Banana** — fast; needs a Gemini API key (pay per picture).
>
> **2. What should kid mode call the grown-up who helps?** (e.g. "Mom", "Grandpa" — default
> "a grown-up"). Optional: how old are the kids? (default 5 to 9)
>
> Whichever you pick, coins need no AI and "Make me 3D" toys are built by your Claude Code.

If the user says "just do it" or doesn't care, use option 1 and the defaults.

## 2. Install

Run the installer non-interactively with their answers. `--yes` never starts the studio and
`--no-start` makes that explicit: you start it yourself in step 5, after the checks, so the
server doesn't tie up your shell.

```bash
# 1) Claude Code
./install.sh --images claude --yes --no-start --grown-up "Mom" --kid-ages "4 to 7"

# 2) ComfyUI — they already run one
./install.sh --images comfyui --comfyui-url http://127.0.0.1:8188 --yes --no-start --grown-up "Mom"

# 2) ComfyUI — install it (long: a ~20 GB download; use a long timeout or run it in the
#    background, and tell the user it's downloading)
./install.sh --images comfyui --install-comfyui --yes --no-start --grown-up "Mom"

# 3) Nano Banana — see the key note below first
./install.sh --images nano --yes --no-start --grown-up "Mom"
```

Leave out `--grown-up` / `--kid-ages` when they took the defaults. Quote names exactly as
given.

**Gemini key (option 3):** don't ask the user to paste an API key into chat. If
`GEMINI_API_KEY` is already set in their environment, the studio uses it when started from
that environment — but a studio launched from Finder or the Dock doesn't see shell variables,
so the key file is the reliable place. Ask the user to save it there **in their own terminal**,
either by running `./install.sh --images nano` (it asks for the key with hidden input) or with:

```bash
bash -c 'umask 077; mkdir -p ~/.config/3d-print-studio; read -rsp "Gemini API key: " k; echo; printf "%s\n" "$k" > ~/.config/3d-print-studio/gemini_key'
```

**Claude Code CLI missing:** the installer prints the official install command
(`curl -fsSL https://claude.ai/install.sh | bash`). It installs software from the internet, so
ask the user before you run it.

## 3. Check the Claude login

Make me 3D (and Claude pictures) run the user's `claude` CLI headless, which only works if it
is logged in **for headless use**:

```bash
.venv/bin/python scripts/doctor.py --deep
```

`--deep` makes one tiny real call to prove the login. If it reports *not logged in*, tell the
user: **open a terminal, run `claude`, type `/login`, and finish in the browser** — then re-run
the check. You can't log in for them, and a signed-in Claude desktop app doesn't count.

## 4. Fix what the doctor reports

`scripts/doctor.py` prints ✅/❌ lines, each failure with its fix; `--json` gives the same as
data (`problems[].what` / `problems[].fix`). It exits 0 when pictures, Make me 3D and coins are
ready; a missing slicer is only a warning. Apply the fixes, re-run, repeat. The common ones are
under [Troubleshooting](#troubleshooting).

## 5. Start the studio

```bash
./start.sh            # serves on port 8765 and opens http://localhost:8765/?kid=1
```

`start.sh` keeps running (it is the server), so start it in the background, in a terminal the
user can see, or with your preview tool — `.claude/launch.json` defines a `studio`
configuration (port 8765). Then open **http://localhost:8765/?kid=1**. To confirm it's up
without a browser:

```bash
curl -s http://localhost:8765/api/setup
```

## 6. Tell the user how to use it

Send them this, with their grown-up name filled in:

- **Talk or type:** tap **✨ I want…**, then **🎤 Tell me!** and say what you want (or type it
  and tap **🎨 Draw it!**). The studio draws 4 pictures.
- **Pick one**, then **🪙 Make my coin!** (ready in a second) or **🤖 Make me 3D** (a real toy,
  about 5–15 minutes).
- **Paint it:** tap a colour, then tap a part.
- **🖨️ Send to 3D printer!** opens it in the slicer — that's when the kid goes to get *Mom*.
  Grown-up mode (the 🧸 button toggles it) has the full controls.

Start it again any time with `./start.sh` (on a Mac: double-click `Studio.command`).

## 7. Optional: their printer

The repo ships tuned for a **Creality K2** with **Creality Print**. If they have a different
printer or slicer, run the `printer-setup` skill (in Claude Code: *"set up my printer"*). It
writes `printers/<slug>/profile.md` and sets the printer keys; the quick version is:

```bash
.venv/bin/python scripts/configure.py set printer.name "Prusa MK4" printer.bed_mm '[250,210,220]' printer.slicer "PrusaSlicer"
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Port 8765 is busy** ("Could not bind port") | If a studio is already running there, `./start.sh` says so and just opens http://localhost:8765/?kid=1. Something else on the port: `./start.sh --port 8766` (opens http://localhost:8766/?kid=1; the preview tool's `studio-8766` configuration does the same). |
| **"Not logged in"** in doctor, a 503 from pictures, or in `<project>/.make3d.log` | Run `claude` in a terminal and `/login`, then `.venv/bin/python scripts/doctor.py --deep`. The desktop app being signed in is not enough. |
| **Claude Code CLI not found** | `curl -fsSL https://claude.ai/install.sh \| bash` (with the user's OK), then `/login`. If it's installed somewhere unusual: `.venv/bin/python scripts/configure.py set claude.bin /path/to/claude`. |
| **ComfyUI is not answering** | One that `scripts/setup_comfyui.sh` installed: `./start.sh` launches it, but only when the studio isn't already running — stop the studio, then run `./start.sh` again. One the user runs themselves: they start it; if it isn't on 8188, 8000 or 8189, `.venv/bin/python scripts/configure.py set comfyui.url http://127.0.0.1:<port>`. Not installed: `bash scripts/setup_comfyui.sh`. |
| **ComfyUI is missing models** | `bash scripts/setup_comfyui.sh --models-only` (add `--workspace DIR` if ComfyUI isn't in `~/ComfyUI`). |
| **No Gemini API key** | Save it to `~/.config/3d-print-studio/gemini_key` (step 2), or switch: `.venv/bin/python scripts/configure.py set image_backend claude`. |
| **Slicer not found** | Install it, or point 🖨 at theirs: `.venv/bin/python scripts/configure.py set printer.slicer "OrcaSlicer"` (macOS app name, or a command/path on Linux). Files are in `projects/<name>/final/` either way. |
| **Python too old / no venv module** | Install Python 3.10+ (macOS: `brew install python@3.12`; Debian/Ubuntu: `sudo apt install python3 python3-venv`), then re-run `./install.sh`. |
| **Python packages missing** | `./install.sh` again (or `.venv/bin/pip install -r requirements.txt`). |
| **Pictures are very slow on ComfyUI** | It's running on CPU. Use a GPU / Apple Silicon machine, or switch to `claude`. |
| **403 "Host '…' refused"** or **"cross-site request refused"** | Open http://localhost:8765/ (not a LAN IP or tunnel URL). Behind a tunnel or port-forwarder the user set up, start the studio with `STUDIO_ALLOWED_HOSTS=<that hostname> ./start.sh`. |
| **A build "took too long"** | Builds stop after `claude.build_timeout_min` (default 30). For quicker, simpler toys: `.venv/bin/python scripts/configure.py set claude.build_model sonnet`. |
| **The doctor names a config key as "not valid"** | A hand edit has the wrong type (`"options": "four"`); the studio is using the default meanwhile. Fix it in `studio.config.json`, or `.venv/bin/python scripts/configure.py unset <key>`. |
| **Agents: is it ready?** | `install.sh` exits 0 even when the doctor finds problems — read its report, or `.venv/bin/python scripts/doctor.py --json`. Start the studio without opening a browser with `./start.sh --no-browser` (or `STUDIO_NO_BROWSER=1`). Preview ComfyUI's install with `bash scripts/setup_comfyui.sh --dry-run`. |

Everything is safe to re-run: `./install.sh` never clobbers settings it wasn't asked to change,
and `.venv/bin/python scripts/configure.py show` prints the effective config.
