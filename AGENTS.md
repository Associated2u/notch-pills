# Working on notch-pills (for AI coding agents and contributors)

A row of cairo-drawn GTK3 pills at the top of an X11 desktop; one Python process, a
`systemd --user` unit, no root. The ASK pill hands what is on screen to an agent and keeps the
conversation.
**This repo is a scrubbed export of the maintainer's working tree.** Machine names in
comments and docs are placeholders; the code paths are real.

## Layout

| path | what |
|---|---|
| `notch/notch.py` | the whole panel: `Notch` base class, SystemPill, FleetPill, NotePill, WorkspacePill, SnapZones, KillDot, sensors, GPU probe, window watch. Installed as `~/.local/bin/mrog-notch`. |
| `notch/askpill.py` | the ASK pill + pad; **exec'd into notch.py's namespace**, so it uses names defined there. Installed as a **symlink**. |
| `notch/mrog-gpu-helper.py`, `mrog-fleet-helper.py` | child processes: NVML (memory it never returns) and the network sweep. Nothing that blocks or leaks runs in the UI process. |
| `notch/padfit.py` | measure a pad offscreen; never launch the panel to check a size. |
| `notch/mrog-notch.service`, `10-guard.conf` | the unit and the runaway fence drop-in. |
| `bin/` | guard, sandbox (nested X), deadman trial, WM check, unfreeze, pill nudge. |
| `askbar/` | `ask` (capture→OCR→scan→drop→session), `ask-shell` (the window; follow-ups), `_reg.py`/`_regcheck.py` (registry read/validate), `agents.yml` (PRIVATE) + `agents.example.yml`, `ask-selftest*`, entry points `ask-pick`/`ask-now`/`ask-text`/`ask-agent`, `win-text` (AT-SPI page text). |
| `workspace/workspace`, `panel/` | layouts CLI; Cinnamon bar editor + menu fork. |
| `reader/notch_button.py` | the READ button; drives the speedreader CLI. |
| `docs/` | the engineering record. `90-traps.md` first. |

## Rules that matter

- **Send fixes as PRs against this tree.** They are ported into the maintainer's private
  tree and come back in the next export, so a local edit here is never the last word.
- **`tick()` may not block.** No subprocess, no network, no NVML in the UI process. A slow
  thing is a child that writes a state file.
- **Never test a pill on the desktop you are using.** `mrog-sandbox` (Xephyr) or
  `mrog-notch-trial N` (reverts by itself). A bad input shape or a stuck grab freezes the
  session, and a grab survives a compositor restart.
- **A subclass inherits the parent's costs.** `NEEDS_GPU=False`, `NEEDS_SENSORS=False` on
  every pill that does not need them; check the child process list after adding one.
- **The registry is the policy.** Agents, intents, follow-up contracts are rows in
  `agents.yml`; the pad and the picker read the same rows. Adding code where a row would do
  is how the two menus drift.
- **Shell exports use `shlex.quote`, not `%r`.** `_reg.py` once emitted a double-quoted
  string for a value containing `'`, and `eval` expanded `$NF` inside it.
- **Commands carry references, not text.** The question is in the dropped file; follow-up
  text goes over stdin. Never argv through `bash → ssh → zsh`.
- **Verify by effect, and drive checks red first.** `_regcheck.py` was proven by feeding it
  registries that must fail; the follow-up path was proven by a turn-2 answer that could only
  come from turn 1. A green check never seen red proves nothing.

## Quick check

```bash
python3 -c "import ast,glob;[ast.parse(open(f).read()) for f in glob.glob('*/*.py')]" && bash -n askbar/ask askbar/ask-shell bin/* && python3 askbar/_regcheck.py askbar/agents.example.yml
```
