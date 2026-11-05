#!/bin/bash
# Double-click me in Finder to launch 3D Print Studio. The first time, this
# Terminal window asks a couple of setup questions; after that it just starts
# the studio and opens it in your browser. Close the window to stop it.
cd "$(dirname "$0")" || exit 1
exec bash ./start.sh "$@"
