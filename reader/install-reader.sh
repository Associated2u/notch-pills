#!/usr/bin/env bash
# ============================================================================
#  Installs the mrog READER: a speaking button on the notch pill, plus the
#  `mrog-read` CLI. NO ROOT. Nothing outside $HOME.                LINUX-E3X
#
#    bash ~/mrog/reader/install-reader.sh
#
#  Revert everything:
#    bash ~/mrog/reader/revert-reader.sh
# ============================================================================
set -euo pipefail
[[ $EUID -ne 0 ]] || { echo "do NOT run this as root"; exit 1; }
SRC="${MROG_ROOT:-$HOME/mrog}/reader"

for b in xclip xdotool spd-say paplay tesseract; do
  command -v "$b" >/dev/null || { echo "missing dependency: $b"; exit 1; }
done
python3 -c 'import speechd' 2>/dev/null || { echo "missing python3-speechd"; exit 1; }

install -d -m 0755 "$HOME/.local/bin"
install -m 0755 "$SRC/reader.py" "$HOME/.local/bin/mrog-read"

# The notch imports notch_button from ~/mrog/reader directly (sys.path), so the
# button module is NOT copied - one source of truth, edit and restart.
PRE=$(systemctl --user show -p MainPID --value mrog-notch.service 2>/dev/null || echo 0)
install -m 0755 "${MROG_ROOT:-$HOME/mrog}/notch/notch.py" "$HOME/.local/bin/mrog-notch"

systemctl --user daemon-reload
# restart, NOT "enable --now" - --now is a no-op on a running unit and would
# silently keep the OLD binary alive with an unchanged PID and no error.
systemctl --user restart mrog-notch.service
sleep 2
POST=$(systemctl --user show -p MainPID --value mrog-notch.service 2>/dev/null || echo 0)

echo
echo "notch MainPID: $PRE -> $POST"
[[ "$PRE" != "$POST" && "$POST" != "0" ]] \
  && echo "  OK - the new binary is what is running" \
  || { echo "  FAILED - PID did not change, the old binary is still live"; exit 1; }

systemctl --user is-active --quiet mrog-notch.service \
  && echo "notch: running" || { echo "notch: NOT running"; exit 1; }

# Prove the button module actually loaded inside the notch, not just on disk.
if journalctl --user -u mrog-notch.service --since "30 seconds ago" 2>/dev/null \
     | grep -qi 'notch_button\|ImportError'; then
  echo "  WARNING: notch_button import trouble - check journalctl --user -u mrog-notch"
fi

cat <<'EOF'

  READER installed.

  On the pill:  [>)) ]  [camera]  [o REC]
      click  ->  reads your selection if you have one,
                 otherwise the cursor becomes a crosshair - click any window
      click again while it is speaking  ->  stop

  From a terminal:
      mrog-read                      selection, else newest Claude message
      mrog-read claude --delta       only what Claude has said since last time
      mrog-read window               point-and-read a window (AT-SPI or OCR)
      mrog-read --style gist         10x   headings + warnings only
      mrog-read --style structure    3x    the default
      mrog-read --style skim         2x    lead clause + bolds
      mrog-read --style verbatim     1.2x  everything, code blocks summarised
      mrog-read --rate 60            faster voice (-100..100)
      mrog-read --pacer on           force the follow-along window
      mrog-read --pacer off          audio only
      mrog-read ... --dry            print what it WOULD say, say nothing

  Follow-along window (the pacer): opens automatically for anything over 60
  words. Full text, everything dimmed except the line being spoken, synced to
  the real A2DP delay. Esc stops it.

  Voice:
      $SRC/voice-lab.py             audition 12 voices
      $SRC/voice-lab.py --more      10 more, picked for your ear
      $SRC/voice-lab.py --sweep klatt      same voice, 5 speeds
      $SRC/voice-lab.py --set klatt --rate 40
      $SRC/voice-lab.py --set-pacer off

  Config (shared by button, CLI and lab): ~/.config/mrog/reader.json
EOF
