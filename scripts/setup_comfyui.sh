#!/usr/bin/env bash
# setup_comfyui.sh — a local ComfyUI that draws the studio's pictures with Z-Image Turbo.
#
#   scripts/setup_comfyui.sh [--workspace DIR] [--url URL] [--gpu auto|m-series|nvidia|amd|cpu]
#                            [--models-only] [--no-launch] [--yes] [--dry-run]
#
# If a ComfyUI already answers (--url, else the configured comfyui.url, else
# 127.0.0.1:8188/8000/8189) nothing is installed: it fetches only the models that
# ComfyUI says it lacks, into the folders ComfyUI itself reads (or --workspace).
# Otherwise it installs comfy-cli into <repo>/.venv-comfy, ComfyUI into the
# workspace (default ~/ComfyUI), downloads the three models (~20 GB, resumable),
# launches it on 127.0.0.1:8188 and records url + workspace in studio.config.json
# so ./start.sh can relaunch it next time.
#
# --dry-run prints every step and download (with sizes) and changes nothing.
# Written for macOS's stock /bin/bash 3.2, like install.sh.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# STUDIO_MODELS_URL: a mirror with the same split_files/ layout (or a local test server)
HF_BASE="${STUDIO_MODELS_URL:-https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main}"
PROBE_URLS="http://127.0.0.1:8188 http://127.0.0.1:8000 http://127.0.0.1:8189"

# folder | file we save | path in the Hugging Face repo. The VAE is saved as
# z_image_ae.safetensors because other model families also ship an "ae.safetensors".
model_info() {
  case $1 in
    1) echo "diffusion_models z_image_turbo_bf16.safetensors split_files/diffusion_models/z_image_turbo_bf16.safetensors" ;;
    2) echo "text_encoders qwen_3_4b.safetensors split_files/text_encoders/qwen_3_4b.safetensors" ;;
    3) echo "vae z_image_ae.safetensors split_files/vae/ae.safetensors" ;;
  esac
}

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
  C_STEP=$'\033[1;34m' C_BOLD=$'\033[1m' C_WARN=$'\033[1;33m' C_ERR=$'\033[1;31m' C_OK=$'\033[1;32m' C_OFF=$'\033[0m'
else
  C_STEP="" C_BOLD="" C_WARN="" C_ERR="" C_OK="" C_OFF=""
fi
step() { printf '%s==>%s %s%s%s\n' "$C_STEP" "$C_OFF" "$C_BOLD" "$*" "$C_OFF"; }
note() { printf '    %s\n' "$*"; }
good() { printf '    %s%s%s\n' "$C_OK" "$*" "$C_OFF"; }
warn() { printf '%s  ! %s%s\n' "$C_WARN" "$*" "$C_OFF" >&2; }
die()  { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

usage() {
  sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --workspace DIR   the ComfyUI folder: installed into, launched from, models saved under DIR/models
                    (default ~/ComfyUI; for a running ComfyUI, the folders it reports are used instead)
  --url URL         the ComfyUI to use / where to launch it (default http://127.0.0.1:8188)
  --gpu KIND        auto (default) | m-series | nvidia | amd | cpu
  --models-only     don't install or launch anything — just make sure the models are there
  --no-launch       install but don't start it (./start.sh starts it later)
  --yes, -y         don't ask (including before the ~20 GB download)
  --dry-run         show what would happen; download and change nothing
EOF
}

WS="" URL="" GPU=auto MODELS_ONLY=0 NO_LAUNCH=0 YES=0 DRY=0
while [ $# -gt 0 ]; do
  case $1 in
    --workspace|--url|--gpu)
      [ $# -ge 2 ] || die "$1 needs a value"
      case $1 in --workspace) WS=$2 ;; --url) URL=${2%/} ;; --gpu) GPU=$2 ;; esac
      shift 2 ;;
    --workspace=*) WS=${1#*=}; shift ;;
    --url=*) URL=${1#*=}; URL=${URL%/}; shift ;;
    --gpu=*) GPU=${1#*=}; shift ;;
    --models-only) MODELS_ONLY=1; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    -y|--yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done
