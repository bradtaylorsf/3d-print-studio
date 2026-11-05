#!/bin/zsh
# One-time (re)vendoring of three.js into studio/static/three/.
# Already run — only needed again to upgrade the pinned version.
set -euo pipefail
VERSION=0.169.0
DEST="$(cd "$(dirname "$0")" && pwd)/static/three"
TMP="$(mktemp -d)"
cd "$TMP"
npm pack "three@$VERSION" --silent
tar xf "three-$VERSION.tgz"
mkdir -p "$DEST"
cp package/build/three.module.min.js \
   package/examples/jsm/controls/OrbitControls.js \
   package/examples/jsm/loaders/STLLoader.js "$DEST/"
cp package/LICENSE "$DEST/LICENSE"      # MIT asks for the notice to travel with the copy
rm -rf "$TMP"
echo "Vendored three@$VERSION into $DEST"
