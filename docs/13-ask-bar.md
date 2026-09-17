# The Ask Bar — send what is on screen to any agent

Built 2026-09-06 (`HERMES-7TZ`). One pill, five agents: pick who gets it, capture
something or nothing, and a session opens with that agent already reading it.

**Code:** `~/mrog/askbar/` (layer 1) · `~/mrog/notch/askpill.py` (the pill) ·
`~/bin/ask-now`, `~/bin/ask-agent`, `~/bin/ask-text`, `~/bin/askpill-pos`.
Canonical copy lives in `hub:~/hermes/tools/askbar`.

## Three layers, so the visible part is the disposable one

```
agents.yml     the REGISTRY — colour, model, can it see an image, where its drop
               lands, how to open a session with it, what constrains it
     ↓
ask            capture → OCR → secret scan → drop → clipboard → open a session.
               No GUI. Runs headless on the laptop and on Hub.
     ↓
askpill.py     draws a pill and shells out. Nothing else.
```

**Adding a sixth agent is a row in `agents.yml`.** Rebuilding the bar for Waybar
or Wayland rewrites the drawing and none of the policy.

## Why a file path and not per-agent integrations

All five agents can read a file. Only four speak MCP, Dreamzs needs its own
shape, and every integration rots separately. A path is the lowest common
denominator, and per-agent **rules** become **where the file lands** — Hermes's
drop is the Hermes spine `inbox/`, which is agent-read-only and one-way by ACL.

## The registry

| field | what it decides |
|---|---|
| `color` | the dot. This is the whole selector — Chris learns the colour |
| `vision` | **measured, not assumed.** `false` means the OCR sidecar IS the payload |
| `drop` | `host:path`. One registry works from either machine |
| `ask_host` / `ask_cmd` | how a session actually opens. `{q}` becomes the prompt |

🔴 **`vision: false` is a measurement.** GpuBox's llama-server runs with no
`--mmproj`, and `dreamzs_agent.screenshot()` returns a **path and byte count**,
never pixels — it even guards with *"NO IMAGE WAS CAPTURED. You MUST NOT describe
the appearance of this page."* Dreamzs reads the web as **text**. Do not flip this
field to make a capture "work"; re-measure the backend.

## Say what you want, not how to grab it

The first pad welded capture to send: clicking `region` grabbed **and** fired. There
was no moment between selecting something and committing it, and Chris hit it on his
first real use — *"I type my question, I select the window and it automatically fires."*

Two verbs now, on two rows:

| row | what it does |
|---|---|
| **grab:** `window` `region` `screen` `none` | **arms.** Sticky state. Fires nothing |
| **ask:** the intents | **fires.** Captures in whatever is armed, then sends |

The armed mode always beats the intent's registry default, because the pad *shows*
which grab is armed — a button that silently grabs something other than what is
displayed is the same welded-together surprise this split removes.

Enter in the text box sends with no preset: just your question.

### The five intents

| | asks for |
|---|---|
| `skip?` | is this worth my time at all |
| `angle?` | what is our take, where do we come in |
| `draft` | write the comment |
| `research?` | what context am I missing |
| `feedback?` | judge the comment I already wrote |

`feedback?` is **diagnostic only** — its prompt ends *"Diagnose only. If I want it
rewritten I will ask for a draft."* Without that it answers every critique with a
rewrite, which is a different question than *did mine land*.

It also wants the **whole thread**, not just your reply. Judging a comment without the
post it answers is arguing with something invisible, so `ask-pick` says so **before**
the region grab, while you can still change what you select.

Intents live in `agents.yml`. Adding a sixth or rewording one touches **no code** —
not the pad, not the picker. Both read the same rows.

### Two entry points, one script

`ask-pick` bare opens the rofi picker; the pad calls the same script with the intent and
the armed mode already chosen. **The picker comes first and the grab comes second on
purpose:** the region-select *is* the commit, so Esc during it cancels everything and
nothing is sent.

A second near-identical `ask-run` for the pad was the obvious build and is the wrong
one — two scripts is how the pad's menu and the picker's menu drift apart.

## The command carries a reference, not the question

