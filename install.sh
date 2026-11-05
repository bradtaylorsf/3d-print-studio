#!/usr/bin/env bash
# install.sh — set up 3D Print Studio on macOS or Linux (Windows: run it inside WSL).
#
#   ./install.sh                          asks how to draw pictures (and two small things), then installs
#   ./install.sh --images claude --yes    no questions — for agents and scripts (see --help)
#   curl -fsSL https://raw.githubusercontent.com/bradtaylorsf/3d-print-studio/main/install.sh | bash
#                                         clones into ~/3d-print-studio first, then runs the clone's copy
#
# Safe to re-run: it reuses .venv, keeps every studio.config.json value it isn't
# told to change (and any saved API key), and never touches projects/.
#
# Written for macOS's stock /bin/bash 3.2 — a fresh Mac has nothing newer — so:
# no associative arrays, no ${x,,}, no mapfile, and empty arrays are guarded.
# Everything lives in functions and `main` is the last line, so `curl | bash`
# can't run a half-downloaded script.
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/bradtaylorsf/3d-print-studio.git"
CLAUDE_INSTALLER="curl -fsSL https://claude.ai/install.sh | bash"
DEFAULT_PORT=8765

# ------------------------------------------------------------- output ----
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
  C_STEP=$'\033[1;34m' C_BOLD=$'\033[1m' C_WARN=$'\033[1;33m' C_ERR=$'\033[1;31m' C_OK=$'\033[1;32m' C_OFF=$'\033[0m'
else
  C_STEP="" C_BOLD="" C_WARN="" C_ERR="" C_OK="" C_OFF=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$C_STEP" "$C_OFF" "$C_BOLD" "$*" "$C_OFF"; }
note() { printf '    %s\n' "$*"; }
good() { printf '    %s%s%s\n' "$C_OK" "$*" "$C_OFF"; }
warn() { printf '%s  ! %s%s\n' "$C_WARN" "$*" "$C_OFF" >&2; }
die()  { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }
indent() { sed 's/^/    /'; }

usage() {
  cat <<'EOF'
3D Print Studio installer

  ./install.sh [options]
  curl -fsSL https://raw.githubusercontent.com/bradtaylorsf/3d-print-studio/main/install.sh | bash -s -- [options]

With no options it asks how pictures should be drawn, what kid mode calls the
grown-up, and the kids' ages, then installs everything. Options answer those
questions up front (agents: always pass --images and --yes):

  --images claude|comfyui|nano|auto   who draws the 4 picture options
                                      claude  = Claude Code (Opus 5.5), no GPU, uses your Claude plan
                                      comfyui = a ComfyUI on this computer, free per picture, ~20 GB models
                                      nano    = Google Nano Banana, needs a Gemini API key
  --grown-up NAME                     what kid mode calls the helper ("Go get NAME to help")
  --kid-ages "4 to 7"                 shapes how chunky and sturdy the toys are
  --comfyui-url URL                   use a ComfyUI that's already running
  --install-comfyui                   install ComfyUI + its models (~20 GB) if none is running
  --comfyui-workspace DIR             where ComfyUI lives / goes (default ~/ComfyUI)
  --python PATH                       the Python 3.10+ to build .venv with (or STUDIO_PYTHON=...)
  --yes, -y                           no questions; anything not given keeps its current value
                                      (or the default on a first install)
  --start / --no-start                start the studio when done (default: ask; never with --yes)
  -h, --help                          this help

Environment: STUDIO_DIR (where the curl one-liner clones; default ~/3d-print-studio),
STUDIO_REPO_URL (what it clones), GEMINI_API_KEY, NO_COLOR.
EOF
}

# -------------------------------------------------------------- args -----
IMAGES="" YES=0 GROWN_UP="" KID_AGES="" COMFY_URL="" INSTALL_COMFY=0 COMFY_WS=""
START="" PY_OVERRIDE="${STUDIO_PYTHON:-}" SHOW_HELP=0 CONFIG_FILE=""

