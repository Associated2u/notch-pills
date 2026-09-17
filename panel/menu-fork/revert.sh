#!/usr/bin/env bash
# Remove the forked menu applet. Cinnamon falls straight back to the stock one.
set -euo pipefail
DST="$HOME/.local/share/cinnamon/applets/menu@cinnamon.org"
if [[ -d $DST ]]; then
    rm -rf "$DST"
    echo "forked menu removed - run 'panel-app apply' to load the stock menu again"
else
    echo "no forked menu installed; nothing to do"
fi