First attempt embedded the question inline. That meant quoting a multi-line string
through `bash → ssh → zsh`; it produced `$'what\ do\ you...'`, unrunnable, and a
fresh bug every time the text changed.

The question is **already in the dropped file**, beside the OCR and the provenance
header — so the agent gets *more* context by reading it than any argv string could
carry. One short single-line prompt: nothing to break.

```
ssh -t agentuser@192.0.2.127 \
  "/Users/agentuser/.local/bin/hermes -p void -z 'Read inbox/ask_….md and answer the question in it.'"
→ ASKBAR-WIRED
```

That is a real run, not an example.

## Secret scan — a screenshot defeats a filename filter

`ship.sh` refuses secrets by name and content. A screenshot defeats it because the
secret is **pixels**. So every capture is OCR'd and the **text** is scanned before
the image is allowed to land.

Proven: a fixture containing `sk-proj-…` was REFUSED **even though OCR misread two
characters**, because the prefix pattern still matched. Refusals stay in private
staging (`~/.askbar/staging`, mode 700) — never in an agent's drop.

## Grab safety — the part that froze a desktop

`flameshot gui` takes an X **pointer and keyboard grab**. If it hangs the grab is
never released, and **a grab survives a compositor restart** — so `cinnamon --replace`
does nothing and looks like it failed. This froze the laptop on 2026-09-06;
`~/bin/mrog-unfreeze` is the correct recovery and breaks grabs before touching the
compositor.

Two guards, both driven to fire:
1. **Refuse to start a capture while one is already running.** Stacking grabs turns
   recoverable into unrecoverable.
2. **`timeout` on every interactive capture** (`ASKBAR_CAPTURE_TIMEOUT`, default 45s).
   Killing the tool releases the grab.

## Using it

| | |
|---|---|
| click the dot | next agent (colour changes, model name flashes) |
| click the pill body / right-click | open the pad (grab row + ask row) |
| `Super+Space` | five `Ask:` verbs in the leader menu |
| `ask-pick` | picker, then grab, then send — the fast path |
| `ask --intents` | the live intent list; `--intent nope` fails loudly |
| `askpill-pos --left` / `--right` | nudge it out of the neighbours' way |
| `ask --dry-open` | print the command instead of spawning a terminal |

## Measured

| | |
|---|---|
| whole pipeline, no capture | **0.26 s** |
| OCR, full 1920×1080 | 2.65 s |
| scp to the Mini | 0.22 s |
| `gnome-screenshot` first invocation | the only slow stage |

⚠️ I once reported this as "over 100 seconds". That was **my own tool call timing
out**, not a measurement — three sequential runs plus a real capture over SSH
against a 120 s harness limit. Reading the instrument instead of the thing, again.

## Three traps that cost a session