parse_args() {
  while [ $# -gt 0 ]; do
    case $1 in
      --images|--grown-up|--kid-ages|--comfyui-url|--comfyui-workspace|--python)
        [ $# -ge 2 ] || die "$1 needs a value (see --help)"
        set_opt "$1" "$2"; shift 2 ;;
      --images=*|--grown-up=*|--kid-ages=*|--comfyui-url=*|--comfyui-workspace=*|--python=*)
        set_opt "${1%%=*}" "${1#*=}"; shift ;;
      --install-comfyui) INSTALL_COMFY=1; shift ;;
      -y|--yes) YES=1; shift ;;
      --start) START=1; shift ;;
      --no-start) START=0; shift ;;
      -h|--help) SHOW_HELP=1; shift ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done
}

set_opt() {
  case $1 in
    --images) IMAGES=$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]') ;;
    --grown-up) GROWN_UP=$2 ;;
    --kid-ages) KID_AGES=$2 ;;
    --comfyui-url) COMFY_URL=$(norm_url "$2") ;;
    --comfyui-workspace) COMFY_WS=$2 ;;
    --python) PY_OVERRIDE=$2 ;;
  esac
}

# "localhost:8188" -> "http://localhost:8188". curl guesses http:// for a bare
# host:port but the studio's Python (urllib) refuses it — the URL "worked" here,
# then every model looked missing and the studio said ComfyUI wasn't answering.
norm_url() {
  local u=$1
  u=${u%/}
  case $u in "" | http://* | https://*) ;; *) u="http://$u" ;; esac
  printf '%s' "$u"
}

trim() {   # strip leading/trailing whitespace (bash 3.2-safe)
  local s=$1
  s=${s#"${s%%[![:space:]]*}"}
  s=${s%"${s##*[![:space:]]}"}
  printf '%s' "$s"
}

# ------------------------------------------------------------ prompts ----
# Where answers come from: "stdin" (a terminal), "/dev/tty" (curl | bash: stdin
# is the script, the keyboard is still there), or "" (no questions — --yes, or
# no terminal at all, e.g. an agent's shell: then defaults apply).
TTY_IN=""
# /dev/tty only when a person can see the questions (stdout or stderr is a
# terminal, as with `curl | bash`). An agent's shell captures both, yet some
# still have a controlling terminal — asking there would hang the agent and
# print prompts into the user's terminal app instead.
tty_fallback_ok() { { [ -t 1 ] || [ -t 2 ]; } && ( : </dev/tty ) 2>/dev/null; }
setup_tty() {
  TTY_IN=""
  [ "$YES" = 1 ] && return 0
  if [ -t 0 ]; then
    TTY_IN="stdin"
  elif tty_fallback_ok; then
    TTY_IN="/dev/tty"
  fi
}

say_prompt() {   # prompts go where the answer comes from, so they're never lost in a pipe
  if [ "$TTY_IN" = "/dev/tty" ]; then printf '%s' "$1" >/dev/tty; else printf '%s' "$1" >&2; fi
}

read_line() {    # read_line VAR [-s]
  # bash scoping is dynamic: this local must not share a name with any caller's
  # variable, or printf -v below would fill the local instead of the caller's.
  local __rl_line=""
  if [ "$TTY_IN" = "stdin" ]; then
    if [ "${2:-}" = "-s" ]; then IFS= read -rs __rl_line || true; else IFS= read -r __rl_line || true; fi
  else
    if [ "${2:-}" = "-s" ]; then IFS= read -rs __rl_line </dev/tty || true; else IFS= read -r __rl_line </dev/tty || true; fi
  fi
  printf -v "$1" '%s' "$__rl_line"
}

# ask VAR "Question" "default" — Enter keeps the default; no terminal = default
ask() {
  local _var=$1 _q=$2 _def=${3:-} _ans=""
  if [ -z "$TTY_IN" ]; then printf -v "$_var" '%s' "$_def"; return 0; fi
  if [ -n "$_def" ]; then say_prompt "$_q [$_def] "; else say_prompt "$_q "; fi
  read_line _ans
  _ans=$(trim "$_ans")
  [ -n "$_ans" ] || _ans=$_def
  printf -v "$_var" '%s' "$_ans"
}

# confirm "Question" y|n — returns 0 for yes; no terminal = the default
confirm() {
  local _q=$1 _def=${2:-n} _ans=""
  if [ -z "$TTY_IN" ]; then [ "$_def" = "y" ]; return; fi
  while :; do
    if [ "$_def" = "y" ]; then say_prompt "$_q [Y/n] "; else say_prompt "$_q [y/N] "; fi
    read_line _ans
    _ans=$(printf '%s' "$_ans" | tr '[:upper:]' '[:lower:]')
    case $_ans in
      "") [ "$_def" = "y" ]; return ;;
      y|yes) return 0 ;;
      n|no) return 1 ;;
    esac
  done
}

