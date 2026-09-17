#!/usr/bin/env bash
# Has Mint updated the menu applet since the fork was taken?
set -euo pipefail
SRC=/usr/share/cinnamon/applets/menu@cinnamon.org/applet.js
DST="$HOME/.local/share/cinnamon/applets/menu@cinnamon.org"
[[ -d $DST ]] || { echo "no fork installed"; exit 0; }
have=$(cat "$DST/.upstream-md5" 2>/dev/null || echo none)
now=$(md5sum "$SRC" | awk '{print $1}')
if [[ $have == "$now" ]]; then
    echo "fork is current with upstream ($now)"
else
    echo "UPSTREAM MOVED: forked from $have, system now $now"
    echo "re-run: bash ~/mrog/panel/menu-fork/install.sh && panel-app apply"
fi
