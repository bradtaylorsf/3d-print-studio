#!/bin/bash
# Build "3D Print Studio.app" (macOS) from studio/static/icon.svg — a Dock /
# Spotlight icon that starts the studio in THIS clone and opens kid mode.
# Rerun any time (e.g. after moving the clone); safe to overwrite.
#
#   studio/make_app.sh [dest_dir]        (default ~/Applications; PORT=N to bake in another port)
set -euo pipefail

[ "$(uname -s)" = "Darwin" ] || { echo "make_app.sh builds a macOS app — on Linux, run ./start.sh"; exit 1; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Applications}"
PORT="${PORT:-8765}"
# baked into the launcher script below, so it must be a plain number
case $PORT in ''|*[!0-9]*) echo "make_app.sh: PORT must be a number (got '$PORT')" >&2; exit 2 ;; esac
APP="$DEST/3D Print Studio.app"
SVG="$REPO/studio/static/icon.svg"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) rasterize the SVG with Quick Look (stock macOS), then build the .icns
qlmanage -t -s 1024 -o "$TMP" "$SVG" >/dev/null
[ -f "$TMP/icon.svg.png" ] || { echo "SVG rasterize failed"; exit 1; }
ICONSET="$TMP/studio.iconset"
mkdir "$ICONSET"
for s in 16 32 64 128 256 512; do
  sips -z "$s" "$s" "$TMP/icon.svg.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z "$d" "$d" "$TMP/icon.svg.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$TMP/studio.icns"

# 2) app bundle
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/studio.icns" "$APP/Contents/Resources/studio.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>3D Print Studio</string>
  <key>CFBundleDisplayName</key><string>3D Print Studio</string>
  <key>CFBundleIdentifier</key><string>local.printstudio.launcher</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>studio</string>
  <key>CFBundleIconFile</key><string>studio</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

# The launcher bakes in this clone's path (quoted for spaces) and the port.
printf -v Q_REPO '%q' "$REPO"
cat > "$APP/Contents/MacOS/studio" <<LAUNCH
#!/bin/bash
REPO=$Q_REPO
URL="http://localhost:$PORT/?kid=1"
# Already running: just bring up the page.
if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/"; then
  open "\$URL"
  exit 0
fi
# Never set up (no .venv): run the first-time install where it can be seen —
# in a Terminal window, which asks its questions and then starts the studio.
if [ ! -x "\$REPO/.venv/bin/python" ]; then
  chmod +x "\$REPO/Studio.command" 2>/dev/null   # Terminal won't run it without the bit (a zip may drop it)
  open -a Terminal "\$REPO/Studio.command"
  exit 0
fi
# Start the server DETACHED and exit — LaunchServices kills script apps
# that linger, so the app process must return immediately. start.sh opens
# the browser once the server answers. Run through bash, not the exec bit.
mkdir -p "\$HOME/Library/Logs"
PORT=$PORT nohup /bin/bash "\$REPO/start.sh" >>"\$HOME/Library/Logs/3D Print Studio.log" 2>&1 </dev/null &
disown
exit 0
LAUNCH
chmod +x "$APP/Contents/MacOS/studio"

# Ad-hoc sign: gives the app a stable identity so macOS shows the
# Documents-access permission prompt instead of silently denying it.
codesign --force --deep -s - "$APP"

touch "$APP"   # nudge Finder to refresh the icon
echo "Built: $APP  (drag it to the Dock; Spotlight will index it)"
echo "It starts the studio in $REPO — rebuild if you move that folder."