ask_secret() {   # ask_secret VAR "Question" — hidden input
  local _var=$1 _ans=""
  printf -v "$_var" '%s' ""
  [ -n "$TTY_IN" ] || return 0
  say_prompt "$2 "
  read_line _ans -s
  say_prompt $'\n'
  printf -v "$_var" '%s' "$_ans"
}

# ---------------------------------------------------------- bootstrap ----
is_checkout() { [ -f "$1/install.sh" ] && [ -f "$1/studio/config.py" ]; }

git_ok() {
  command -v git >/dev/null 2>&1 || return 1
  # On a fresh Mac /usr/bin/git is a stub that pops up the Command Line Tools
  # installer instead of running — treat that as "no git" and say so.
  if [ "$(uname -s)" = "Darwin" ] && [ "$(command -v git)" = "/usr/bin/git" ] \
     && ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

git_help() {
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "git comes with Apple's Command Line Tools: run  xcode-select --install  then re-run this."
  else
    echo "install git (e.g.  sudo apt install git) then re-run this."
  fi
}

# Not inside a checkout (curl | bash): clone, then run the clone's install.sh
# with the same arguments and the keyboard as stdin.
bootstrap() {
  local dest=${STUDIO_DIR:-$HOME/3d-print-studio} url=${STUDIO_REPO_URL:-$REPO_URL_DEFAULT}
  step "Getting 3D Print Studio into $dest"
  git_ok || die "git is needed to download the studio — $(git_help)"
  if is_checkout "$dest"; then
    note "Already there — updating it (git pull --ff-only)"
    git -C "$dest" pull --ff-only --quiet 2>&1 | indent \
      || warn "couldn't update $dest (local changes?) — using it as it is"
  elif [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then
    die "$dest already exists and isn't a 3D Print Studio folder. Choose another: STUDIO_DIR=/some/new/folder"
  else
    git clone --quiet "$url" "$dest" || die "git clone $url failed"
  fi
  is_checkout "$dest" || die "$dest doesn't look like 3D Print Studio (no install.sh / studio/config.py) — is STUDIO_REPO_URL right?"
  if [ "$YES" != 1 ] && tty_fallback_ok; then
    exec bash "$dest/install.sh" "$@" </dev/tty
  fi
  exec bash "$dest/install.sh" "$@"
}

find_repo() {   # prints the checkout this script belongs to, or nothing
  local src=${BASH_SOURCE[0]:-} dir
  if [ -n "$src" ] && [ -f "$src" ]; then
    dir=$(cd "$(dirname "$src")" && pwd)
    if is_checkout "$dir"; then echo "$dir"; return 0; fi
  fi
  if is_checkout "$PWD"; then echo "$PWD"; fi   # `curl | bash` run from inside a checkout
  return 0
}

# ------------------------------------------------------------- python ----
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

# Newest-but-proven first: 3.13…3.10 have wheels for everything in
# requirements.txt; a brand-new python3 (3.15 here, once) may not yet.
find_python() {
  local c p
  if [ -n "$PY_OVERRIDE" ]; then
    py_ok "$PY_OVERRIDE" || die "$PY_OVERRIDE isn't a working Python 3.10+"
    echo "$PY_OVERRIDE"; return 0
  fi
  for c in python3.13 python3.12 python3.11 python3.10 python3.14 python3; do
    p=$(command -v "$c" 2>/dev/null) || continue
    # macOS's /usr/bin/python3 is a Command Line Tools stub (and 3.9 when present)
    if [ "$p" = "/usr/bin/python3" ] && [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    if py_ok "$p"; then echo "$p"; return 0; fi
  done
  if command -v uv >/dev/null 2>&1; then
    p=$(uv python find '>=3.10' 2>/dev/null || true)
    if [ -n "$p" ] && py_ok "$p"; then echo "$p"; return 0; fi
  fi
  return 1
}

python_help() {
  cat >&2 <<'EOF'
No Python 3.10 or newer found. Install one, then re-run ./install.sh:
  macOS:          brew install python@3.13      (Homebrew: https://brew.sh)
                  or the installer from https://www.python.org/downloads/
  Ubuntu/Debian:  sudo apt install python3 python3-venv
  with uv:        uv python install 3.13
Or point at one you have:  ./install.sh --python /path/to/python3
EOF
}

# --------------------------------------------------------- config i/o ----
cfg() { "$PY" "$REPO/scripts/configure.py" "$@"; }
cfg_get() { "$PY" "$REPO/scripts/configure.py" get "$1" 2>/dev/null || true; }
# py_studio 'python using cfg/config/sys.argv' [args…] — runs against studio/config.py
py_studio() {
  local code=$1; shift
  "$PY" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); import config; cfg = config.load(); $code" \
    "$REPO/studio" "$@" 2>/dev/null || true
}

claude_path() { py_studio 'print(config.claude_bin(cfg) or "")'; }
have_gemini_key() { [ -n "$(py_studio 'print("yes" if config.gemini_key(cfg) else "")')" ]; }

comfy_alive() { command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "${1%/}/system_stats" >/dev/null 2>&1; }

probe_comfy() {   # the first ComfyUI that answers: configured url, then the usual ports
  local u
  for u in "$(cfg_get comfyui.url)" http://127.0.0.1:8188 http://127.0.0.1:8000 http://127.0.0.1:8189; do
    u=$(norm_url "$u")    # an old hand-edited "host:port" — configure.py now refuses those
    if [ -n "$u" ] && comfy_alive "$u"; then echo "$u"; return 0; fi
  done
  return 0
}

comfy_missing_models() {   # models the ComfyUI at $1 doesn't have, one per line
  # "?" when Python can't reach it although curl could (a proxy, an odd URL):
  # comfy_model_choice would then call every model missing and offer 20 GB of
  # downloads ComfyUI may already have.
  py_studio "
if not config.comfy_alive(sys.argv[1]):
    print('?')
else:
    print('\\n'.join(config.comfy_model_choice(cfg, sys.argv[1])[1]))" "$1"
}

# ---------------------------------------------------------- questions ----
ask_images() {
  local cur=$1 def=1 ans
  case $cur in comfyui|comfy) def=2 ;; nano) def=3 ;; esac
  {
    echo
    echo "How should the studio draw pictures?"
    echo "  1) Claude Code (Opus 5.5) — no GPU, no extra downloads; uses your Claude plan"
    echo "  2) ComfyUI, on this computer — free per picture, needs a GPU or Apple Silicon and ~20 GB of models"
    echo "  3) Google Nano Banana — needs a Gemini API key"
  } | if [ "$TTY_IN" = "/dev/tty" ]; then cat >/dev/tty; else cat >&2; fi
  while :; do
    ask ans "Choose 1, 2 or 3:" "$def"
    case $(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]') in
      1|claude) IMAGES=claude; return ;;
      2|comfyui|comfy) IMAGES=comfyui; return ;;
      3|nano|gemini) IMAGES=nano; return ;;
    esac
  done
}

