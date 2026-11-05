#!/usr/bin/env bash
# start.sh — launch 3D Print Studio and open it in the browser (kid mode).
#
#   ./start.sh [--port N] [--no-browser] [more server args…]
#
# PORT=N and STUDIO_NO_BROWSER=1 work too. Safe to re-run:
#   - first run (no .venv): runs ./install.sh — with its questions in a terminal,
#     with defaults (Claude draws) when there's no terminal;
#   - requirements.txt changed since the last install (a `git pull`): updates packages;
#   - pictures come from a ComfyUI that scripts/setup_comfyui.sh installed and it
#     isn't running: launches it in the background first;
#   - the studio is already running on the port: just opens the page.
# Works with macOS's stock /bin/bash 3.2.
set -euo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8765}
OPEN_BROWSER=1
case ${STUDIO_NO_BROWSER:-0} in 0|""|false|no) ;; *) OPEN_BROWSER=0 ;; esac
EXTRA=()
while [ $# -gt 0 ]; do
  case $1 in
    --port) [ $# -ge 2 ] || { echo "start.sh: --port needs a number" >&2; exit 2; }; PORT=$2; shift 2 ;;
    --port=*) PORT=${1#*=}; shift ;;
    --no-browser) OPEN_BROWSER=0; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done
case $PORT in ''|*[!0-9]*) echo "start.sh: port must be a number (got '$PORT')" >&2; exit 2 ;; esac
URL="http://localhost:$PORT/?kid=1"

have() { command -v "$1" >/dev/null 2>&1; }

open_browser() {
  [ "$OPEN_BROWSER" = 1 ] || return 0
  if [ "$(uname -s)" = "Darwin" ] && have open; then open "$URL"
  elif have xdg-open && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then xdg-open "$URL" >/dev/null 2>&1 || true
  elif have wslview; then wslview "$URL" >/dev/null 2>&1 || true
  else echo "Open $URL in a browser."
  fi
}

# Already running here? Then this is a "show me the studio" click. A refused
# connection answers instantly, so the generous timeout only matters when
# something listens: /api/setup probes ComfyUI, and a configured ComfyUI on a
# sleeping machine takes ~2 s — a 1 s limit missed the running studio and
# started a second one that died on "Could not bind port".
resp=""
if have curl; then
  resp=$(curl -s -w '\n%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/api/setup" 2>/dev/null || true)
fi
code=${resp##*$'\n'}
case $code in
  200|500)   # 500: the studio's own "setup checks failed" — still the studio
    echo "The studio is already running: $URL"
    open_browser
    exit 0 ;;
  404)
    case $resp in
      *"unknown route"*)   # a studio from before /api/setup existed
        echo "An older studio is already running: $URL  (stop it and run ./start.sh again to update it)"
        open_browser
        exit 0 ;;
    esac
    echo "start.sh: something else is using port $PORT — try: ./start.sh --port $((PORT + 1))" >&2
    exit 1 ;;
  000|"") ;;
  *)
    echo "start.sh: something else is using port $PORT (HTTP $code at /api/setup) — try: ./start.sh --port $((PORT + 1))" >&2
    exit 1 ;;
esac

# ---- first run / updates
if [ ! -x .venv/bin/python ]; then
  echo "First run — setting up (one time, a few minutes)…"
  if [ -t 0 ] && [ -t 1 ]; then
    bash ./install.sh --no-start
  elif [ -f studio.config.json ]; then
    bash ./install.sh --yes --no-start            # keeps the choices already in the config
  else
    bash ./install.sh --yes --images claude --no-start
  fi
elif ! cmp -s requirements.txt .venv/.studio-requirements.txt; then
  echo "requirements.txt changed — updating Python packages…"
  if .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt; then
    cp requirements.txt .venv/.studio-requirements.txt
  else
    echo "warning: couldn't update the Python packages (offline?) — starting anyway" >&2
  fi
fi

# ---- a ComfyUI we installed, not running yet: start it alongside
comfy_autostart() {
  local info backend alive url ws port log
  info=$(.venv/bin/python - <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, "studio")
import config
cfg = config.load()
b = (cfg.get("image_backend") or "").strip().lower()
b = "comfyui" if b == "comfy" else b
url = (config.get_path(cfg, "comfyui.url") or "").strip().rstrip("/")
ws = os.path.expanduser((config.get_path(cfg, "comfyui.workspace") or "").strip())
alive = b == "comfyui" and config.comfy_url(cfg) is not None
print("\t".join([b or "-", "1" if alive else "0", url or "-", ws or "-"]))
PY
) || return 0
  IFS=$'\t' read -r backend alive url ws <<<"$info"
  [ "$backend" = "comfyui" ] && [ "$alive" = "0" ] || return 0
  [ "$ws" != "-" ] && [ -f "$ws/main.py" ] && [ -x .venv-comfy/bin/comfy ] || return 0
  port=8188
  if [ "$url" != "-" ]; then
    port=${url##*:}; port=${port%%/*}
    case $port in ''|*[!0-9]*) port=8188 ;; esac
  fi
  log="${TMPDIR:-/tmp}"
  log="${log%/}/3d-print-studio-comfyui.log"
  echo "Starting ComfyUI in the background on port $port (log: $log) — pictures work once it's up."
  ( .venv-comfy/bin/comfy --skip-prompt --workspace "$ws" launch --background \
      -- --listen 127.0.0.1 --port "$port" >>"$log" 2>&1 </dev/null & )
}
comfy_autostart

# ---- open the page once the server answers, then hand this process to it
if [ "$OPEN_BROWSER" = 1 ]; then
  (
    i=0
    while [ $i -lt 40 ]; do
      if have curl && curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/" 2>/dev/null; then break; fi
      have curl || { sleep 2; break; }
      sleep 0.5; i=$((i + 1))
    done
    open_browser
  ) &
fi

echo "3D Print Studio: $URL   (Ctrl-C stops it)"
exec .venv/bin/python studio/server.py --port "$PORT" ${EXTRA[@]+"${EXTRA[@]}"}
