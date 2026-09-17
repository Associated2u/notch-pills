# 08 — the reader

A speaking button on the notch pill. Point it at text, it reads aloud through
the Ray-Ban Meta glasses (or any sink) and optionally opens a follow-along
window that highlights each line as it is spoken.

Built 2026-09-04, `SID:LINUX-E3X`. Code: `~/mrog/reader/`. Install:
`bash ~/mrog/reader/install-reader.sh`. Revert: `revert-reader.sh`.

## Why it exists

Measured across Chris's 13 Claude Code transcripts: **97,419 words of assistant
prose — about 9 hours of read-aloud at natural pace**, and **2,022 tool_use
blocks against 903 text blocks**, so ~69% of what Claude emits is scaffolding.

## Files

| file | role |
|---|---|
| `reader.py` | the engine. Sources, extraction, redaction, earcons, speaker. Installed as `mrog-read` |
| `notch_button.py` | button state machine + glyph. Imported by `notch.py` over `sys.path` |
| `pacer.py` | the follow-along GTK window |
| `voice-lab.py` | audition voices, sweep rate/pitch, write the config |
| `style-demo.py` | the original six-reading-styles demo, kept for provenance |
| `install-reader.sh` / `revert-reader.sh` | one paste each |

**`notch.py` carries only geometry** — a 26-line patch that imports
`notch_button` and fails safe (`ReaderButton = None`) if the module is absent.
Keep it that way; the reader must never be able to break the pill.

## Config is the single source of truth

`~/.config/mrog/reader.json` — read by `reader.py`, written by `voice-lab.py`,
shared with the button.

```json
{"voice": "English (America)+klatt", "rate": 40, "pitch": 0,
 "style": "verbatim", "pacer": "auto"}
```

🔴 **The button must NOT pass `--style` or `--rate`.** It originally kept its
own fallbacks and passed them as explicit flags, which beat the config file, so
every setting the voice lab wrote was silently overridden. It now passes only
`--pacer` (the per-click choice). If you add a setting, put it in the config and
let `reader.py` read it — do not add a second default anywhere.

Every run logs its **effective** settings to
`~/.local/state/mrog-reader/last.log`, which is how that class of bug gets
caught next time:

```
source=selection style=verbatim rate=40 voice='English (America)+klatt' pacer=off
```

## Sources

Tried in this order by `pick_auto()`: fresh selection → newest Claude message →
focused window.

| source | how | measured |
|---|---|---|
| `selection` | `xclip` PRIMARY | **5 ms** |
| `claude` | reads `~/.claude/projects/-home-chris/*.jsonl` | **5 ms**, exact |
| `window` | AT-SPI accessibility tree | **160 ms** |
| `window` | ffmpeg x11grab + tesseract fallback | **800 ms**, lossy |

`--delta` on the Claude source speaks only what is new since last time, tracked
in `~/.local/state/mrog-reader/<session>.jsonl.pos`.

**Pointing at the Claude app OCRs nothing** — `notch_button` matches WM_CLASS
against `com.anthropic.claude` / `claude-desktop` and routes to the transcript
instead. Add other apps to `CLAUDE_CLASSES` the same way.

AT-SPI needs `gsettings set org.gnome.desktop.interface toolkit-accessibility
true` (enabled 2026-09-04) **and** the app must have been launched since. The
bridge loads at app startup, so anything already running exposes nothing.
Electron apps additionally need `--force-renderer-accessibility`.

## Levels

`_spans()` yields `(kind, spoken_text, src_start, src_end)`. The offsets are
what make the pacer possible.

| level | kept | speedup |
|---|---|---|
| verbatim | 83% | 1.2x |
| skim | 53% | 1.9x |
| structure | 41% | 2.4x |
| gist | 10% | 10.1x |

Even verbatim saves 17%, because fenced blocks become one-line descriptions —
spelling a shell path aloud is unusable. `--code speak` reads them out instead.

🔴 **Chris uses `verbatim`, and compression is retired for the pacer.** A pacer
needs the voice and the eye on the *same words at the same time*; when the audio
skips a paragraph the eye is still on, the highlight jumps and there is nothing
to follow. **Compression and pacing are mutually exclusive.** `gist` still earns
its place for audio-only triage (`--style gist --pacer off`).

## Voice

espeak-ng via speech-dispatcher: ~2 MB, offline, ~0.1% of a core, and it stays
intelligible where neural voices smear.

**Chris's ear, tested:** klatt won; Alex and Storm were the only other two he
could follow; `whisper` was unusable. The common property is **high consonant
contrast and invariant phonemes**. Natural speech coarticulates — every sound
bends toward its neighbours — which helps a relaxed listener and hurts under
time compression. A synthesiser emits an identical `/t/` every time, so the
listener pattern-matches instead of inferring.

🔴 **Therefore mbrola and Piper are probably WRONG for him**, despite being the
obvious "upgrades". They are better because they are more natural, which is the
property that costs him speed. Do not install them on the assumption they help.

