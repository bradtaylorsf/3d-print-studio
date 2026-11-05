# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- **Skills are first-class here.** Each `skills/<name>/` is symlinked into `.claude/skills/`,
  so every session in this repo — interactive, or a headless spawn like the studio's Make-me-3D
  builds — loads them. Edit the files under `skills/`; the symlinks follow. A new skill needs
  its symlink: `ln -s ../../skills/<name> .claude/skills/<name>`.
- **`/setup`** runs the `setup` skill, which follows [`SETUP.md`](SETUP.md): one question
  about who draws the pictures, then `install.sh`, `scripts/doctor.py`, and the first start.
- **The studio spawns headless `claude -p`** with the user's own CLI and login:
  - *Pictures* (`image_backend: "claude"`): one call per option, in parallel, model
    `claude.draw_model`, run in an empty temp directory with no tools — so this file, the
    skills and the repo are deliberately **not** loaded. Claude replies with an SVG; the studio
    sanitizes it, rasterizes it with resvg into `refs/`, and keeps the SVG in `vectors/`.
  - *Make me 3D*: model `claude.build_model`, cwd = the repo,
    `--permission-mode bypassPermissions --strict-mcp-config`, killed after
    `claude.build_timeout_min` minutes. This file, `AGENTS.md` and the skills **are** loaded.
    The session log is `<project>/.make3d.log`.
- **Headless needs a logged-in CLI.** Run `claude` once in a terminal and `/login`. A signed-in
  Claude desktop app is not enough: a build that dies instantly with "Not logged in" in
  `.make3d.log` means exactly this. `.venv/bin/python scripts/doctor.py --deep` proves it with
  one tiny real call.
- **Previewing the studio:** `.claude/launch.json` defines `studio` (port 8765) and
  `studio-8766`, for the desktop app's preview pane.
- **Personal notes** go in `CLAUDE.local.md` next to this file — gitignored, and Claude Code
  loads it automatically.