# ComfyUI: use one that's running, or install one. Decided here, done later.
ask_comfy() {
  local found ans
  [ -n "$COMFY_URL" ] && return 0
  found=$(probe_comfy)
  if [ -n "$TTY_IN" ]; then
    if [ -n "$found" ] && confirm "Found ComfyUI running at $found — use it?" y; then
      COMFY_URL=$found; return 0
    fi
    if [ "$INSTALL_COMFY" != 1 ]; then
      ask ans "Do you already have ComfyUI running? Paste its URL, or press Enter to install it here:" ""
      if [ -n "$ans" ]; then COMFY_URL=$(norm_url "$ans"); return 0; fi
    fi
    note "That installs ComfyUI (with its own Python packages) and downloads ~20 GB of models."
    ask COMFY_WS "Where should ComfyUI go?" "${COMFY_WS:-$HOME/ComfyUI}"
    if confirm "Install ComfyUI into $COMFY_WS now?" y; then
      INSTALL_COMFY=1
    else
      note "OK — later, run: scripts/setup_comfyui.sh"
    fi
  elif [ -n "$found" ] && [ "$INSTALL_COMFY" != 1 ]; then
    COMFY_URL=$found
  fi
}

NANO_KEY=""
ask_nano() {
  local keyfile
  if [ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]; then
    keyfile=$(cfg_get nano.key_file)
    if [ -n "$TTY_IN" ] && ! [ -s "$(expand_path "$keyfile")" ] \
       && confirm "Save your GEMINI_API_KEY to $keyfile, so the studio finds it when started from Finder too?" y; then
      NANO_KEY=${GEMINI_API_KEY:-$GOOGLE_API_KEY}
    fi
    return 0
  fi
  if have_gemini_key; then note "A Gemini API key is already saved — keeping it."; return 0; fi
  ask_secret NANO_KEY "Paste your Gemini API key (get one at https://aistudio.google.com/apikey; input is hidden; Enter to skip):"
}

