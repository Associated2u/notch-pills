# notch-pills

A row of small, borderless status pills along the top edge of an X11 desktop, drawn in
cairo by one Python/GTK3 process, that read the machine, capture the screen, hold a
scratchpad, snap windows into layouts, show who — human or agent — holds the keyboard,
and **send whatever is on screen to an AI agent and keep talking to it**.

Built for Linux Mint / Cinnamon on X11. No root, no compositor plugin, no applet: it is a
plain client of your own X session, run by a `systemd --user` unit, ~60 MB at rest,
0.3–0.4 % of one core.

```
 [LAYOUTS]        [CPU 3.1%  RAM 3.5/23.1G  59°C  GPU 0.3/4.0G 53°C  81%  ● ◉ ▶ 📷 ●]        [NOTE]   [ASK ● HERMES]   [FLEET 4/4]
   26%                                        centre                                              74%     right-ish        right
```

Each pill drops a panel down when clicked. Each hides while a window is fullscreen or
maximised, leaving a 4 px strip at the top edge that reveals it on hover — **except while an
agent holds an input lease**: the red dot is the only sign a machine is typing for you, and
nothing may conceal it.

## Why not an applet

An applet is JavaScript running *inside* the Cinnamon process, so any stall in it freezes
the whole desktop. That happened here: a desklet made a 51 s network call on Cinnamon's main
loop and the UI was dead while the load average stayed normal. These pills own their own
process and their own main loop, and follow one hard rule: **nothing in the 1 Hz tick may
block** — no subprocess, no network, no `nvidia-smi`. Every sensor is a `/proc` or `/sys` read
under a millisecond. Anything slower runs in a short-lived child and writes a state file.

The full rationale, costs and measurements: [docs/01-architecture.md](docs/01-architecture.md).

## The pills

### SYSTEM — centre

The pill text is `CPU  RAM used/total  temp  [GPU used/total temp]  battery%`, content-sized
and recentred as segments appear and disappear. Left of the text:

| dot | meaning |
|---|---|
| grey | no lease |
| amber + countdown | a **root lease** is live (`/run/mrog/lease.json`, from the companion `mrog-lease` layer) |
| **red** + countdown | an **agent holds your keyboard/mouse** (`/run/mrog/input-lease.json`). Click it to halt. |
| red, `INPUT HALTED` | the panic file exists; all agent input is stopped |

Next to it a **model-state dot** (green `LEGAL` / amber `NORMAL` / red `SPLIT`) reads a JSON
file written by an external model-swap tool and shows which weight family a fleet is running,
with the direction of a swap while one is in progress. Clicking it launches the swap UI via
`pkexec`. If nothing writes the file the dot is idle — a missing file can never take the
pill down.

Right of the text: the **READ ▶** button (SpeedReader integration — left reads the current
selection aloud and becomes pause/resume while reading, right opens the follow-along
window, middle opens settings; the button simply is not drawn if `reader/notch_button.py`
cannot import),
the **camera** (instant full-screen PNG; `flameshot full -c -p` with an `ffmpeg x11grab`
fallback so it works with nothing installed; flashes green 1.4 s) and **REC** (toggle;
`h264_nvenc` on mains, `h264_vaapi` on battery, 60 fps, system audio from the default sink's
monitor via PulseAudio, SIGINT to finalise; the pill shows `REC m:ss` while live).

**Capture first, ask second.** After a shot or a recording, a dialog offers *Delete · Open
folder · Copy · Save as… · Keep* with a thumbnail. The file is on disk **before** the dialog
opens, so cancelling can never lose it. `MROG_NOTCH_ASK=0` makes capture silent.

The drop-down lists CPU, memory, package temperature, the dGPU (on demand — see below, or
`asleep`), battery, network, uptime, the lease and the model state.

**The GPU is read carefully, on purpose.** On a PRIME laptop the discrete card is suspended
~98 % of the time and waking it costs ~13 W — about five hours of battery for two numbers.
So `MROG_NOTCH_GPU=auto` (default) reads NVML only while something *else* already has the
card awake; opening the drop-down asks for a live reading on demand and releases it when
closed. The reading happens in a child process because NVML's ~20 MB is never returned to
the process that loaded it. [docs/04-capture.md](docs/04-capture.md) has the measurements
and the three latches this design had to escape.

**STOP capsule.** While an input lease is live, a red `STOP m:ss` capsule appears at the
top-left of the work area, above fullscreen windows (it is override-redirect, so the WM cannot
stack it under anything). Click = halt. The better kill switch is already built in: **moving
the mouse yourself** trips the human-motion abort in the lease layer.

### FLEET — right

`FLEET n/N` — reachability of your other machines. A child process TCP-connects to port 22
on each host every 30 s (ICMP is filtered on many networks; sshd is not; *refused* still
proves the host is up), reading addresses from `~/.ssh/config`. The drop-down shows per-host
latency. `MROG_NOTCH_FLEET=0` removes it.

