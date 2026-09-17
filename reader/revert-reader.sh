#!/usr/bin/env bash
#  Removes the reader and puts the notch back to the committed version.
set -euo pipefail
rm -f "$HOME/.local/bin/mrog-read"
cd "$HOME/mrog" && git checkout -- notch/notch.py
install -m 0755 "$HOME/mrog/notch/notch.py" "$HOME/.local/bin/mrog-notch"
systemctl --user restart mrog-notch.service
sleep 2
echo "reverted. notch MainPID now $(systemctl --user show -p MainPID --value mrog-notch.service)"
