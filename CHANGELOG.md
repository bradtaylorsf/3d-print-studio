# Changelog

3D Print Studio started on 2026-08-02 in a private repo. The August commits are in this
repo's history as redacted copies of the code commits, keeping their original dates. Work from
late August up to the first public release on 2026-11-05 was never committed separately, so
this file summarizes it. It covers the shared studio, skills and scripts, not individual
print projects.

## Unreleased

**Safety**

- **Make me 3D no longer runs Claude Code with permissions bypassed.** A build now starts in
  `dontAsk` mode, so anything not allowed is refused instead of asked, and
  `studio/build_guard.py` checks every tool call as a PreToolUse hook: writes only inside the
  build's own project folder, reads only the repo and the projects folder, Bash only the
  repo's own Python, no web tools. A user's own Claude Code allow rules can't loosen it.
  Tests: `scripts/test_build_guard.py`.
- `scripts/doctor.py --deep` also checks that the installed Claude Code is new enough to
  start a guarded build.
- New setting `claude.build_sandbox` (`off` / `on` / `auto`, default `off`): run a build's
  Python inside Claude Code's OS sandbox, so the script itself can write only in the project
  folder and has no network. The doctor says which of the two a build gets.
- The build prompt and `AGENTS.md` tell the build agent how to work inside the guard, and the
  studio creates `previews/` before a build starts.

## 2026-11-05 · First public release

Commit `59d35df`.

**Kid mode**

- 🎤 **Talk to it.** A *Tell me!* button uses the browser's own speech recognition, and
  drawing starts when the child stops talking. The studio never sees the audio, but Chrome and
  Safari send it to Google or Apple (see the README). The studio reads its replies, picture
  titles and errors aloud (🔊/🔇 toggle, remembered). The mic hides in browsers without speech
  recognition.
- **Four pictures to pick from** by default (`options`, 1–8; it was 2 or 3), shown uncropped
  in a 2×2 grid, with a short name under each when Claude drew them.
- **Claude Code can draw the pictures.** A new `claude` backend makes one headless
  `claude -p` call per option, each with a different take. The SVG it returns is sanitized,
  rendered into `refs/` with resvg and kept in `vectors/`. It uses your own Claude Code CLI and
  login, so it needs no GPU. New installs default to it (`image_backend: "claude"`), and `auto` also
  falls back to it when there's no Gemini key and no running ComfyUI.
- **"Needs setup" instead of a dead spinner.** Grown-up mode dims backends that aren't
  ready. An unset backend, a logged-out CLI or a rejected key now answers at once with the
  fix; kids see "ask a grown-up". A seconds counter runs while it draws, and only one draw
  runs at a time.
- **Your words for the grown-up.** Kid mode calls the helping adult whatever `kid.grown_up`
  says ("Go get Mom to help you from here"). `kid.ages` goes into the Claude drawing prompt and
  the toy build.
- **Make me 3D** defaults to Opus 5.5 (`claude.build_model`; it was Sonnet) with a
  configurable timeout (`claude.build_timeout_min`, 30 minutes; it was a fixed 18). The build
  prompt now knows your printer's envelope and scales the toy to fit, and reads the SVG when
  Claude drew the picture. A missing Claude CLI is refused up front.
- **Redo can't lose the old toy.** Its part files are now archived to
  `projects/.archive/redo_parts/` instead of deleted, and only once the new build has actually
  launched. A redo that can't start leaves the toy untouched, and one that fails later can be
  restored from the archive. A new picture that reuses an archived file name gets a fresh
  project.

**Coins**

- The 🪙 coin tracer and the one-colour chip tool now ship in `studio/tools/`
  (`make_coin.py`, `make_chip.py`, and `chip_geometry.py` for the shared 28 mm chip and socket
  dimensions). Outputs are named `token_coin_*` and `token_chip_*`, and a new `token-coin`
  skill documents the flow.

**Printers**

- **Any printer, not just the K2.** Bed, margin, name and slicer are `printer.*` config keys.
  The viewer's bed grid (non-square beds too), envelope box, camera and "fits *your printer*"
  badge follow them, and so do `meshtools.py` and the `design.py` template. The K2 facts,
  including where to find its firmware release notes, moved to
  `printers/creality-k2/profile.md`, and `printer-setup` now also sets the `printer.*` keys
  when it writes a profile for another machine.
- 🖨 opens the slicer named in `printer.slicer`: a macOS app name, or a command or path on
  Linux (falling back to `xdg-open`). It was Creality Print, on macOS only.

**Setup**

