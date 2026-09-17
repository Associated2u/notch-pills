# Traps

Everything here was found by **running** something, never by reading it. Most
are the same shape: *the thing reported success and had done nothing.*

## Things that succeed and do nothing

| | |
|---|---|
| `ReloadXlet` | returns a normal dbus reply, does **not** re-read `launcherList` |
| `restartCinnamon()` | reloads the shell **in-process**; the Cinnamon PID never changes, applet code is never re-read. Only `cinnamon --replace` does |
| `systemctl --user enable --now` | a **no-op on an already-running unit** — re-running an installer kept the OLD binary alive, same PID, no error |
| `git clone` into a bare repo with an unborn HEAD | **exit 0, zero files.** Pushed `main`, HEAD pointed at `master` |
| `2>/dev/null` on a broken parser | turned a `SyntaxError` into `(no events yet)`. The log was fine; only the viewer was broken |

**The rule: count the result. Exit 0 is not evidence.**

## systemd

🔴 **`graphical-session.target` is never activated by Cinnamon on Mint.** A unit
`WantedBy` it reads `enabled`, is correctly symlinked, and **never starts at
login**. Use `default.target`. `is-enabled` proves a unit is wired, not that its
target is ever reached.

🔴 **`StartLimitIntervalSec` / `StartLimitBurst` belong in `[Unit]`, not
`[Service]`** — under `[Service]` they are silently ignored. It mattered: at boot
X may not be up when `default.target` is reached, and the default burst (5 starts
/ 10 s) throttles the retries out, so the service never appears.

## X11 and window management

🔴 **`xdotool getwindowgeometry` reports a different origin for reparented
windows** — `1967,72 941x1133` for a window `xwininfo` proved was `1957,0
941x1165`. Verify with `xwininfo` + `_NET_FRAME_EXTENTS`; place with `wmctrl -e`.

🔴 **A maximized window silently ignores a move.** Drop the states first.

🔴 **While the WM moves a window it holds a pointer grab** — your windows get no
motion, enter or button events at all. Poll and hit-test yourself.

⚠️ **An unmapped `POPUP` does not keep geometry set at construction** — overlays
sat on the wrong monitor until re-placed at use time.

⚠️ **A `DOCK` window takes no keyboard focus** unless `set_accept_focus(True)` is
called **before realise**. A `POPUP` is override-redirect, so it sits above
fullscreen windows where a `DOCK` does not.

## GTK and cairo

🔴 **`show_text()` leaves a current point, and a following `arc()` draws a LINE
to it** — a stripe ran from the pill text through the camera to the REC dot.
`new_path()` before geometry, `new_sub_path()` before each arc.

🔴 **A `Gtk.Box` pushes its parent out rather than clipping.** A toolbar wider
than its pane forces the whole window wider. `ScrolledWindow` with
`propagate_natural_width=False`.

⚠️ **A GtkSourceView style scheme colours syntax, not the widget background.**
Set it with CSS. `Adwaita-dark` does not exist here.

## Holding a resource you are also measuring

🔴 **Three latches, one shape.** While *we* hold the GPU, its power state reads
`active` **because of us** — so "release when it goes idle" can never fire. The
release signal must be the *client count*, not the state. Re-suspend (~30 s) is
slower than any poll, so releasing then polling re-latches — hence a cooldown.
And a forced helper never self-exits, so the caller must stop it explicitly.

**Anything that both observes and holds a resource has to be told when to let go.
It can never infer it.**

⚠️ **Observer effect.** Any tool that reads dGPU state *changes* it. An early
conclusion that the notch was pinning the card awake was wrong — the diagnostics
were doing it. Check with `runtime_status` and `/proc/<pid>/fd`, never NVML.

⚠️ **`ctypes` never `dlclose()`s.** Once NVML is loaded its ~20 MB stays for the
life of the process, even after `nvmlShutdown()`. Releasing recovers the watts,
never the megabytes — hence a child process.

## Shell

🔴 **`pgrep -f` / `pkill -f` / `ps | awk` match this session's own shell** when
the pattern text appears in its command line. Killed three tool calls (exit 144).
Filter on `$$`/`$PPID`, or use a pidfile.