expand_path() { "$PY" -c 'import os, sys; print(os.path.expanduser(sys.argv[1]))' "$1"; }

WANT_CLAUDE_INSTALL=0
ask_claude_install() {
  CLAUDE_BIN=$(claude_path)
  [ -n "$CLAUDE_BIN" ] && return 0
  echo >&2
  note "The Claude Code CLI isn't installed. The studio needs it for Make me 3D (and to draw, if you chose Claude)."
  if confirm "Install it now with the official installer ($CLAUDE_INSTALLER)?" n; then
    WANT_CLAUDE_INSTALL=1
  fi
}

# --------------------------------------------------------------- work ----
setup_venv() {
  if [ -x .venv/bin/python ] && py_ok .venv/bin/python; then
    note "Reusing .venv ($(.venv/bin/python -V 2>&1))"
    return 0
  fi
  if [ -e .venv ]; then
    warn ".venv is broken or older than Python 3.10 — rebuilding it"
    rm -rf .venv
  fi
  note "Creating .venv with $PY ($("$PY" -V 2>&1))"
  "$PY" -m venv .venv || die "couldn't create .venv — on Debian/Ubuntu: sudo apt install python3-venv"
}

install_deps() {
  local stamp=.venv/.studio-requirements.txt
  if cmp -s requirements.txt "$stamp" \
     && .venv/bin/python -c 'import trimesh, manifold3d, numpy, shapely, cv2, skimage, resvg_py' >/dev/null 2>&1; then
    note "Python packages are up to date"
    return 0
  fi
  note "Installing Python packages (the first time takes a few minutes)…"
  .venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip \
    || die "couldn't upgrade pip in .venv (offline?)"
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || die "pip couldn't install requirements.txt — see the error above (offline? a Python too new for some wheels? try --python python3.12)"
  cp requirements.txt "$stamp"
  good "Python packages installed"
}

