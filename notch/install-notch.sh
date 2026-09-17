#!/usr/bin/env bash
# ============================================================================
#  Installs the notch. NO ROOT ANYWHERE - it is a plain GTK client of your own
#  X session, installed into ~/.local/bin and run by a systemd *user* unit.
#
#    bash ~/mrog/notch/install-notch.sh
#
#  To remove all of it:
#    systemctl --user disable --now mrog-notch.service
#    rm -f ~/.local/bin/mrog-notch ~/.config/systemd/user/mrog-notch.service
# ============================================================================
set -euo pipefail
[[ $EUID -ne 0 ]] || { echo "do NOT run this as root - it installs into your own session"; exit 1; }
SRC="${MROG_ROOT:-$HOME/mrog}/notch"

install -d -m 0755 "$HOME/.local/bin" "$HOME/.config/systemd/user"
install -m 0755 "$SRC/notch.py"          "$HOME/.local/bin/mrog-notch"
# The GPU is read in a short-lived child so that libnvidia-ml's ~20 MB is
# handed back when it exits - ctypes never dlclose()s, so an in-process read
# would keep that memory for the life of the notch.
install -m 0755 "$SRC/mrog-gpu-helper.py" "$HOME/.local/bin/mrog-gpu-helper"
# The fleet probe touches the network, so it too lives outside the UI loop.
install -m 0755 "$SRC/mrog-fleet-helper.py" "$HOME/.local/bin/mrog-fleet-helper"
# The ASK pill is exec'd into the notch namespace at startup, so it must be installed too --
# without this the deployed mrog-notch has no askpill.py beside it and the pill never loads.
# 🔴 SYMLINK, NOT A COPY. A copy here is loader candidate #2 and BEATS the source at #3,
# so every subsequent edit to ~/mrog/notch/askpill.py changes nothing that runs -- silently.
# That cost hours on 2026-09-06 and is the same defect twice over (see docs
# mrog/90-traps.md). One file, one truth.
[ -f "$SRC/askpill.py" ] && ln -sfn "$SRC/askpill.py" "$HOME/.local/bin/mrog-askpill.py"
install -m 0644 "$SRC/mrog-notch.service" "$HOME/.config/systemd/user/mrog-notch.service"

# The notch reads the input-lease panic file from here; create it now so the
# directory exists before mrog-input ever runs.
install -d -m 0700 "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/mrog"

systemctl --user daemon-reload
systemctl --user enable mrog-notch.service
# restart, NOT "enable --now": --now is a no-op on an already-running unit, so
# re-running this installer after an edit would silently keep the OLD binary
# alive with no error and an unchanged PID.
systemctl --user restart mrog-notch.service

sleep 2
if systemctl --user is-active --quiet mrog-notch.service; then
  echo "notch: running"
else
  echo "notch: FAILED to start - journalctl --user -u mrog-notch -n 30"
  exit 1
fi

cat <<'DONE'

Installed and started. Prove it:

  Look at the top centre of the screen  -> pill with CPU / RAM / temp / battery
  Click the pill                        -> drops down a detail panel
  Right-click the pill                  -> quits (systemd will NOT restart it;
                                           use systemctl --user start mrog-notch)

  systemctl --user status mrog-notch    -> active
  ps -o rss= -C mrog-notch              -> expect ~50 MB

The lease dot at the far left is the point of the thing:
  grey  = no lease            amber = mrog root lease live (with countdown)
  red   = an agent holds your keyboard/mouse
DONE
