# Architecture

## What runs

**One process** — `~/.local/bin/mrog-notch`, a systemd *user* service — draws four
pill windows and owns the drag-to-snap watcher. It spawns short-lived children
for anything that could block or bloat it.

    mrog-notch  (systemd --user, WantedBy=default.target)
      ├── SystemPill    centre    CPU / RAM / temp / GPU / battery, camera, REC, STOP
      ├── NotePill      74%       scratchpad, drops into the top-right corner
      ├── FleetPill     right     FLEET n/4, per-host latency
      ├── WorkspacePill 26%       LAYOUTS, auto-hidden until the pointer arrives
      ├── SnapZones               two one-inch drop slivers + the layout chooser
      ├── KillDot                 STOP capsule, only while an input lease is live
      ├── mrog-gpu-helper         child, only while the GPU is worth reading
      └── mrog-fleet-helper       child, always — it touches the network

## Why children, not threads

Two different reasons, and both were forced by measurement:

- **The GPU helper** exists because `ctypes` never `dlclose()`s. Loading NVML
  costs ~20 MB that is **never returned** to the process, even after
  `nvmlShutdown()`. In a child, the kernel takes it back on exit.
- **The fleet helper** exists because it touches the **network**. The precedent
  is on this machine: `fleet-status` v1 called restic over sftp (51 s) from a
  desklet timer and froze the entire desktop.

**The rule: nothing that can block, and nothing that leaks memory, runs in the
UI process.**

## What it costs

| | |
|---|---|
| notch, at rest | **~50 MB**, GPU asleep, zero nvidia maps |
| notch, with the scratchpad loaded | ~62 MB (GtkSourceView) |
| gpu helper, while alive | 33 MB — and only while the card is already awake |
| fleet helper | small; one TCP sweep of 4 hosts every 30 s, **35 ms** per sweep |
| idle CPU | **~0.3–0.4 %** of one core, scaling with window count |
| snap watcher | **no measurable cost** — identical with `MROG_NOTCH_SNAP=0` |

Idle CPU moves with the number of open windows, not with features: each pill
does one X round trip per second for the fullscreen check.

## The load-bearing fact

**This machine runs X11** (`XDG_SESSION_TYPE=x11`, Cinnamon 6.6.9 / muffin 6.6.3).
The notch, XTEST input, `x11grab` capture and `x11vnc` are all easy here and
hard-to-impossible on Wayland. A `cinnamon-wayland.desktop` session exists —
**switching to it throws all four away.** Do not propose it.

## Environment switches

    MROG_NOTCH_FLEET=0     no FLEET pill
    MROG_NOTCH_NOTE=0      no NOTE pill
    MROG_NOTCH_SNAP=0      no drag-to-snap
    MROG_NOTCH_GPU=        auto (default) | ac | force | off
    MROG_NOTCH_ASK=0       capture silently, no save dialog
    MROG_NOTCH_HOME=       where captures and notes go
    MROG_NOTCH_DEBUG=1     print layout geometry on every relayout

## Storage

    ~/Documents/mrog/Screenshots/   shot-<ts>.png
    ~/Documents/mrog/Recordings/    rec-<ts>.mkv
    ~/Documents/mrog/Notes/         scratch.txt + state.json

One folder to back up, one place to look.