🔴 **A heredoc IS stdin.** `tail x | python3 - <<'EOF'` discards the pipe — the
program reads the heredoc, not the data. Pass the path as an argument.

🔴 **Escaped double quotes inside an f-string inside a single-quoted shell
string** are a `SyntaxError`. Use a heredoc and single-quoted keys.

🔴 **A window-diff broken by leading whitespace moved the wrong window.**
`awk '{print "  "$1}'` wrote two spaces into the file, so `grep -vxF -f` matched
nothing and returned an *existing* window as "new" — the desktop got moved.
**When a diff returns a surprising answer, check the comparison, not the data.**

⚠️ **Quote every pattern in a sourced config.** An unquoted glob is expanded
against the filesystem at source time, silently emptying a deny list.

## Design lessons that cost the most

🔴 **A safety feature that cries wolf gets switched off.** The motion abort
started at **3 px per axis** — a hand resting on a mouse exceeds that. Unusable
is worse than absent. Now a 1.5 inch *radius*; per-axis is a box, and a diagonal
had to travel further to trip.

🔴 **Re-measure a security premise before repeating it.** A stale audit note
("passwordless apt exists") was carried for a whole session and used to argue
*against* hardening something else. The file did not exist.

🔴 **Anything anchored to the screen must derive its position from the screen,
not its container.** Resizing a window to fit its drop-down dragged the anchored
pill along with it.

🔴 **A subclass inherits the parent's costs, not just its looks.** A pill that
shows no GPU inherited a GPU probe and ran a duplicate helper holding the card
awake. Check the child process list after adding one.

## The reader — 2026-09-04, `SID:LINUX-E3X`

Every one of these was found by running the thing, not by reading it.

🔴 **A fallback that the real failure mode cannot reach is not a fallback.**
Window capture tried ImageMagick's `import` and fell back to ffmpeg on a
non-zero exit code. `import` is not installed, so it raised `FileNotFoundError`
and crashed straight past the fallback. To the user the button "did nothing".

🔴 **Do not send a subprocess's stderr to `/dev/null`.** That is what made the
above invisible — a traceback and a no-op looked identical. It now writes to
`~/.local/state/mrog-reader/last.log`, and every run logs its **effective**
settings, not its intended ones.

🔴 **Two sources of truth, and the wrong one wins silently.** `notch_button`
kept its own `style`/`rate` fallbacks and passed them as explicit CLI flags,
which beat the config file. Every setting the voice lab wrote was overridden and
the only symptom was "it still skims". Config file or nothing.

🔴 **A D-Bus property filter that is right in principle can return a plausible
zero.** The A2DP delay probe filtered transports on `State == "active"`, but the
transport is `idle` until audio flows — and the probe runs *before* the first
word. It returned 0 with no error, silently disabling sync compensation.

🔴 **GTK3 CSS has no `line-height`, and it rejects the ENTIRE stylesheet** over
one unknown property, not just that line. The pacer refused to build. Line
spacing belongs on the TextView (`pixels_above/below_lines`).

🔴 **A redactor that only catches the canonical form is the dangerous kind.**
The Telegram pattern demanded *exactly* 35 characters after the colon; a
near-miss walked through while the tool looked like it was working.

🔴 **…and a redactor that bleeps your own project names gets switched off.** The
entropy backstop then caught `BirdsFlyPoopSimulator-GDD-v1-1`. It now needs a
20+ char *unbroken* alphanumeric run containing a digit. Both directions must be
tested: 4/4 secrets caught, 7/7 legitimate strings surviving.

🔴 **Set-membership operators are not the test you meant.** `set(c) > set("-: ")`
is a strict-superset test, not "is this only dashes and colons". It silently
dropped every real table row while looking correct.

🔴 **Compression and pacing are mutually exclusive.** Skimmed audio plus full
on-screen text means the highlight jumps over paragraphs the eye is still
reading, and there is nothing left to follow. Only verbatim paces.

