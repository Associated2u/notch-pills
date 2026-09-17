# The pill framework — and how to add one

## What a pill is

A borderless GTK3 `DOCK` window at the top of the primary monitor, drawn entirely
in cairo, with an **input shape** so only the visible part accepts clicks and the
transparent remainder never steals one from the window underneath.

All four subclass `Notch`. A new pill is ~40 lines because it inherits the whole
window plumbing: shape, hide-on-fullscreen, hover peek, expand, drop-down.

## Adding a pill

    class MyPill(Notch):
        ANCHOR        = "center" | "right" | "frac"   # frac uses ANCHOR_FRAC
        ANCHOR_FRAC   = 0.26                          # centre, as a screen fraction
        BUTTONS       = False        # camera/REC belong to the system pill only
        NEEDS_SENSORS = False        # do not inherit costs you do not use
        NEEDS_GPU     = False
        ALWAYS_HIDDEN = False        # True = invisible until the pointer arrives
        MIN_PILL_W    = 130
        SHOWS_KILL    = False        # only the system pill owns the STOP capsule

        def pill_parts(self):                 # -> [str], joined into the pill
        def panel_rows(self, kind, dot, lbl): # -> [(key, value, colour)]
        def lease_state(self):                # -> (kind, dot_colour, label)
        def on_pill_click(self):              # default: toggle the drop-down

Then instantiate it in `__main__`. Existing anchors: system `center`, LAYOUTS
`frac 0.26`, NOTE `frac 0.74`, FLEET `right`.

🔴 **`NEEDS_GPU` / `NEEDS_SENSORS` are not decoration.** `FleetPill` first
inherited a second `GpuProbe` and quietly ran a duplicate GPU helper, holding a
discrete GPU awake for a pill that shows no GPU. **A subclass inherits the
parent's costs, not just its looks — check the child process list after adding
one.**

## Anchoring

🔴 **Anything anchored to the screen must derive its position from the screen,
not from its container.** The scratchpad's first version resized the pill's
window to fit the pad; because the pill is drawn *inside* that window, the pill
slid around with it. The fix: the window is fixed and oversized, only the pad
moves inside, and `pill_x_for()` computes from the monitor. Verified across
three sizes — window constant, pill centre constant at 916.

## Drawing

- `rounded(cr, x, y, w, h, r, top=, bottom=)` for the capsule shapes.
- 🔴 **`show_text()` leaves a current point, and a following `arc()` draws a LINE
  to it.** That put a stripe from the pill text through the camera to the REC
  dot. Call `cr.new_path()` before button geometry and `new_sub_path()` before
  every arc.
- The pill is **content-sized**: measure the text, size the capsule, recentre.
  A fixed width either clips a variable segment (GPU appears and disappears) or
  leaves a lopsided gap.

## Never block

`tick()` runs at 1 Hz on the GTK main loop. No subprocess, no network, no
`nvidia-smi`. Sensors are `/proc` and `/sys` reads costing well under a
millisecond. Anything slower goes in a child process — see
[01-architecture](01-architecture.md).

## Hiding

`ALWAYS_HIDDEN` pills draw nothing until the pointer reaches a 4 px strip at the
top. Fullscreen hiding applies to all pills **except** while a lease is live —
the red dot is the only sign an agent holds the keyboard, so nothing may conceal
it.