Measured wpm for klatt: rate 20 → 267, 40 → 329, 60 → 395, 80 → 448, 100 → 506.

🔴 **The ceiling is perceptual, not configuration.** Phonemes need ~60–80 ms to
be discriminated, so intelligible speech caps around 500–700 wpm. Chris reads
3–4x faster than that and has read at 8–10x in bursts. **No rate setting closes
that gap.** Reaching his real speed needs the audio to stop being the content
and become a metronome — chunked visual presentation at 8–10x with a tick per
chunk. Parked, not attempted.

## The pacer

Full text, everything dimmed except the live span, scrolled to keep it ~a third
down. Auto-raises over 60 words; a window for a six-word highlight is noise.

🔴 **The highlight is delayed by the live A2DP transport delay** — read from
BlueZ `org.bluez.MediaTransport1.Delay` (units 1/10 ms; **320 ms** on these
glasses). Without it the light runs ahead of the sound and the effect inverts.
Re-read at start, never hardcoded.

Markdown markers are hidden with an **invisible** GTK tag, not deleted, so every
source offset still lands on the right character. Deleting them would mean
maintaining a source→display offset map.

## Redaction

On by default — the glasses talk into a room. Non-destructive: you hear
"anthropic key redacted" rather than losing the sentence. `--no-redact` disables.

Verified both directions: 4/4 secrets caught; MAC addresses, paths, kernel
versions and `hub:mrog.git` all survive.

## Editing it

1. `reader.py`, `pacer.py` and `voice-lab.py` are read fresh from `~/mrog/reader`
   on every run — **edit and re-run, no install needed.**
2. `notch_button.py` is imported into the notch process at startup —
   **edit then `systemctl --user restart mrog-notch`.**
3. `notch.py` changes need the installer, which copies to `~/.local/bin` and
   checks the MainPID actually changed.
4. New spoken element? Add a kind in `_spans()`, an entry in `VOICE`
   (rate/pitch/earcon), a colour in `pacer.HOT_BG`, and always yield offsets.
5. New setting? Config file only. Never a second default in the button.

## 2026-09-16 — word sync, settings, and the public repo (`LINUX-QW6`)