🔴 **Listening speed does not scale like reading speed.** Phoneme discrimination
needs ~60–80 ms, capping intelligible speech near 500–700 wpm. Advising "push
the rate up" assumed otherwise and was wrong. The ear is not the vehicle for
8–10x; the eye is.

⚠️ **Bluetooth: pairing succeeds, then the first connect fails**
(`br-connection-page-timeout`) — the glasses drop to low power the moment
bonding completes. And the first connection comes up **HFP-only, 16 kHz mono
with the mic held open**; a clean disconnect + reconnect is what produces
`a2dp-sink` at 48 kHz stereo with the mic released. Cycle, never trust the
first link.

## Cinnamon leaks ~70 MB/hour and wedges the desktop around 20 hours

**FLEET-CB2 2026-09-05. Two freezes in one afternoon, both at ~20h uptime.**

Symptom: the screen stops repainting. Everything else looks fine — load 1.7 on
16 cores, 14 GiB free, swap untouched, no kernel errors, and **X still answers
queries**. Every "is the system busy" check comes back healthy, which is why
this is so hard to catch after the fact.

Measured with `mrog-freeze-capture` running DURING the freeze:

    cinnamon  pid 2307  age 20.8h  RSS 1768 MB  cpu 90.9%  D-Bus main loop BLOCKED
    cinnamon  fresh               RSS  238 MB  idle

The two decisive lines are **"NOT REPAINTING"** and **"CINNAMON D-BUS DID NOT
ANSWER"**. X alive + not repainting + shell D-Bus silent = this.

**What misled me, twice.** The notch showed 100% CPU in the same capture and
looked like the culprit. It was a **victim**: a GTK overlay blocked on a wedged
compositor spins. Run it against a healthy Cinnamon and it sits at 0.0%.
Killing the notch did **not** thaw the desktop; killing Cinnamon did. Also
beware `ps` `%CPU`, which is cputime/elapsed **since start** — a freshly
restarted process reads high on startup cost alone and looks like a spinner.
Use `top -bn1` for the instantaneous number.

**`cinnamon --replace` does not always replace.** Measured the same day: the old
process stayed alive, two shells ran at once, neither owned the window list
(`wmctrl -l` reported **0 windows**), and the desktop stayed frozen. The old one
then ignored SIGTERM and needed `-9`. Recovery is: replace, confirm the old pid
is gone, then verify D-Bus answers **and** the window list is non-empty.

**Prevention:** `~/mrog/mrog-cinnamon-guard` — warns at 900 MB (~13h), danger at
1400 MB (~20h; it wedged at 1768). `--restart` does the replace-and-verify
correctly. `--watch` notifies once per crossing rather than nagging.

## 🔴 NEVER edit the notch while the pills are running (2026-09-06)

Chris: "it only freezes when I have an agent make changes to it so it should
turn it off before committing changes than reloading it."

Two desktop freezes in one day, both needing an SSH rescue from another machine:

  1. flameshot stuck holding an X pointer+keyboard grab. A GRAB SURVIVES A
     COMPOSITOR RESTART, so `cinnamon --replace` does nothing for it -- and
     reaching for that first destroyed 22 hours of session state while the real
     cause was already fixed by another session.
  2. Cinnamon ran away to 1.5 GB / 83% CPU in 146 seconds. No grab holder at
     all. X was alive, the pointer answered, windows were alive -- nothing
     painted. Ungrab is irrelevant to this one.

They need OPPOSITE fixes, and telling them apart is the whole job:

    pointer does NOT respond  ->  stuck grab. Kill the grabber.
    pointer DOES respond, UI dead  ->  runaway compositor. Kill the runaway.

**THE RULE.** Any edit to the notch (`~/mrog/notch/notch.py`,
`~/.local/bin/mrog-notch`) goes through:

    mrog-notch-edit -- <command>      # pills down, edit, syntax-gate, pills up
    mrog-notch-edit --shell           # interactive; pills return on exit

It always restores the pills -- on success, on failure, on Ctrl-C -- EXCEPT when
the installed notch fails a syntax check, where it deliberately leaves them down
rather than load a half-written file onto the display.