**A hand-placed copy beats the file you are editing.** `notch.py` looks for `askpill.py`
in three places and `~/.local/bin/mrog-askpill.py` is **#2** — it won over the source at
`~/mrog/notch/askpill.py` (#3). No installer put it there; someone copied it once. Every
edit to the source changed nothing that ran, silently. It is a **symlink** now, and that
is the fix: not "remember to sync", but one file.

> This is the fleet's `donny_soul.md` lesson in a different costume: *a guard — or an
> edit — that names a path must be checked against the path the consumer actually opens.*
> Third instance recorded. Derive the path from the loading code, never from the doc.

**A hardcoded rect stops matching what GTK draws.** `pad_rect_now()` returned a constant
`360×150`. The split added a second row and a fifth button; the pad then wanted
**347×188**, so **38 vertical pixels were drawn outside their own input shape** — the
"next agent" button and the status line were *visible and dead to the pointer*. Same
family as the frozen desktop, just quieter: nothing crashes, nothing logs, a control
simply stops working. Measure the widget; floor it at the old constant so it never
shrinks below what you aim at; clamp it to the window; **re-apply the shape on
`size-allocate`** so it can never lag the pixels.

**Two copies of the tools directory.** `~/ceo-tools/askbar/` and `~/hermes/tools/askbar/`
had diverged — the live one was untracked, the tracked one was stale. `ceo-tools` is now
a symlink to the repo. Same fix, same reason.

## A screenshot is a viewport. `page` is the document.

A long thread, a tall article, a chat log: the part you scroll to is **not in the image**,
and OCR cannot invent it. `≣ page` reads the window through the **accessibility layer**
(AT-SPI) instead of grabbing pixels, so everything below the fold comes with it.

Measured on the laptop, same window, same moment:

| route | characters |
|---|---|
| full-screen screenshot + OCR | 5,860 — and that is all chrome, panels and other windows |
| `≣ page` | **12,705** — clean document text, front tab only |
| end to end | **724 ms** |

It is also the **only capture mode that takes no X grab**, so it cannot freeze anything.

**Requirements, both already true here:** `toolkit-accessibility true` and `GTK_MODULES`
containing `atk-bridge`. If accessibility is off, `win-text` **refuses** rather than
returning a fragment — truncated text that looks complete is the dangerous outcome,
because the agent cannot tell it is missing the second half and answers confidently
about what it never saw.

**Scoped to the front tab.** The first version walked every document in the tree and
returned **seven** — every open tab, 102k characters. Handing an agent six unrelated
pages and asking "what is the angle here" is worse than a screenshot.

**The window is resolved once, by the caller.** `ask` reads the active window and passes
`--win ID` down. The pill spawns `ask` asynchronously, so focus can move between the
click and the read; without this you silently capture whatever you clicked on next.

`feedback?` defaults to `page` — it always wanted the whole thread and used to make you
drag-select it.

### When NOT to use it

For anything with a **URL**, prefer handing Hermes the link: it has its own render lane
(`hermes_capture.sh`) and fetches the full thread server-side, and can follow it. Page
mode is for what is on *your* screen.

### Never test a pill on the desktop you are using

Two freezes came from the same root: the only way to see whether a pill worked was to
launch it on `:0`, where a bad input shape or a stuck grab takes the whole session down.

**`mrog-sandbox` — a nested X server.** Xephyr on `:9` with its own window manager and the
panel inside it. A grab taken there is scoped to that X server; `:0` never sees it.

```bash
mrog-sandbox start          # nested X + the panel inside it
mrog-sandbox shot out.png   # picture of the nested screen
mrog-sandbox click 512 110  # drive it
mrog-sandbox stop           # kills only PIDs it recorded — never a pattern kill
```

It found three defects in the first two minutes that no amount of reading would have:
an armed toggle styled identically to an unarmed one, a pad visible at startup while
`pad_open` was `False`, and a status line that disagreed with the highlight.

**`mrog-notch-trial N` — a deadman timer on the real display.** The panel goes live and
**reverts by itself** after `N` seconds unless confirmed:

```bash
mrog-notch-trial 60      # live for 60s
mrog-notch-trial keep    # ...if it looks right
mrog-notch-trial revert  # ...if it does not
```

🎯 **Doing nothing is the safe path, on purpose.** If the desktop freezes you cannot click
a "keep this setting?" dialog — a GUI confirm is useless exactly when it is needed. So the
default is revert, and *confirming* is the action that requires a working desktop.

The revert breaks grabs first, stops **one** service, and **never touches the compositor** —
killing Cinnamon is what cost a desktop on 2026-09-06: `mrog-unfreeze` saw a runaway shell
and shot it, `metacity` took the root window as Cinnamon's fallback, and Cinnamon could
then never get it back (`BadAccess`, `request_code 2` — the signature of *another WM already
owns this*). The recovery is `pkill -x metacity` and then `cinnamon --replace`.

Measured: active at t+6s, inactive at t+32s, nobody touched anything.

### Verify a pill without launching the panel

Restarting the panel to see whether a shape is right is how a desktop gets frozen. Build
the widget in a `Gtk.OffscreenWindow` instead — never mapped, no grab, no
override-redirect surface — and measure it:

```bash
timeout 30 python3 ~/mrog/notch/padfit.py     # prints the pad's real size vs the shape
```

Check it **fails** against the old rect as well as passing against the new one. A check
only ever seen passing proves nothing.

## Follow-ups — the window is no longer a dead end

Added 2026-09-16 (`FLEET-4HY`). Chris: *"it opens a 1-shot window, shows you what you
asked for and closes. Can I ask it follow-up questions and start a session if I need?"*

Before this, the window was `bash -c "$DISPATCH_INNER; read -rp 'enter to close'"`.
Whether you could talk back depended entirely on what `ask_cmd` happened to be:

| agent | `ask_cmd` | before |
|---|---|---|
| Claude | `claude '<prompt>'` — the interactive REPL primed with the question | already a session |
| Hermes | `hermes -z` — one-shot | **measured:** every one-shot is *saved* as a session on the Mini; there was just no door back in |
| Dreamzs | `dreamzs.sh -c` — one-shot | the thread lived in the CLI process's memory and died with it |

Now the window is **`ask-shell`** (`~/mrog/askbar/ask-shell`), and the registry says how a
row continues:

| `followup:` | meaning | rows |
|---|---|---|
| `native` | the first command holds the terminal itself. Run it, then the old `enter to close` | claude, dreamzs |
| `resume` | one-shot that persists a session. Pin its id (`sid_cmd`), then loop: **Enter** = close, **`/session`** = full REPL on this thread (`session_cmd`), **anything else** = next turn (`followup_cmd`) | hermes |

What you see is identical up to the answer. Then:

```
──────────────────────────────────────────────────────────
Hermes · follow up?  (Enter = close · /session = open the full REPL on this thread · id 20260916_152359_b0463e)
> _
```

Dreamzs gets there differently: `DREAMZS_STAY=1` → `dreamzs.sh` passes `--stay` →
`dreamzs_cli.py` answers the `-c` question and **falls into its own `dreamzs>` loop** with
the conversation intact, skipping the banner and `session_startup()`. Empty line closes
(stay mode only; the plain REPL still ignores empty lines).

### Proven by effect

- **Hermes:** turn 1 `-z` → `PING-4HY-ONE`. Turn 2 over `--resume <id>`: *"reply with the
  word you replied last time, with -TWO appended"* → **`PING-4HY-ONE-TWO`**. Content only
  turn 1 knew; `sessions list` shows the same id and no new row. The follow-up text carried
  `'`, `"`, `$HOME` and backticks and arrived literal.
- `_regcheck.py` driven red on each new class: `followup_cmd` without `{sid}`, an unknown
  `followup:` value, and `followup_cmd` present on a `native` row.

### Three things that would have bitten

**The follow-up goes over stdin, never argv.** Same trap this page already records under
*"The command carries a reference, not the question"*. `hermes chat --query-file -` is
documented as "nothing is shell-interpreted"; ssh passes stdin through untouched.

**The id is pinned once, not `--resume latest`.** `latest` is workspace-scoped and
re-evaluated per call — a gateway or cron turn landing mid-thread would redirect your
second follow-up into a different conversation. `sid_cmd` filters `--source cli`, runs
within seconds of the answer, and every later turn names that id.

🔴 **`%r` is not shell quoting.** `_reg.py` exported registry fields with Python `%r`, and
`sid_cmd` was the first field ever to contain a single quote — so `%r` chose *double*
quotes and `eval` expanded `awk '{print $NF}'` to `awk '{print }'` on the laptop. The sid
came back as the whole table row. Every earlier field merely happened to be quote-free.
Fixed with `shlex.quote` on every field. Found only because the first run used the real
path, not a hand-typed one.

Note: Hermes's `chat -Q` still prints three header lines (`↻ Resumed session …`, YOLO
notice, `session_id:`) above each follow-up answer. They are true and cheap; left in
rather than filtered by a pattern that could one day eat an answer.

Files: laptop `ask`, `ask-shell` (new), `_reg.py`, `_regcheck.py`, `agents.yml`
(`patch-FLEET-4HY-followup.sh`) · GpuBox `~/dreamzs-redteam/dreamzs_cli.py`
(`patch-FLEET-4HY-dreamzs-stay.py`) · Hub `~/ceo-tools/dreamzs.sh`
(`patch-FLEET-4HY-dreamzs-sh.py`). `.bak.FLEET-4HY.*` beside each.
