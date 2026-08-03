#!/bin/bash
# One-command launcher: sets up Python env on first run, starts the studio,
# and opens the browser. Safe to re-run; reuses everything after first time.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "First run — setting up the Python environment (one time, a few minutes)…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet trimesh manifold3d numpy scipy shapely matplotlib pillow opencv-python-headless scikit-image
  echo "Setup done."
fi

URL="http://localhost:8765/"
( sleep 1.5
  if command -v open >/dev/null; then open "$URL"        # macOS
  elif command -v xdg-open >/dev/null; then xdg-open "$URL"  # Linux
  fi ) &

exec .venv/bin/python studio/server.py