**Word-level highlight.** Every source token in a span gets an SSML
`<mark name="N"/>`; speech-dispatcher fires `INDEX_MARK` as each is reached
and the pacer lights that exact word on top of the sentence highlight. Proven
11/11 marks fire with espeak-ng. ⚠️ The last two or three short words of a
sentence bunch — espeak submits the final audio buffer whole. Only in
`verbatim` (a compressed span does not contain the source's words).

**Right-click = settings** (`settings.py`, own process). Voice + Test, rate
with a wpm hint fitted to the measured klatt numbers (`207 + rate × 3`),
pitch, level, **what left-click does** (audio / audio + pacer), redact /
earcons / code toggles. Writes the shared config; live on the next read.
`notch.py` was NOT touched — it is another session's file — the existing
`click(pacer=True)` kwarg now means "secondary button".

🔴 **The public repo is `~/readalong`, a separate scrubbed tree — never a
fork of `~/mrog`.** Bare backup `hub:readalong.git` (verified 14 files
by clone-back). It is the upstream from now on; this tree is the private
working copy until the notch is pointed at it. What differs in public:

- config `~/.config/readalong/config.json`; state `~/.local/state/readalong/`
- Claude transcripts found by `~/.claude/projects/*/*.jsonl` (no hardcoded project)
- **the CLI is the integration surface**: `readalong --toggle` (arm, or stop
  if reading — one button) and `readalong --settings`; a pidfile at
  `~/.local/state/readalong/reading.pid` gives any bar its state
- the arm/pick flow lives in the CLI (`--pick`), not the button module;
  `integrations/gtk-pill/notch_button.py` is a thin shim over the CLI
- no SID-marker skip; `tests/test_reader.py` (8 checks, no pytest needed)

Installed here already: `readalong`, `readalong-settings`, `readalong-voices`
on PATH, config set to klatt / 40 / verbatim to match this tree.

**To switch the notch to the public version:** replace the import in
`notch.py` with `integrations/gtk-pill/notch_button.py` and change
`click(pacer=…)` to `click(secondary=…)`. Not done — `notch.py` is
mid-edit elsewhere.

**Traps added by running it today:** a scrub that turns an absolute path
into a bare relative one (`"reader.py"`) works from the package dir and
crashes from anywhere else — every cross-file import is `HERE`-relative now.
And `bash install.sh >/dev/null` from the wrong directory fails silently;
verify an install by the installed file's content.

## 2026-09-16 later — SpeedReader: tray, click model, numbers, presets, colours, security (`LINUX-V7P`)

**Renamed** the public tree `readalong` -> **`speedreader`** (`~/speedreader`,
bare `hub:speedreader.git`, `readalong.git` now stale). Public commit
452f6cf; private port 4b6e2d3.

**Click model, now uniform everywhere** (pill, tray, CLI): **left = read aloud,
right = follow-along window, middle = settings** (tray also: hold-left =
settings). Pill: `notch.py` one-line routing `ev.button in (1,2,3)` +
`click(button=ev.button)`; `notch_button.click(button=, pacer=None)` keeps the
legacy `pacer=` caller working so HEAD is runnable while `notch.py` (another
session's file) is uncommitted. The old right=settings was reverted at Chris's
request.

**System tray icon** (`speedreader-tray`, `tray.py`) — the answer to "did we
make a tray": there was none before, now there is. `Gtk.StatusIcon`, glyph
drawn to a pixbuf (light fill + dark outline so it reads on any panel; fills/
greens while reading, polled from the pidfile). Per-button clicks on X11
(verified `is_embedded: True` in Cinnamon), StatusNotifier menu fallback for
GNOME-style trays, `--quit`, tray.pid so the settings window can offer Quit.
Installer adds it + a `.desktop`; README documents panel-add per desktop.

**Numbers** (Chris: "it's reading numbers it shouldn't ... millions and
thousands"): `numbers` setting skip(default)/normal/digits. Skips IDs,
versions (`1.0.5`), times (`14:30`), hashes, MAC-like, 5+ digit runs; ALWAYS
keeps currency, %, years, 1-4 digit counts; KEEPS word-with-digits (`GPT-4`,
`mp3`, `COVID-19`) or it would delete real words. Filters AUDIO only - the
window still shows numbers. 🔴 Trap: the first classifier used `search` for a
small-int substring, so `1.0.5`/`98:59` were kept because "1"/"98" matched;
fixed to whole-token `fullmatch`.

**Presets**: easy/medium/fast/superfast = rate 15/40/68/95 (~250/330/410/490
wpm), buttons in settings + `--preset`.

**Colours**: follow-along window bg / text / sentence / word / read-text are
config keys, GtkColorButtons in settings, **Test** opens `pacer --preview`
with the unsaved colours via `SR_PREVIEW` env. Palette is `load_palette()`.

🔴 **Security stance — do not oversell it.** `docs/SECURITY.md` states plainly:
redaction is **best-effort, not a guarantee**. Threat model = don't announce a
key out loud / don't paint it in the window; NOT a DLP. Cannot catch:
plain-word passwords, unknown formats, split secrets, secrets inside a
word-with-digits token, or anything with `--no-redact`. Added JWT/Stripe/Google
OAuth/SendGrid/npm/PyPI/GitLab/`sk-proj-` patterns; fails toward silence, not
toward leaking. When asked "is this secure, confirm before public" the honest
answer given was **no, it is a seatbelt not a vault** - ship on-by-default,
link the doc, tell users not to point it at a secrets file.

**Divergence**: `~/speedreader` is upstream; `~/mrog/reader` is the private pill
copy, kept in sync this session by porting the four feature files and re-fixing
paths (config `~/.config/mrog/reader.json`, state `~/.local/state/mrog-reader`).
They WILL drift again if edited separately - edit public, re-port.

## 2026-09-16, third pass — pause button, GitHub, redaction re-verified (`LINUX-V7P`)

**Pause/resume.** The reader button becomes a pause control while reading:
left pauses/resumes, right stops, middle settings. Glyphs: ⏸ bars (reading),
▶ triangle (paused). 🔴 speech-dispatcher `pause()` only stops at an INDEX
MARK, so plain audio reads (no marks) could not pause mid-sentence - fixed by
inserting per-word SSML marks on EVERY read, not just the pacer. Verified a 4s
pause holds: 5.7s -> 12.5s. Mechanism: SIGUSR1 -> a flag serviced on the
speaker thread (never touch the SSIP socket from the signal handler); a
`paused` marker file drives the glyph. New button CLI `--primary`/`--secondary`
/`--playpause` branch on the pidfile; pill/tray/shim all route through them.

**Numbers, second tightening.** Audit of real transcripts showed 3-4 digit
dull numbers (ports 8080/3129, statuses 404/403/200, sizes 512/128, models
3050/2850) still spoken. Keep-threshold lowered to 1-2 digit bare ints; years
rescued by the year rule. Only years remain among 3+ digit kept.

**CPU note + agent guide.** SpeedReader is CPU-only (espeak, no model, no GPU);
documented in README with a "customizing" section (settings in the app;
redaction patterns and number rules are code). `AGENTS.md` added so agentic
tools can modify it safely.

**GitHub.** Public repo pushed to **github.com/Associated2u/speedreader**
(gh account Associated2u, `repo` scope). Created PRIVATE pending Chris's demo
video; flip with `gh repo edit --visibility public`.

🔴 **Redaction, asked again "no possible way to be bad" - answer is NO and was
shown, not claimed.** Adversarial test: catches all 7 structured shapes;
MISSES a bare password in prose, a passphrase, an unknown token format, and a
secret hidden inside a word token (kept 4/5 misses). Best-effort, not airtight;
`docs/SECURITY.md` is the honest writeup. Do not certify it complete.