### NOTE — 74 %

A real `GtkSourceView` scratchpad (171 languages) that drops into the top-right corner in
three sizes (S 460×320 · M 960×600 · L 1382×1008) plus fullscreen. Autosaves 1.5 s after
you stop typing and on close; reopens on the same file, cursor and size. Ctrl+F find,
Ctrl+S, Ctrl+N, Esc. *Recent* from GtkRecentManager. **Open in Kate** saves first, then
hands the file to a real editor — this is the quick-capture half, deliberately not a
Notepad++. [docs/07-scratchpad.md](docs/07-scratchpad.md)

### LAYOUTS — 26 %, hidden until the pointer touches the top edge

Three window layouts as fractions of the monitor's work area (`split`, `main`, `quad`),
applied with frame-correct `wmctrl` placement. The `workspace` CLI does the same from a
terminal (`list | windows | geom | apply | launch | place`, `--dry-run`, `--monitor`).

**Drag-to-snap.** Start dragging any window and two **one-inch** slivers (from the monitor's
real DPI) appear under the LAYOUTS pill: right = this screen, left = the second monitor,
present only while one is plugged in. Enter a sliver and a chooser opens beneath it showing
the layouts as cards divided into zones; release on a zone and the window lands there, on
that monitor. The chooser lingers 700 ms and fades over 220 ms after you leave, so it never
reads as a glitch.

This *has* to be polled: while the WM moves a window it holds a pointer grab and our windows
receive no events at all, so both overlays are input-transparent and everything runs on
`query_pointer()` at 200 ms idle / 25 ms while dragging — measured identical to having the
feature off. [docs/05-workspaces.md](docs/05-workspaces.md)

### ASK — send what is on screen to an agent, and keep talking

One pill, any number of agents, all in a registry file (`askbar/agents.yml`): colour, model,
whether it can see an image, where its drop lands, how a session opens, what constrains it.
**Adding an agent is a row, not code.**

- **Click the dot** — next agent (colour changes, model name flashes).
- **Click the pill / right-click** — open the pad:

```
  ask… (Enter sends, Esc closes)                       ↷ next agent
  grab:  ▣ window   ⬚ region   ▢ screen   ≣ page   ○ none
  ask:   skip?   angle?   draft   research?   feedback?
```

The **grab row arms** (sticky, fires nothing). The **ask row fires**: captures in whatever is
armed, then sends. The split exists because the first version welded them — clicking
*region* grabbed *and* sent, with no moment to change your mind. Enter in the text box sends
your bare question. Intents (`skip?` … `feedback?`) are prompts in the registry; reword or
add one with no code change. The rofi picker `ask-pick` reads the same rows.

**What a send does** (`askbar/ask`, headless, no GUI): capture → OCR (always, so a
text-only agent still gets the content) → **secret scan of the OCR text** (a screenshot
defeats a filename filter, because the secret is pixels; a fixture `sk-proj-…` was refused
even with two characters misread) → drop the file where *that* agent reads (local copy or
scp, sha-verified) → reference on the clipboard → **open a terminal with the agent already
reading it**. The command carries a *reference* to the dropped file, never the question:
a multi-line string through `bash → ssh → zsh` is a fresh quoting bug every time.

**`≣ page` is the document, a screenshot is a viewport.** It reads the active window's
*whole* text through the accessibility layer (AT-SPI, `win-text`) — everything below the
fold, front tab only, 12,705 clean characters where a full-screen OCR got 5,860 of chrome.
It is also the only capture mode that takes no X grab, so it cannot freeze anything.

**Follow-ups.** The window an ask opens is `ask-shell`. After the first answer:

```
──────────────────────────────────────────────────────────
Hermes · follow up?  (Enter = close · /session = open the full REPL on this thread · id 20260916_152359_b0463e)
> _
```

Enter closes (the old behaviour, unchanged). Typing sends the next turn of the **same**
conversation — the session id is pinned once, right after the first answer, and the text
goes over **stdin**, never argv. `/session` hands the window to the agent's full REPL on that
thread. Agents whose one-shot already *is* a REPL (Claude Code) or whose CLI stays open after
answering (`--stay`) need nothing: the registry marks them `followup: native`.

**Grab safety.** `flameshot gui` takes a pointer *and* keyboard grab; a hung one survives a
compositor restart and froze this desktop once. So `ask` refuses to start a capture while one
is running, every interactive capture runs under `timeout` (45 s default), and
`bin/mrog-unfreeze` breaks grabs before touching anything else.

