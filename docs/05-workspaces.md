# Workspace layouts and drag-to-snap

## `~/bin/workspace`

    workspace list | windows | geom
    workspace apply  <layout> [--dry-run] [--monitor <connector|index>]
    workspace launch <layout> [--dry-run]
    workspace place  <winid> <layout> <zone> [--monitor ...]

Three layouts, zones expressed as fractions of the monitor's **work area**
(`Gdk.Monitor.get_workarea`), so panels are respected without hard-coding them.
Config: `~/.config/mrog/workspaces.json`, generated on first run.

| | zones | on eDP-1 |
|---|---|---|
| `split` | 2 | 941x1165 each |
| `main` | 3 | 1242 left, two 640x582 right |
| `quad` | 4 | four 941x582 |

`launch` runs a per-zone command; the default opens a terminal straight into the
work: `ssh -t hub "cd autonomy && exec bash -l -c claude"`. Change `term`
in the config.

## Placement traps

🔴 **A maximized window silently ignores a move** — drop the maximised states
first.

🔴 **`xdotool getwindowgeometry` reports a different origin for reparented
windows.** It said `1967,72 941x1133` for a window `xwininfo` proved was exactly
`1957,0 941x1165`. **Verify with `xwininfo` + `_NET_FRAME_EXTENTS`** (here
`0,0,32,0`); place with `wmctrl -e`, which is frame-correct.

## Drag-to-snap

Start dragging any window and **two one-inch slivers** appear at the top edge,
side by side under the LAYOUTS pill:

    [ screen 2 ][ this screen ]

One inch is computed from the monitor's real DPI (`get_width_mm()`; this panel is
141 dpi), not a guessed pixel count. Small on purpose — a full-width strip was
far too easy to hit by accident. The left sliver only exists while a second
monitor is plugged in, and is drawn dimmer.

Enter a sliver and the chooser opens **directly under it**, labelled with that
monitor's connector (`eDP-1` / `DP-2`), showing the three layouts as cards
divided into zones. The zone under the pointer lights up; release and the window
lands there — on that monitor.

After the pointer leaves, the chooser **lingers 700 ms then fades over 220 ms**.
Returning inside that window cancels it. A chooser that vanishes instantly reads
as a glitch; one that lingers gets in the way.

## 🔴 Why this had to be polled

**While the WM is moving a window it holds a pointer grab** — our windows receive
no motion, enter or button events whatsoever. So both overlays are
**input-transparent** (empty input region) and the whole interaction is driven by
`query_pointer()` with hit-testing against rectangles we compute ourselves.
Ordinary GTK event handlers cannot work here.

Adaptive polling: **200 ms idle, 25 ms during a drag.** Measured identical to a
build with `MROG_NOTCH_SNAP=0`, so it costs nothing at rest. A 100 ms idle poll
*was* visible (0.599 % vs 0.300 %).

⚠️ **An unmapped `POPUP` does not keep geometry set at construction** — both
overlays sat at 0,0 on the *external* monitor until they were re-placed at the
moment the drag starts.