- `install.sh` asks who draws the pictures, what kid mode should call the grown-up, and the
  kids' ages. Agents can pass these as flags (`--images`, `--grown-up`, `--kid-ages`,
  `--yes`). It is safe to re-run and works as a curl one-liner. `SETUP.md` is the runbook an
  agent follows, and `/setup` wraps it.
- `scripts/doctor.py` checks the install; `--deep` makes one tiny real Claude call to prove
  the CLI is logged in. The studio serves the same report at `/api/setup`, and grown-up mode
  shows the first problem as a banner.
- One settings file, `studio.config.json` (gitignored; `studio.config.example.json` is the
  template), edited with `scripts/configure.py` and re-read live.
- `scripts/setup_comfyui.sh` installs ComfyUI and the Z-Image Turbo models, or only the
  missing models if a ComfyUI is already running. The studio now tries ComfyUI's default port
  8188 first, then 8000 and 8189 (August tried 8000 first), and `comfyui.url` points it at a
  specific instance.
- Projects can live outside the repo (`projects_dir`, `--projects` or
  `STUDIO_PROJECTS_DIR`). An empty projects folder starts with `examples/`: a picture library,
  a dragon toy and a three-colour star token (with its 28 mm coin).
- `start.sh` runs the installer on first use, reinstalls packages when a `git pull` changes
  `requirements.txt`, and just opens the page if the studio is already running. The Dock app
  opens kid mode.

**Safety**

- The server (still bound to 127.0.0.1) now refuses requests whose Host isn't localhost,
  which blocks DNS rebinding. It also refuses POSTs from any other web page, using Origin and
  Sec-Fetch-Site checks against CSRF. `STUDIO_ALLOWED_HOSTS` lets a tunnel through. This
  matters because Make me 3D runs Claude Code with permission prompts off.
- Uploaded pictures are served with `nosniff`, toasts and file names are inserted as text
  rather than HTML, a child's request is capped at 200 characters, and Claude's SVGs are
  sanitized.
- Server errors come back as readable messages instead of dropped connections.

**Docs, skills and contributing**

- `AGENTS.md` is the contract any coding agent follows, and `CLAUDE.md` imports it. The
  README is rewritten around the kid flow. MIT license.
- The skills work for any printer and any agent. `image-to-model` gains a traced photo plaque
  job: trace a photo into raised line art instead of redrawing it.
- `scripts/smoke_test.py` exercises every core endpoint against a throwaway projects folder
  and spends nothing. `scripts/check_privacy.py` and `scripts/export_public.sh` build the
  public repo from an allowlist and check it for private files.

Also: the Gemini key file moved to `~/.config/3d-print-studio/` (the old location still
works) and `GOOGLE_API_KEY` is accepted; dropping a picture with no project selected files it
in the library; Escape closes the picture wizard.

## October 2026

- **Bed size fixed.** The studio, skills and docs assumed a K2 Pro's 300 mm bed. The K2 is
  260 × 260 × 260 mm, with a 255 mm design envelope.
- 🖨 can open a project's real print file. A `slice.json` names what to open (say, a 3MF with
  the filaments already assigned) or says why there's nothing to slice.
- `k2-slicing`: what survives in a generated Creality Print 3MF. Filament settings are
  replaced by the CFS slot's preset, so write a user filament preset instead (the recipe is
  included). Also: the nine valid prime-tower positions, `skirt_loops 0`, `z_hop` is a machine
  key, and outer-only brims leave lips in notches.
- `print-troubleshooting`: a TE2762 + TE2766 strain-gauge and wiper checklist, and when a 0.6
  or 0.8 mm nozzle actually helps (only for speed-limited prints).

## September 2026

- `print-troubleshooting`: a step-by-step guide to the K2's "Extruder may be clogged"
  (FO2845) alarm: how the CFS buffer detects a clog, the hotend test, swapping the integrated
  nozzle, and TE2564 after a nozzle swap. Also what the CFS front lights mean, and that a
  firmware update force-updates the CFS.
- Server: fixed a crash in request logging, and added a second preview config so the studio
  can run on port 8766.

## August 2026 · in the git history

2026-08-02 to 2026-08-26, ten commits: the live viewer that hot-reloads `model.stl` whenever
`design.py` reruns, the project layout and the first skills, a one-command launcher and a
Dock-launchable macOS app, and kid mode, where a picture from Nano Banana or a local ComfyUI
can become a coin and a Make me 3D toy, with redo and archive. `git log --reverse` shows them.
They are history, not a version to run: they predate the request checks listed under Safety.