install_claude() {
  note "Running: $CLAUDE_INSTALLER"
  if ! (curl -fsSL https://claude.ai/install.sh | bash); then
    warn "the Claude Code installer failed — install it by hand later: $CLAUDE_INSTALLER"
  fi
  CLAUDE_BIN=$(claude_path)
}

prepare_config() {
  # The file configure.py actually reads — $STUDIO_CONFIG can point elsewhere,
  # and checking ./studio.config.json instead once moved a GOOD repo config
  # aside because the other file was broken.
  CONFIG_FILE=$(cfg path)
  # A config that isn't valid JSON can't be merged into: move it aside (not
  # delete — it may hold hand edits) and start from the example.
  if [ -f "$CONFIG_FILE" ] && ! cfg show --file >/dev/null 2>&1; then
    local aside
    aside="$CONFIG_FILE.broken-$(date +%Y%m%d-%H%M%S)"
    mv "$CONFIG_FILE" "$aside"
    warn "$CONFIG_FILE wasn't valid JSON — moved it to $aside and starting fresh"
  fi
}

needs_login() {   # the sentence subject for the login reminders
  if [ "$IMAGES" = claude ]; then printf "Make me 3D and Claude's pictures need"; else printf 'Make me 3D needs'; fi
}

write_config() {
  cfg init | indent
  cfg set image_backend "$IMAGES" | indent
  cfg set --string kid.grown_up "$GROWN_UP" kid.ages "$KID_AGES" | indent
}

save_nano_key() {
  local keyfile path
  keyfile=$(cfg_get nano.key_file)
  path=$(expand_path "$keyfile")
  mkdir -p "$(dirname "$path")"
  ( umask 077; printf '%s\n' "$NANO_KEY" >"$path" )
  chmod 600 "$path"
  good "Saved the Gemini API key to $keyfile (only you can read it)"
}

setup_comfy() {
  local args=(--yes) missing
  [ -n "$COMFY_WS" ] && args+=(--workspace "$COMFY_WS")
  if [ -n "$COMFY_URL" ]; then
    if comfy_alive "$COMFY_URL"; then
      good "ComfyUI answers at $COMFY_URL"
      cfg set --string comfyui.url "$COMFY_URL" | indent
      missing=$(comfy_missing_models "$COMFY_URL")
      if [ -z "$missing" ]; then
        good "It has the Z-Image Turbo models"
        return 0
      fi
      if [ "$missing" = "?" ]; then
        warn "curl reaches $COMFY_URL but the studio's Python can't (a proxy setting?) — not downloading anything."
        warn "check it with: .venv/bin/python scripts/doctor.py"
        return 0
      fi
      note "It's missing: $(echo "$missing" | tr '\n' ' ')"
      if [ "$INSTALL_COMFY" = 1 ] || confirm "Download them now (up to ~20 GB)?" y; then
        run_setup_comfy --url "$COMFY_URL" --models-only --no-launch "${args[@]}"
      else
        warn "pictures won't work until they're there: scripts/setup_comfyui.sh --models-only"
      fi
      return 0
    fi
    warn "nothing answers at $COMFY_URL"
    if [ "$INSTALL_COMFY" = 1 ]; then
      run_setup_comfy --url "$COMFY_URL" "${args[@]}"
    else
      cfg set --string comfyui.url "$COMFY_URL" | indent
      warn "start that ComfyUI (the studio finds it when it's up), or install one: scripts/setup_comfyui.sh"
    fi
    return 0
  fi
  if [ "$INSTALL_COMFY" = 1 ]; then
    run_setup_comfy "${args[@]}"
  else
    warn "no ComfyUI chosen or installed — pictures need one."
    warn "install one any time: scripts/setup_comfyui.sh   (or: ./install.sh --images comfyui --install-comfyui)"
  fi
}

run_setup_comfy() {
  note "Running: scripts/setup_comfyui.sh $*"
  if [ "$TTY_IN" = "/dev/tty" ]; then
    bash scripts/setup_comfyui.sh "$@" </dev/tty || warn "ComfyUI setup didn't finish — re-run scripts/setup_comfyui.sh"
  else
    bash scripts/setup_comfyui.sh "$@" || warn "ComfyUI setup didn't finish — re-run scripts/setup_comfyui.sh"
  fi
}

# --------------------------------------------------------------- main ----
main() {
  parse_args "$@"
  if [ "$SHOW_HELP" = 1 ]; then usage; exit 0; fi

  case "$(uname -s)" in
    Darwin|Linux) ;;
    MINGW*|MSYS*|CYGWIN*)
      die "Windows isn't supported directly. Install WSL (in PowerShell: wsl --install), then run this inside Ubuntu." ;;
    *) warn "untested system: $(uname -s) — carrying on" ;;
  esac

  case $IMAGES in
    ""|claude|comfyui|nano|auto) ;;
    comfy) IMAGES=comfyui ;;
    *) die "--images must be claude, comfyui, nano or auto (got '$IMAGES')" ;;
  esac

  REPO=$(find_repo)
  if [ -z "$REPO" ]; then bootstrap "$@"; fi
  cd "$REPO"
  export PIP_DISABLE_PIP_VERSION_CHECK=1
  setup_tty

  step "3D Print Studio — installing in $REPO"
  if [ -z "$TTY_IN" ] && [ "$YES" != 1 ]; then
    note "No terminal to ask questions in — using defaults. (Agents: pass --images … --yes.)"
  fi
  git_ok || warn "git isn't available — fine for now, but you'll want it to update: $(git_help)"
  PY=$(find_python) || { python_help; exit 1; }
  note "Python: $PY ($("$PY" -V 2>&1))"
  prepare_config

  # ---- questions first, so the long part runs unattended
  local had_config=0 cur_backend cur_grown cur_ages
  [ -f "$CONFIG_FILE" ] && had_config=1
  cur_backend=$(cfg_get image_backend | tr '[:upper:]' '[:lower:]')
  cur_grown=$(cfg_get kid.grown_up)
  cur_ages=$(cfg_get kid.ages)
  if [ "$had_config" = 0 ]; then cur_backend=claude; fi   # a first install defaults to Claude, not "auto"
  # A hand-edited value: "comfy" must still get the ComfyUI step, and a typo must
  # not abort a --yes re-run (start.sh does one) at the configure.py write.
  case $cur_backend in
    comfy) cur_backend=comfyui ;;
    claude|comfyui|nano|auto) ;;
    *) warn "image_backend '$cur_backend' in the config isn't one I know — using claude"; cur_backend=claude ;;
  esac
  # --comfyui-url / --install-comfyui say which backend without --images
  if [ -z "$IMAGES" ] && { [ -n "$COMFY_URL" ] || [ "$INSTALL_COMFY" = 1 ]; }; then IMAGES=comfyui; fi

  if [ -z "$IMAGES" ]; then
    if [ -n "$TTY_IN" ]; then ask_images "$cur_backend"; else IMAGES=${cur_backend:-claude}; fi
  fi
  case $IMAGES in
    comfyui) ask_comfy ;;
    nano) ask_nano ;;
  esac
  if [ -z "$GROWN_UP" ]; then
    ask GROWN_UP "What should kid mode call the grown-up who helps? (Mom, Dad, Grandpa…)" "${cur_grown:-a grown-up}"
  fi
  if [ -z "$KID_AGES" ]; then
    ask KID_AGES "How old are the kids who'll use it?" "${cur_ages:-5 to 9}"
  fi
  ask_claude_install

  # ---- the work
  step "Python environment (.venv)"
  setup_venv
  install_deps

  step "Claude Code CLI"
  if [ "$WANT_CLAUDE_INSTALL" = 1 ]; then install_claude; fi
  if [ -n "$CLAUDE_BIN" ]; then
    good "Found: $CLAUDE_BIN ($("$CLAUDE_BIN" --version 2>/dev/null | head -n 1 || echo "version unknown"))"
  else
    warn "not installed. Install it with:  $CLAUDE_INSTALLER"
  fi
  note "$(needs_login) the CLI logged in for headless use:"
  note "run  claude  once in a terminal, then type  /login  (the desktop app being signed in isn't enough)."

  step "Settings (studio.config.json)"
  write_config

  case $IMAGES in
    comfyui) step "ComfyUI"; setup_comfy ;;
    nano)
      step "Nano Banana"
      if [ -n "$NANO_KEY" ]; then save_nano_key
      elif [ -n "${GEMINI_API_KEY:-}${GOOGLE_API_KEY:-}" ]; then note "Using GEMINI_API_KEY from the environment (start the studio from this shell, or save the key: re-run ./install.sh)."
      elif have_gemini_key; then good "Gemini API key: saved"
      else warn "no Gemini API key yet — set GEMINI_API_KEY, or put the key in $(cfg_get nano.key_file)"
      fi ;;
  esac

  step "Checking the setup"
  local doctor_rc=0
  .venv/bin/python scripts/doctor.py || doctor_rc=$?

  step "Done"
  note "Start the studio:  ./start.sh        (on a Mac you can also double-click Studio.command)"
  note "Kid mode:          http://localhost:$DEFAULT_PORT/?kid=1"
  note "Grown-up mode:     http://localhost:$DEFAULT_PORT/"
  note "$(needs_login) the Claude Code CLI logged in once: claude, then /login"
  note "(prove it with: scripts/doctor.py --deep)"
  if [ "$doctor_rc" != 0 ]; then
    warn "a few things still need fixing (listed above) — re-check any time with: scripts/doctor.py"
  fi

  if [ "$START" = "" ] && [ -n "$TTY_IN" ] && confirm "Start the studio now?" y; then START=1; fi
  if [ "$START" = 1 ]; then
    exec bash ./start.sh
  fi
}

main "$@"