**Recovery, from a phone.** Phone reaches only Hub, so Hub is the jump host:

    Hub.sh  then:   ./unfreeze            safe: breaks grabs, kills runaways
                          ./unfreeze --status   look only
                          ./unfreeze --restart  last resort, LOSES session state

Hub `~/unfreeze` -> laptop `~/bin/mrog-unfreeze`, trying laptop / 192.0.2.64 /
198.51.100.5 in order. Logs to `~/mrog/audit/freezes/` on the laptop.

**Do NOT pick which cinnamon to kill by AGE.** That was the original heuristic
and it is wrong: in freeze 1 the oldest held all the session state. Pick the one
MISBEHAVING -- over 40% CPU and over 700 MB.

## Cinnamon runaway correlates with the pills being UP (2026-09-06)

THREE runaways in one afternoon, each needing a kill: 567 MB, 1.5 GB, 2.4 GB.
Each grew to gigabytes in roughly 10-15 minutes. Every one happened while the
notch pills were running.

Against that: with the pills OFF, the notch watcher logged 3,624 samples over 12
hours and Cinnamon's RSS spread was **8 MB** (flat 364-372 MB).

Chris spotted it first: "it only freezes when I have an agent make changes to
it." Pills are OFF pending a proper investigation. One click on the favourites
bar button turns them back on.

NOT PROVEN -- the correlation is strong and the mechanism is unknown. Do not
close this as solved.

### 🔴 The detector bug that made the tool look broken

`mrog-unfreeze` first tested `cpu >= 40 AND rss >= 700MB`, reading CPU from
`ps pcpu`. **That is the LIFETIME AVERAGE** -- the exact trap already in this
file. A Cinnamon at 94% in `top` read 27.5% in `ps` (averaged over its 824 s
life), the AND-condition failed, and the script printed "compositor CPU/RSS look
normal" while the desktop was frozen under a 1.9 GB compositor. Run from Chris's
phone it did nothing and looked broken; it was working perfectly and asking the
wrong question.

FIXED: **RSS alone decides.** RSS needs no sampling window and cannot be averaged
into innocence. Healthy Cinnamon here is 136-250 MB; the runaways were 1.5-2.4 GB.
CPU is still printed as context, never as the test.

## Process detection

🔴 **`pgrep -x` CANNOT SEE A NAME LONGER THAN 15 CHARACTERS.** Linux truncates
the `comm` field, and pgrep refuses outright: *"pattern that searches for process
name longer than 15 characters will result in zero matches."* `gnome-screenshot`
is **16**. A guard written to prevent an X-grab freeze was therefore blind to one
of the two tools that can cause one — and said nothing, because the warning goes
to stderr and was being discarded. Match `/proc/PID/exe` instead: no length limit,
and it cannot be fooled by a command line that merely *mentions* the name.

🔴 **`pgrep -f` matches your own command line.** A guard using it fired on the
shell running the test, and would fire on any line merely mentioning the tool.
**A guard that false-positives is a guard that gets switched off.**

## X11 and window management (additions)

🔴 **`wmctrl -lG` reports the DECORATED FRAME, `xwininfo` the client area.**
Measured on this display: `1274,81` vs `1264,41`, `10,72` vs `0,32`, and `0,0` vs
`0,0` on an undecorated window — **not a constant offset**. Targeting "which window
is under the pointer" off frame coordinates silently picks the wrong window near
edges. Worse, chasing a position that "would not stick" cost three wrong theories
— HiDPI scaling (scale was 1), the WM overriding placement, then wmctrl "doubling"
— before a second instrument showed the window had been exactly where it was put
the whole time.

🔴 **`wmctrl -l` lists nothing on this laptop's WM, and never lists DOCK windows.**
A pill panel is invisible to it. `xwininfo -root -tree` is the instrument that
works. "0 windows" from wmctrl twice read as *"I have broken the panel"* when
nothing was wrong.

🔴 **An X grab survives a compositor restart.** A wedged `flameshot` held pointer
and keyboard; `cinnamon --replace` did nothing and looked like it had failed.
Break grabs FIRST — `~/bin/mrog-unfreeze` — and treat restarting the compositor as
the last resort. Reaching for the restart first also killed a 22-hour Cinnamon and
destroyed a day of panel and workspace state, while the real cause was one `pgrep`
away.

