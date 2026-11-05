---
name: setup
description: >-
  Install and configure 3D Print Studio for a new user, end to end: clone if needed, ask the
  one picture-backend question (Claude Code / local ComfyUI / Nano Banana) plus the grown-up's
  name in a single message, run install.sh non-interactively, verify the Claude Code login with
  scripts/doctor.py --deep, fix what the doctor reports, start the studio, and explain kid mode.
  Use on first run (no .venv or no studio.config.json), or when the user says "set up",
  "set this up", "install", "get started", "first run", "/setup", "switch to ComfyUI",
  or "the pictures don't work".
---

# setup — get a new user from clone to kid mode

**Follow [`SETUP.md`](../../SETUP.md) step by step.** It is the runbook; this skill only adds
the rules that matter most when you're the one running it. It is for a session with a person
in it: a headless "Make me 3D" build never runs it, even if the config looks missing.

1. **One message of questions.** The picture backend (with the one-line trade-off for each)
   and the grown-up's name — optionally the kids' ages — together, using SETUP.md's wording.
   No drip-fed follow-ups. "Just do it" means Claude Code and the defaults.
2. **Run the installer non-interactively:**
   `./install.sh --images <claude|comfyui|nano> --yes --no-start [--grown-up "<name>"] [--kid-ages "<ages>"] [--comfyui-url URL | --install-comfyui]`.
   `--install-comfyui` downloads ~20 GB — give it a long timeout or run it in the background,
   and tell the user it's downloading.
3. **Never handle secrets in chat.** A Gemini key goes into
   `~/.config/3d-print-studio/gemini_key` by the user's own hand (SETUP.md has the command).
   Installing the Claude Code CLI fetches software from the internet: ask first.
4. **You can't log in for them.** `.venv/bin/python scripts/doctor.py --deep` proves the
   headless login; if it fails, the user runs `claude` → `/login` in a terminal, then you
   re-check. A signed-in desktop app doesn't count.
5. **Done means the doctor exits 0** (a missing slicer is only a warning) **and the studio
   answers** at `http://localhost:8765/api/setup`. Start it with `./start.sh` in the
   background or your preview tool (`.claude/launch.json` → `studio`), never in a way that
   blocks your shell.
6. **Finish with the four kid-mode bullets** from SETUP.md step 6, with their grown-up name in
   them. If their printer isn't a Creality K2, offer the `printer-setup` skill.

Re-running is safe: `install.sh` is idempotent and only changes the settings it's given. To
switch backends later, re-run it with a different `--images`, or
`.venv/bin/python scripts/configure.py set image_backend <backend>` (the studio picks the change
up without a restart).
