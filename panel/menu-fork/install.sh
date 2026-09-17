#!/usr/bin/env bash
# ============================================================================
#  Give the menu's right-click BOTH bar choices.
#
#  Cinnamon's "Add to panel" targets a single ROLE PROVIDER
#  (Roles.PANEL_LAUNCHER). Only one panel-launchers applet can hold that role,
#  so the menu can only ever offer one bar - that is why you get the left bar
#  and no choice. There is no setting for this; the only way to change it is to
#  override the menu applet.
#
#  Cinnamon loads applets from ~/.local/share/cinnamon/applets FIRST, so this
#  is a USER-LEVEL override. No root anywhere. Fully reversible: delete the
#  directory and the stock menu is back.
#
#  🔴 THE COST, be clear about it: this forks a 3030-line upstream file. Mint
#  updates to the menu applet will NOT reach your copy until you re-run this.
#  `check.sh` tells you when upstream has moved.
#
#    bash ~/mrog/panel/menu-fork/install.sh
#    bash ~/mrog/panel/menu-fork/revert.sh      <- undo, any time
# ============================================================================
set -euo pipefail
[[ $EUID -ne 0 ]] || { echo "do NOT run this as root - it installs into your own session"; exit 1; }
SRC=/usr/share/cinnamon/applets/menu@cinnamon.org
DST="$HOME/.local/share/cinnamon/applets/menu@cinnamon.org"
HERE="$(cd "$(dirname "$0")" && pwd)"

command -v panel-app >/dev/null || { echo "panel-app is not on PATH - install it first"; exit 1; }
[[ -d $SRC ]] || { echo "stock menu applet not found at $SRC"; exit 1; }

install -d "$(dirname "$DST")"
rm -rf "$DST.tmp"
cp -a "$SRC" "$DST.tmp"

# Patch, and refuse loudly if upstream moved out from under the anchors.
python3 "$HERE/patch.py" "$DST.tmp/applet.js" "$HOME" || {
    echo "patch refused - nothing installed, your menu is untouched"
    rm -rf "$DST.tmp"; exit 1; }

node --check "$DST.tmp/applet.js" 2>/dev/null || true   # best-effort syntax sniff
rm -rf "$DST"
mv "$DST.tmp" "$DST"
md5sum "$SRC/applet.js" | awk '{print $1}' > "$DST/.upstream-md5"

cat <<'DONE'

Installed as a USER applet. Restart Cinnamon to load it:

    panel-app apply

Then right-click any app in the menu. You should now see BOTH:
    Add to bottom bar
    Add to left bar

If the menu misbehaves in ANY way, undo it immediately - the stock menu
returns as soon as the directory is gone:

    bash ~/mrog/panel/menu-fork/revert.sh && panel-app apply
DONE