## Pills (additions)

🔴 **Overriding `on_pill_click` and dropping `apply_input_shape()` freezes the
desktop.** The pill window is far larger than the capsule; the input shape is the
only thing keeping the transparent remainder click-through. A stale shape makes
that window swallow clicks across the screen. **It does not crash, raises nothing
and logs nothing** — the notch log shows clean starts throughout. When overriding
a framework method, keep the base's side effects.

🔴 **An embedded pad must be UNIONED into the input shape** or it is invisible to
the pointer: you see buttons and clicking does nothing.

🔴 **The base connects only `button-press`.** An `on_release` override never fires
until you `add_events(BUTTON_RELEASE_MASK)` and connect it yourself — so a
click-versus-drag test silently does nothing and looks identical to the bug.

🔴 **`MROG_NOTCH_ASK` was already taken** by `ASK_AFTER_CAPTURE` (notch.py:67).
Reusing it for a new pill would have silenced the capture dialog. Grep the env
namespace before claiming a variable.

🔴 **`install-notch.sh` installs a COPY to `~/.local/bin/mrog-notch`.** Editing
`~/mrog/notch/notch.py` changes nothing that runs, and resolving a sibling file
relative to `__file__` looks in `~/.local/bin`, where it is not. The pill silently
never loaded while the source looked correct. **Check the path the consumer opens.**

🔴 **…and it happened AGAIN, one file over.** `~/.local/bin/mrog-askpill.py` was a
hand-placed copy of `askpill.py` with **no installer behind it**, and `notch.py`
searches for it *before* `~/mrog/notch/askpill.py`. Hours of edits to the source
changed nothing that ran, silently, exactly as the entry above predicted. Both are
symlinks now. **The lesson is not "remember to sync" — it is "one file."** Derive the
path from the loading code, never from the doc: `grep -n askpill notch.py` shows all
three candidates and their order.

🔴 **Two copies of a tools directory drift, and the tracked one loses.**
`~/ceo-tools/askbar/` (live, untracked) vs `~/hermes/tools/askbar/` (tracked, stale).
The one under version control was the *wrong* one. `ceo-tools` is a symlink now.

🔴 **A hardcoded pad rect stops matching what GTK draws.** `pad_rect_now()` returned a
constant `360×150`; adding one row and one button made the pad want `347×188`, so
**38 vertical pixels were drawn outside the input shape** — buttons visible, dead to
the pointer. Same family as the frozen desktop, quieter: no crash, no log, a control
just stops working. Measure the widget, floor at the constant, clamp to the window,
and **re-apply the shape on `size-allocate`** so it cannot lag the pixels.

🔴 **Verify a pill WITHOUT launching the panel.** Restarting the panel to check a shape
is how the desktop got frozen. Build the widget in a `Gtk.OffscreenWindow` — never
mapped, no grab — and measure it (`~/mrog/notch/padfit.py`). Check it **fails** against
the old value too; a check only ever seen passing proves nothing.

🔴 **`systemctl --user set-environment` is invisible state that lives in NO FILE.**
The ASK pill was missing from the real desktop for an entire session while the code was
correct and a nested-X sandbox showed it working perfectly. Cause:
`MROG_NOTCH_ASKPILL=0`, set once with `systemctl --user set-environment` when the pill was
deliberately disabled to stop a freeze — and then **inherited silently by every service
restart for the rest of the login.**

It is in no unit, no drop-in, no `.profile`, no `environment.d`. Grepping every config on
the machine returns nothing. The only place it exists is the running user manager:

```bash
systemctl --user show-environment | grep MROG          # the only way to see it
systemctl --user unset-environment MROG_NOTCH_ASKPILL  # the fix
```

**How it was found, and the general method:** the same binary was run two ways — under the
unit (3 pill windows) and by hand in the sandbox (4). Same code, same paths, same
resolution, one window different. That gap *is* the environment, and diffing what each
launch inherited named the variable in one step. When something works one way and not
another, compare the two environments before reading any more code.