**Self-test.** `ask-selftest` probes every row — not `--version` (proves a name resolves)
but *does the program start with its credential*, plus a canary round trip whose answer must
be **computed, not echoed** (`317 + 486` → `803`; an echoing CLI passed a `Reply with
exactly: PROBE` probe while the API was refusing every request). Metered rows are skipped
unless `--paid`. [docs/13-ask-bar.md](docs/13-ask-bar.md) is the full story.

## Companion tools

| tool | what |
|---|---|
| `bin/mrog-notch-guard` | supervisor: runs the notch under `py-spy record`, kills and restarts a confirmed CPU runaway within ~15 s **and captures the stack that names the loop**. Paired with a `CPUQuota=50%` / `MemoryMax=500M` drop-in as a second, kernel-enforced fence. |
| `bin/mrog-sandbox` | a nested X server (Xephyr on `:9`) with its own WM and the panel inside it. A grab taken there is scoped to that server; `:0` never sees it. **Never test a pill on the desktop you are using.** |
| `bin/mrog-notch-trial N` | deadman timer: the panel goes live on the real display and **reverts by itself** after N seconds unless you run `keep`. Doing nothing is the safe path, because a frozen desktop cannot click a confirm dialog. |
| `notch/padfit.py` | measures a pad's real size in a `Gtk.OffscreenWindow` against its input shape, without launching anything. |
| `bin/mrog-wm-check` | is the window manager the one you think it is (a fallback WM owning the root is why `cinnamon --replace` fails with `BadAccess`). |
| `bin/mrog-unfreeze` | recovery: break X grabs, then the runaway, then — only if needed — the compositor. |
| `panel/panel-app` | edit *both* Cinnamon launcher bars from the CLI (`bars / list / add / remove / move / copy / apply`). The GUI can only ever add to one of them, and writing the JSON is half the job: the list must be pushed into the live applet over Cinnamon's `Eval` D-Bus method. [docs/06-panels.md](docs/06-panels.md) |
| `panel/menu-fork` | a 9-line override of the stock Cinnamon menu adding *Add to bottom bar / Add to left bar*; `check.sh` tells you when upstream moved. |
| `bin/askpill-pos` | nudge the ASK pill left/right out of a neighbour's way. |
| `bin/mrog-freeze-capture`, `bin/mrog-cinnamon-guard`, `bin/mrog-notch-watch`, `bin/mrog-shell-guard` | freeze forensics and watchdogs: capture per-thread CPU, Cinnamon RSS and Xorg load when the desktop stalls; restart a runaway shell; watch the notch's CPU from outside it. |

## The reader

`reader/` is the **READ ▶** button *and the engine it drives* — `reader.py` (sources,
extraction, redaction, number handling, the speaker), `pacer.py` (the word-synced
follow-along window), `settings.py`, `voice-lab.py`. It is the private original of
[speedreader](https://github.com/Associated2u/speedreader), which is the same engine
packaged standalone with a tray icon; fixes are ported between the two by hand (both
directions have happened). It lives here because `notch_button.py` resolves `reader.py`
*beside itself* — a bundle without the engine would draw a button that points at nothing.
[docs/08-reader.md](docs/08-reader.md).

## Install

See [INSTALL.md](INSTALL.md). Short version: X11 + Cinnamon (or any WM honouring
`_NET_WM_STATE`), `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-gtksource-4`, `python3-xlib`,
`python3-yaml`, `xdotool`, `wmctrl`; optional `flameshot`, `xclip`, `tesseract`, `rofi`,
`py-spy`, `Xephyr`, `espeak-ng` + `speech-dispatcher` for the reader. Then `bash notch/install-notch.sh` — no root anywhere.

## Configure

Every knob is an environment variable on the user unit or a row in `askbar/agents.yml`.
[CONFIGURE.md](CONFIGURE.md) lists all of them, plus the file contracts the pill reads (leases,
model state, fleet helper output) so other tools can feed it.

## Docs

`docs/` is the engineering record: architecture, the pill framework and how to add a pill,
capture, workspaces, panels, the scratchpad, the ask bar, and **[90-traps.md](docs/90-traps.md)
— every trap found by running it**, which is the highest-value page here. Everything in
those pages was measured, and every guard was driven to fail on its own failure class before
being called working.

## Status

This is the public export of the maintainer's working tree: machine names, addresses and
accounts in the docs are placeholders (`hub`, `gpubox`, `mini`, `hubuser`…), the incidents
they describe are real. Issues and PRs are welcome here; fixes are ported into the
private tree and re-exported.

Companion repos: [mrog-lease](https://github.com/Associated2u/mrog-lease) (the lease layer
the pill displays, with its security review) and
[agent-control-shell](https://github.com/Associated2u/agent-control-shell) (the root lease
standalone, with a tray icon).

A note on the name: `mrog` is the project prefix (units, binaries, `MROG_*` variables,
`/run/mrog`). It is not expanded anywhere and does not need to be.

## License

MIT — see [LICENSE](LICENSE).