case $GPU in auto|m-series|nvidia|amd|cpu) ;; *) die "--gpu must be auto, m-series, nvidia, amd or cpu" ;; esac
# "localhost:8188" -> "http://localhost:8188": curl accepts a bare host:port, the
# studio's Python doesn't — and then every model looks missing (see running_missing).
case $URL in "" | http://* | https://*) ;; *) URL="http://$URL" ;; esac
WS_GIVEN=0
if [ -n "$WS" ]; then WS_GIVEN=1; fi
WS=${WS:-$HOME/ComfyUI}
# shellcheck disable=SC2088  # matching a literal "~" someone passed in quotes
case $WS in "~"|"~/"*) WS="$HOME${WS#\~}" ;; esac
case $WS in /*) ;; *) WS="$PWD/$WS" ;; esac

# ------------------------------------------------------------- prompts ----
TTY_IN=""
if [ "$YES" != 1 ]; then
  # /dev/tty only when someone can see the question (see install.sh's tty_fallback_ok)
  if [ -t 0 ]; then TTY_IN=stdin
  elif { [ -t 1 ] || [ -t 2 ]; } && ( : </dev/tty ) 2>/dev/null; then TTY_IN=/dev/tty; fi
fi
confirm() {   # confirm "Question" y|n — no terminal: --yes means yes, otherwise the default
  local q=$1 def=${2:-n} ans=""
  if [ "$YES" = 1 ]; then return 0; fi
  if [ -z "$TTY_IN" ]; then [ "$def" = "y" ]; return; fi
  while :; do
    if [ "$def" = "y" ]; then printf '%s [Y/n] ' "$q" >&2; else printf '%s [y/N] ' "$q" >&2; fi
    if [ "$TTY_IN" = stdin ]; then IFS= read -r ans || true; else IFS= read -r ans </dev/tty || true; fi
    case $(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]') in
      "") [ "$def" = "y" ]; return ;;
      y|yes) return 0 ;;
      n|no) return 1 ;;
    esac
  done
}

run() {   # run a command, or just show it with --dry-run
  if [ "$DRY" = 1 ]; then
    printf '    [dry-run] would run:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# --------------------------------------------------------------- python ----
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
find_python() {   # PyTorch trails new Pythons, so 3.13…3.10 before anything newer
  local c p
  if [ -n "${STUDIO_PYTHON:-}" ] && py_ok "$STUDIO_PYTHON"; then echo "$STUDIO_PYTHON"; return 0; fi
  for c in python3.13 python3.12 python3.11 python3.10 python3.14 python3; do
    p=$(command -v "$c" 2>/dev/null) || continue
    if [ "$p" = "/usr/bin/python3" ] && [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
      continue
    fi
    if py_ok "$p"; then echo "$p"; return 0; fi
  done
  return 1
}
# configure.py and the config checks are stdlib-only: the studio's venv if it
# exists, any python3 otherwise.
if [ -x "$REPO/.venv/bin/python" ]; then CPY="$REPO/.venv/bin/python"
else CPY=$(find_python) || die "no Python 3.10+ found — run ./install.sh first"; fi
py_studio() {   # py_studio 'code using config/cfg/sys.argv' [args…]
  local code=$1; shift
  "$CPY" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); import config; cfg = config.load(); $code" \
    "$REPO/studio" "$@"
}
cfg_get() { "$CPY" "$REPO/scripts/configure.py" get "$1" 2>/dev/null || true; }

# --------------------------------------------------------------- comfyui ---
alive() { curl -fsS --max-time 2 "${1%/}/system_stats" >/dev/null 2>&1; }

find_running() {
  local u
  if [ -n "$URL" ]; then
    if alive "$URL"; then echo "$URL"; fi
    return 0
  fi
  for u in "$(cfg_get comfyui.url)" $PROBE_URLS; do
    case $u in "" | http://* | https://*) ;; *) u="http://$u" ;; esac   # an old hand-edited "host:port"
    if [ "$u" != "http://" ] && [ -n "$u" ] && alive "$u"; then echo "${u%/}"; return 0; fi
  done
  return 0
}

url_port() {   # the port in a URL, or 8188
  local p=${1#*://}
  p=${p%%/*}
  case $p in *:*) p=${p##*:} ;; *) p=8188 ;; esac
  case $p in ''|*[!0-9]*) p=8188 ;; esac
  echo "$p"
}

detect_gpu() {
  [ "$GPU" = auto ] || { echo "$GPU"; return 0; }
  case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) echo m-series; return 0 ;;
    Darwin/*) echo cpu; return 0 ;;
  esac
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then echo nvidia; return 0; fi
  if command -v rocminfo >/dev/null 2>&1 || [ -d /opt/rocm ]; then echo amd; return 0; fi
  echo cpu
}

# Models a running ComfyUI lacks, as "folder/file" lines (config.comfy_model_choice
# is the same check the studio makes before it draws). Exit 3 when Python can't
# reach it although curl can: comfy_model_choice would then call all three
# missing and we'd fetch 20 GB that ComfyUI may already have.
running_missing() {
  py_studio "
if not config.comfy_alive(sys.argv[1]):
    sys.exit(3)
print('\\n'.join(config.comfy_model_choice(cfg, sys.argv[1])[1]))" "$1"
}

# Does the running ComfyUI list FILE in FOLDER (or the folder's old name)? Then
# only the config names another file — point it at this one, don't download.
running_lists() {   # running_lists URL FOLDER FILE
  py_studio '
alias = {"diffusion_models": ("diffusion_models", "unet"),
         "text_encoders": ("text_encoders", "clip"), "vae": ("vae",)}[sys.argv[2]]
m = config.comfy_models(sys.argv[1]) or {}
sys.exit(0 if any(sys.argv[3] in (m.get(f) or []) for f in alias) else 1)' "$1" "$2" "$3" 2>/dev/null
}

# Is the URL this computer? A ComfyUI elsewhere reports folders on ITS disk —
# downloading "there" here would fill a local path it never reads.
is_local_url() {
  local h=${1#*://}
  h=${h%%/*}; h=${h##*@}
  case $h in
    \[*) h=${h#\[}; h=${h%%\]*} ;;
    *:*) h=${h%:*} ;;
  esac
  h=$(printf '%s' "$h" | tr '[:upper:]' '[:lower:]')
  case $h in localhost|127.*|::1|0.0.0.0) return 0 ;; esac
  local me
  for me in "$(hostname 2>/dev/null)" "$(hostname -s 2>/dev/null)"; do
    me=$(printf '%s' "$me" | tr '[:upper:]' '[:lower:]')
    if [ -n "$me" ] && { [ "$h" = "$me" ] || [ "$h" = "$me.local" ]; }; then return 0; fi
  done
  return 1
}

# Where a running ComfyUI reads a model folder from: the first path it reports.
running_folder() {
  py_studio '
import json, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1].rstrip("/") + "/internal/folder_paths", timeout=4) as r:
        paths = json.load(r).get(sys.argv[2]) or []
except Exception:
    paths = []
first = paths[0] if paths else ""
if isinstance(first, list):          # some versions send [[paths…], [extensions…]]
    first = first[0] if first else ""
print(first)' "$1" "$2" 2>/dev/null || true
}

human_size() {   # bytes -> "12.3 GB"
  awk -v b="$1" 'BEGIN { if (b >= 1e9) printf "%.1f GB", b/1e9; else if (b >= 1e6) printf "%.0f MB", b/1e6; else printf "%d bytes", b }'
}

remote_size() {   # bytes behind a URL, from a HEAD request (follows the CDN redirect); "" if unknown
  local auth=()
  [ -n "${HF_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $HF_TOKEN")
  curl -sIL --max-time 15 ${auth[@]+"${auth[@]}"} "$1" 2>/dev/null \
    | tr -d '\r' | awk 'tolower($1)=="content-length:" { n=$2 } END { if (n) print n }'
}

free_kb() {   # free space where $1 is (or would be created)
  local d=$1
  while [ ! -d "$d" ]; do d=$(dirname "$d"); done
  df -Pk "$d" | awk 'NR==2 { print $4 }'
}

# DL_LIST holds "index|target dir" lines for the models to fetch; MODEL_KEYS the
# config keys that must then name the files we saved (a renamed model in the
# config would otherwise stay "missing" after the download).
DL_LIST=""
MODEL_KEYS=()
model_key() { case $1 in diffusion_models) echo comfyui.unet ;; text_encoders) echo comfyui.clip ;; vae) echo comfyui.vae ;; esac; }
plan_model() { DL_LIST="${DL_LIST}$1|$2
"; }

download_models() {
  local n dir folder file src dest url size total=0 need_kb
  [ -n "$DL_LIST" ] || { good "All three Z-Image Turbo models are already there."; return 0; }
  step "Models to download"
  while IFS='|' read -r n dir; do
    [ -n "$n" ] || continue
    read -r folder file src <<<"$(model_info "$n")"
    url="$HF_BASE/$src"
    size=$(remote_size "$url")
    [ -n "$size" ] && total=$((total + size))
    note "$file  ($( [ -n "$size" ] && human_size "$size" || echo "size unknown"))  → $dir/$file"
  done <<EOF
$DL_LIST
EOF
  if [ "$total" -gt 0 ]; then note "Total: $(human_size "$total")"; else note "Total: about 20 GB"; fi
  dir=$(printf '%s' "$DL_LIST" | head -n 1 | cut -d'|' -f2)
  need_kb=$(( total > 0 ? total / 1024 + 2097152 : 22020096 ))   # + 2 GB headroom
  if [ "$(free_kb "$dir")" -lt "$need_kb" ]; then
    warn "only $(( $(free_kb "$dir") / 1048576 )) GB free near $dir — the download may not fit"
  fi
  if [ "$DRY" = 1 ]; then
    note "[dry-run] nothing downloaded (each file: curl -L --fail -C - → <file>.part, then renamed)"
    return 0
  fi
  confirm "Download them now? (resumable — re-run this script if it stops)" y \
    || die "skipped the download — run scripts/setup_comfyui.sh --models-only when you're ready"
  while IFS='|' read -r n dir; do
    [ -n "$n" ] || continue
    read -r folder file src <<<"$(model_info "$n")"
    dest="$dir/$file"
    mkdir -p "$dir"
    step "Downloading $file"
    local auth=() meter=()
    [ -n "${HF_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $HF_TOKEN")
    [ -t 2 ] && meter=(--progress-bar)
    # .part + rename: a file at the final name is always complete, so "present and
    # non-empty" is a safe skip test; -C - resumes the .part after a dropped connection.
    curl -L --fail --retry 3 --retry-delay 5 -C - ${meter[@]+"${meter[@]}"} ${auth[@]+"${auth[@]}"} \
      -o "$dest.part" "$HF_BASE/$src" \
      </dev/null || die "download of $file failed — re-run to resume"
    mv "$dest.part" "$dest"
    MODEL_KEYS+=("$(model_key "$folder")" "$file")
    good "saved $dest"
  done <<EOF
$DL_LIST
EOF
}

# Plan downloads against folders on disk (ComfyUI isn't running, or --workspace was given).
plan_from_workspace() {
  local n folder file src
  for n in 1 2 3; do
    read -r folder file src <<<"$(model_info "$n")"
    if [ -s "$WS/models/$folder/$file" ]; then
      note "have $folder/$file"
      MODEL_KEYS+=("$(model_key "$folder")" "$file")   # in case the config names another file
    elif [ "$folder" = vae ] && [ -s "$WS/models/vae/ae.safetensors" ]; then
      note "have vae/ae.safetensors (upstream's name — the studio accepts it)"
    else
      plan_model "$n" "$WS/models/$folder"
    fi
  done
}

wait_for() {   # wait_for URL SECONDS
  local deadline=$((SECONDS + $2))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if alive "$1"; then return 0; fi
    sleep 2
  done
  return 1
}

write_config() {   # write_config URL [WORKSPACE]
  local args=(image_backend comfyui comfyui.url "$1")
  [ -n "${2:-}" ] && args+=(comfyui.workspace "$2")
  args+=(${MODEL_KEYS[@]+"${MODEL_KEYS[@]}"})
  step "Updating studio.config.json"
  run "$CPY" "$REPO/scripts/configure.py" init
  run "$CPY" "$REPO/scripts/configure.py" set --string "${args[@]}"
}

# ------------------------------------------------------------------ main ---
[ "$DRY" = 1 ] && step "Dry run — nothing will be installed, downloaded or written"
command -v curl >/dev/null 2>&1 || die "curl is needed (it ships with macOS; on Linux: sudo apt install curl)"

RUNNING=$(find_running)

if [ -n "$RUNNING" ]; then
  # ---------- a ComfyUI is already up: just make sure it has the models
  step "ComfyUI is already running at $RUNNING — not installing anything"
  rc=0
  missing=$(running_missing "$RUNNING") || rc=$?
  if [ "$rc" = 3 ]; then
    die "curl reaches $RUNNING but Python can't (an http_proxy / no_proxy setting?) — the studio asks ComfyUI from Python, so fix that first"
  elif [ "$rc" != 0 ]; then
    die "couldn't ask $RUNNING which models it has"
  fi
  LOCAL=1
  is_local_url "$RUNNING" || LOCAL=0
  REMOTE_TODO=""
  if [ -z "$missing" ]; then
    good "It has all three Z-Image Turbo models."
  else
    note "It's missing: $(printf '%s' "$missing" | tr '\n' ' ')"
    for n in 1 2 3; do
      read -r folder file src <<<"$(model_info "$n")"
      case $'\n'"$missing" in *$'\n'"$folder/"*) ;; *) continue ;; esac
      if running_lists "$RUNNING" "$folder" "$file"; then
        # the config names some other file; ours is already there
        note "it already has $folder/$file — pointing the config at that"
        MODEL_KEYS+=("$(model_key "$folder")" "$file")
        continue
      fi
      dir=""
      if [ "$WS_GIVEN" = 1 ]; then
        dir="$WS/models/$folder"
      elif [ "$LOCAL" = 1 ]; then
        dir=$(running_folder "$RUNNING" "$folder")
      fi
      if [ -z "$dir" ] && [ -n "$TTY_IN" ]; then
        # an older ComfyUI without /internal/folder_paths, or one on another
        # computer whose folder may be mounted here: ask once, reuse for the rest
        if [ "$LOCAL" = 1 ]; then
          printf 'Where is that ComfyUI installed? (the folder with main.py) ' >&2
        else
          printf 'That ComfyUI is on another computer. If its folder is mounted here, type the path (the folder with main.py); else press Enter: ' >&2
        fi
        if [ "$TTY_IN" = stdin ]; then IFS= read -r WS || true; else IFS= read -r WS </dev/tty || true; fi
        case $WS in "") ;; /*) WS_GIVEN=1 ;; *) WS="$PWD/$WS"; WS_GIVEN=1 ;; esac
        if [ "$WS_GIVEN" = 1 ]; then dir="$WS/models/$folder"; fi
      fi
      if [ -z "$dir" ]; then
        if [ "$LOCAL" = 0 ]; then
          REMOTE_TODO="${REMOTE_TODO}$folder/$file  <-  $HF_BASE/$src
"
          continue
        fi
        die "can't tell where that ComfyUI keeps its models — re-run with --workspace /path/to/ComfyUI"
      fi
      if [ -s "$dir/$file" ]; then
        note "have $dir/$file — pointing the config at it"
        MODEL_KEYS+=("$(model_key "$folder")" "$file")
        continue
      fi
      plan_model "$n" "$dir"
    done
    if [ -n "$DL_LIST" ]; then
      download_models
      note "ComfyUI lists new model files on its next request — no restart needed."
    fi
  fi
  ws_for_config=""
  if [ "$WS_GIVEN" = 1 ] && [ -f "$WS/main.py" ]; then ws_for_config=$WS; fi
  write_config "$RUNNING" "$ws_for_config"
  if [ -n "$REMOTE_TODO" ]; then
    warn "That ComfyUI runs on another computer — this script can only save files on this one."
    note "On that computer, put these in its ComfyUI/models folders (or run this script there with --models-only):"
    printf '%s' "$REMOTE_TODO" | while IFS= read -r line; do if [ -n "$line" ]; then note "  $line"; fi; done
    note "Or, if its ComfyUI folder is mounted here: re-run with --workspace /path/to/that/ComfyUI"
    exit 1
  fi
  good "Done — the studio will draw with the ComfyUI at $RUNNING."
  exit 0
fi

if [ -n "$URL" ]; then note "Nothing answers at $URL."; else note "No ComfyUI is running on 127.0.0.1:8188, :8000 or :8189."; fi

if [ "$MODELS_ONLY" = 1 ]; then
  # ---------- just the files, into the workspace
  step "Checking models in $WS/models"
  plan_from_workspace
  download_models
  if [ -f "$WS/main.py" ]; then write_config "${URL:-http://127.0.0.1:8188}" "$WS"; fi
  exit 0
fi

# ---------- install
PORT=$(url_port "${URL:-http://127.0.0.1:8188}")
LAUNCH_URL="http://127.0.0.1:$PORT"
KIND=$(detect_gpu)
step "Installing ComfyUI into $WS  (GPU: $KIND)"
case $KIND in
  cpu) warn "no supported GPU found — ComfyUI will run on the CPU, and each picture may take minutes."
       warn "Claude Code (./install.sh --images claude) is the better choice on this computer." ;;
esac
if [ -f "$WS/main.py" ]; then
  note "ComfyUI is already installed there — keeping it."
elif [ -e "$WS" ] && [ -n "$(ls -A "$WS" 2>/dev/null)" ]; then
  die "$WS exists and isn't a ComfyUI folder — pick another with --workspace"
fi
if [ "$DRY" != 1 ] && ! confirm "Install ComfyUI into $WS and download ~20 GB of models?" y; then
  die "cancelled"
fi

PY=$(find_python) || die "no Python 3.10+ found for ComfyUI — see ./install.sh's Python notes"
VC="$REPO/.venv-comfy"
note "comfy-cli goes in .venv-comfy (Python: $("$PY" -V 2>&1))"
if [ ! -x "$VC/bin/python" ]; then run "$PY" -m venv "$VC"; fi
run "$VC/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip comfy-cli
run "$VC/bin/comfy" --skip-prompt tracking disable
if [ ! -f "$WS/main.py" ]; then
  # comfy-cli installs ComfyUI's own requirements (PyTorch for this GPU) into
  # the Python it runs from — .venv-comfy — so the studio's .venv stays small.
  run "$VC/bin/comfy" --skip-prompt --workspace "$WS" install "--$KIND"
elif [ "$DRY" != 1 ] && ! "$VC/bin/python" -c 'import torch' >/dev/null 2>&1; then
  note "Installing ComfyUI's Python packages into .venv-comfy"
  run "$VC/bin/python" -m pip install --quiet --disable-pip-version-check -r "$WS/requirements.txt"
fi

step "Models"
plan_from_workspace
download_models

if [ "$NO_LAUNCH" = 1 ]; then
  note "Not launching (--no-launch). ./start.sh launches it when the studio starts."
else
  step "Launching ComfyUI on $LAUNCH_URL"
  run "$VC/bin/comfy" --skip-prompt --workspace "$WS" launch --background -- --listen 127.0.0.1 --port "$PORT"
  if [ "$DRY" != 1 ]; then
    if wait_for "$LAUNCH_URL" 120; then good "ComfyUI is up."
    else warn "ComfyUI didn't answer within 2 minutes — check: $VC/bin/comfy --workspace \"$WS\" launch"; fi
  fi
fi
write_config "$LAUNCH_URL" "$WS"
good "Done — the studio will draw with ComfyUI at $LAUNCH_URL."