`mrog-notch-trial` now prints a loud warning naming every `MROG_NOTCH_*=0` in the manager
before it starts anything — verified firing with the flag set and silent without it.

> Fourth instance of this family today: a copy that beats the file you edit, a tracked dir
> that is the stale one, a hardcoded rect that stops matching what is drawn, and now an env
> var that exists only in RAM. **Check what the consumer actually receives, not what the
> source says it should.**

🔴 **`xclip` holds the caller hostage, and it is doing so ON PURPOSE.** An X selection is
served by the process that owns it, so `xclip -selection clipboard` stays alive until
another app takes the clipboard. It inherits the calling script's **stdout**, so any
caller reading that output with `$(...)` blocks until xclip dies — and `ask-pick`, which
the ASK pill uses, does exactly that.

**MEASURED: `ask --page` finished its work in under a second and then sat for 162
SECONDS.** Fix is `setsid` plus closed fds: **162,076 ms → 724 ms**. The clipboard still
works; the caller is no longer waiting on it.

```bash
printf '%s' "$ref" | setsid xclip -selection clipboard >/dev/null 2>&1 &
```

> Applies to anything that must outlive the script that starts it. If a helper is
> *supposed* to keep running, detach its fds or every caller inherits the wait.

🔴 **I blamed the wrong layer for three rounds, and the measurements were right there.**
Chasing that 162 s I wrote a timeout patch for AT-SPI, built a speed probe, and timed
every accessible app on the desktop. **The accessibility walk takes 178 ms.** The whole
36-app loop takes 0.1 s. The work was finished the entire time; only the pipe was open.

The tell was in the first result and I read past it: the drop file **had already landed
on Hub**, complete and correct, while the command still appeared to be running. A
job that has produced its output is not still working — **look at what finished, not at
what has not returned.**

🔴 **A reference can name a file that was never created.** Page mode produces no `.png`,
but two places chose the clipboard reference on `A_VISION` alone, so a vision-capable
agent was handed a path to a nonexistent image. Both now call one `ref_base()`. When you
add a mode that changes what a pipeline *produces*, grep every branch that assumes the
old shape — a single predicate (`has_image`) beats four hand-written tests of `$MODE`.

## Cinnamon (2026-09-06, twice in one day)

🔴 **A frozen desktop is not always a grab.** `mrog-unfreeze` reported *no grab holders*
and it was telling the truth — Cinnamon had **leaked to 4.3 GB** (793 MB → 3.0 GB → 4.3 GB
in about 90 minutes) and wedged. Check the compositor's RSS before reaching for grab tools:

```bash
ps -eo pid,rss,comm | grep ' cinnamon$'      # >700MB and climbing = restart it deliberately
```

🔴 **`cinnamon-launcher` respawns `metacity` as a fallback the moment Cinnamon dies, and
metacity grabs the root window.** After that Cinnamon **cannot take it back** — it dies
with `BadAccess`, `request_code 2` (X_ChangeWindowAttributes), the signature of *another
window manager already owns this*. Every restart lands in a two-WM standoff, which paints
as large black unrepainted regions with windows still moving.

**The order is the whole fix — metacity FIRST, then Cinnamon:**

```bash
pkill -x metacity; sleep 2; setsid nohup cinnamon --replace >/tmp/cin.log 2>&1 </dev/null &
```

`setsid` matters: a Cinnamon started as a child of an SSH command dies with the connection,
which is how the first recovery attempt came back wrong.

🔴 **Killing the OLD Cinnamon after `--replace` can take the new one with it.** Observed:
`kill -KILL <old>` reclaimed 3.6 GB and left **zero** Cinnamons, with metacity back in
charge. Replace first, verify the new one owns the desktop, and leave the old process alone
unless memory actually demands it.

> 🎯 **And the meta-lesson, learned expensively: stop killing things.** Reaching for one
> more kill produced two Cinnamons, then none, then metacity again. A working-but-untidy
> desktop beats another round of the same. Take a screenshot and *look* — the screen showed
> a working taskbar and a crashed-applet dialog that no `ps` output would have revealed.

---

## Two log families, and the false bug report that came from mixing them
*2026-09-07*

