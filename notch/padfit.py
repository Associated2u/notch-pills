#!/usr/bin/env python3
"""padfit — does the ASK pad fit the window it is drawn into?

PROOF BY EFFECT for the shape defect. Builds the real AskPad (not a mock of it) in an
OFFSCREEN window -- never mapped, no grab, no override-redirect surface, so it cannot touch
Chris's session -- and compares what GTK wants to draw against:

  (a) the OLD hardcoded rect 360x150  -> must FAIL, or the defect being fixed was imaginary
  (b) the window's real free space    -> must PASS, or the fix just moved the clipping

A check that only ever passes proves nothing (CLAUDE.md rule 8.4/8.5).
"""
import os, sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

sys.path.insert(0, os.path.expanduser("~/mrog/notch"))
src = open(os.path.expanduser("~/mrog/notch/askpill.py")).read()

# askpill.py is exec'd into notch.py's namespace and subclasses Notch. We only need AskPad,
# so give the exec the few names its module level touches and stub the rest.
ns = {"__name__": "askpill", "Gtk": Gtk}
import cairo
from gi.repository import Gdk, GLib, Pango
ns.update({"os": os, "time": __import__("time"), "cairo": cairo, "gi": gi,
           "Gdk": Gdk, "GLib": GLib, "Pango": Pango, "Notch": object})
exec(compile(src, "askpill.py", "exec"), ns)

AskPad = ns["AskPad"]
intents = ns["_load_intents"]()[0]
if not intents:
    print("FAIL  registry returned no intents — the pad would have an empty ask row"); sys.exit(1)


class StubOwner:
    """Only what AskPad.__init__ touches."""
    def __init__(self):
        self.intents = intents
        self._tips = ns["_load_intents"]()[1]
    def intent_tip(self, i):
        return self._tips.get(i, "")


off = Gtk.OffscreenWindow()
pad = AskPad(StubOwner())
off.add(pad)
off.show_all()
while Gtk.events_pending():
    Gtk.main_iteration()

nat = pad.get_preferred_size()[1]
W, PILL_H, PANEL_H = 760, 30, 229
free_w, free_h = W - 16, PANEL_H - 4
OLD_W, OLD_H = 360, 150

print("  intents in registry : %d  (%s)" % (len(intents), ", ".join(i[1] for i in intents)))
print("  pad wants           : %d x %d" % (nat.width, nat.height))
print("  old hardcoded rect  : %d x %d" % (OLD_W, OLD_H))
print("  window free space   : %d x %d" % (free_w, free_h))

overflow = nat.width > OLD_W or nat.height > OLD_H
print("\n  (a) against the OLD constants : %s" % (
      "OVERFLOWS by %+d x %+d  -> the unclickable-controls defect was REAL"
      % (nat.width - OLD_W, nat.height - OLD_H) if overflow
      else "fits — defect NOT reproduced, the fix is unproven"))
fits = nat.width <= free_w and nat.height <= free_h
print("  (b) against the WINDOW        : %s" % (
      "FITS with %d x %d to spare" % (free_w - nat.width, free_h - nat.height) if fits
      else "STILL CLIPS by %+d x %+d" % (nat.width - free_w, nat.height - free_h)))

print("\nVERDICT: %s" % ("PASS" if (overflow and fits) else "FAIL"))
sys.exit(0 if (overflow and fits) else 1)
