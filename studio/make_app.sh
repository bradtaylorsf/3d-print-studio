#!/bin/zsh
# Build "3D Print Studio.app" (macOS) from studio/static/icon.svg.
# Creates ~/Applications/3D Print Studio.app pointing at THIS clone.
# Rerun any time; safe to overwrite. Usage: studio/make_app.sh [dest_dir]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/3D Print Studio.app"
SVG="$REPO/studio/static/icon.svg"
TMP="$(mktemp -d)"

# 1) rasterize the SVG with Quick Look (stock macOS), then build the .icns
qlmanage -t -s 1024 -o "$TMP" "$SVG" >/dev/null
[ -f "$TMP/icon.svg.png" ] || { echo "SVG rasterize failed"; exit 1; }
ICONSET="$TMP/studio.iconset"
mkdir "$ICONSET"
for s in 16 32 64 128 256 512; do
  sips -z $s $s "$TMP/icon.svg.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$TMP/icon.svg.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
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

cat > "$APP/Contents/MacOS/studio" <<LAUNCH
#!/bin/bash
# If the studio is already running, just bring up the page.
if curl -s -o /dev/null --max-time 1 http://localhost:8765/; then
  open "http://localhost:8765/"
  exit 0
fi
# Start the server DETACHED and exit — LaunchServices kills script apps
# that linger, so the app process must return immediately.
nohup "$REPO/start.sh" >/dev/null 2>&1 &
disown
exit 0
LAUNCH
chmod +x "$APP/Contents/MacOS/studio"

# Ad-hoc sign: gives the app a stable identity so macOS shows the
# Documents-access permission prompt instead of silently denying it.
codesign --force --deep -s - "$APP"

rm -rf "$TMP"
touch "$APP"   # nudge Finder to refresh the icon
echo "Built: $APP  (drag it to the Dock; Alfred/Spotlight will index it)"