Dreamzs writes telemetry to two places that **do not overlap**:

| family | written by | lands in | carries |
|---|---|---|---|
| tool telemetry | `Tools._log()` in `dreamzs_agent.py` | `~/vault-logs/redteam/session-<id>.log` | `SERP_FALLBACK`, `FALLBACK_FAILED`, `WEBFETCH BLOCKED`, `WEBSEARCH` |
| gate decisions | `logger.*` in `dreamzs_bridge.py` | `~/vault-logs/redteam/bridge-daemon.log` | `GATE2_TRIGGERED`, `GATE2_DISCLOSURE`, `MAX_ROUNDS_EXIT` |

**What it cost.** A session grepped `bridge-daemon.err` for `SERP_FALLBACK`,
`WEBFETCH BLOCKED` and `[FALLBACK FAILED]`, got **0 for all three**, and reported
to Chris that the SERP fallback was "verified firing by direct call but never
fires in a real turn" — a contradiction serious enough to be handed to an agent
to chase. The real counts, in the session logs, were **167 SERP_FALLBACK and 597
BLOCKED**. Nothing was broken. Working code was reported as broken because the
grep was pointed at the wrong file, and the zero *looked* like evidence.

This is the same shape as the block detector's unit test earlier the same week:
a check that appeared to prove something about the system while never touching
the part of the system in question. The tell is identical — **a clean zero that
nobody drove to non-zero first.**

**The guard.** `gpubox:~/bin/dzlog <pattern> [-v]` searches both families, labels
which one each hit came from, and refuses to let a single-family zero read as
absence:

```
  tool telemetry  (551 session logs)  167
  gate decisions  (bridge-daemon.*)  0
  -> present in one family only. This is NORMAL: the two do not overlap.
```

and only when both are zero does it say *"absent from BOTH families. Only now is
'never fired' supportable."* Driven through both outcomes on install, per the
verify-by-effect rule — a green it has never been seen to report red is worth
nothing.

**Third gotcha:** `_log()` returns early under `_private_mode`. A private session
legitimately writes nothing, so zero there means *not recorded*, never *did not
happen*.

---

## `ast.parse` is not a test, and I proved it the same day
*2026-09-07*

I wrote `cellrun.py` as a harness so three test agents would not have to
hand-quote JSON through ssh. I validated it with:

```python
python3 -c 'import ast; ast.parse(open("cellrun.py").read()); print("syntax ok")'
```

…called that verified, and handed the command to three agents. It had never run.
Line 23 iterates `G.CELLS`; `general_battery` names that list `QUESTIONS`. It
died with `AttributeError` before ever contacting the bridge.

**This is the third instance of one pattern in one week:**

| what was "verified" | what was actually exercised |
|---|---|
| block detector, 6/6 unit tests green | the helper — never the caller, which lived on a branch walls don't take |
| SERP_FALLBACK "verified firing" | a direct Python call — never a real turn, and then the wrong log file |
| `cellrun.py` "syntax ok" | the parser — never the program |

Each time the check was real, passed honestly, and proved nothing about the
claim being made. **The tell is always the same: the check never touched the
thing in question, and nobody drove it to fail first.**

The rule already in `CLAUDE.md` — *"a check that has never been seen to fail
proves nothing"* — is not about flaky tests. It is about this. The cheap form of
compliance is one line: run the thing once with input you expect to be rejected.
`python3 cellrun.py dreamzs-ops NO_SUCH_CELL 1` would have caught it in two
seconds, because a working harness must print the cell list and a broken one
cannot get that far.

**Mitigation that survives the next rename:** `cellrun.py` now resolves the list
with `getattr(G, "QUESTIONS", None) or getattr(G, "CELLS", [])`, so a rename
degrades instead of exploding. But the mitigation is not the lesson. The lesson
is that a green from a check that cannot go red is worth exactly nothing, and
that writing this down twice did not stop me doing it a third time.

**Also worth keeping:** all three agents hit the broken command, all three worked
around it with an equivalent shim, and **none of them edited the live file** —
they proposed a one-line diff instead. Propose-before-apply held under pressure,
in parallel, without supervision.
