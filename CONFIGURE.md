# Configuring notch-pills

Three surfaces: **environment variables** on the user unit (the pills), **`askbar/agents.yml`**
(the ASK bar), and a handful of **file contracts** other tools write and the pill reads.
Nothing is compiled in that you would want to change without editing code.

## 1. Environment variables (the pills)

Set them on the unit, not in your shell — the notch is started by `systemd --user`:

```bash
systemctl --user edit mrog-notch      # opens a drop-in; add lines under [Service]
```

```ini
[Service]
Environment=MROG_NOTCH_GPU=ac
Environment=MROG_NOTCH_HOME=%h/Desktop/Captures
```

then `systemctl --user daemon-reload && systemctl --user restart mrog-notch`. **`restart`,
not `enable --now`** — the latter is a no-op on a running unit and silently keeps the old
process alive with an unchanged PID.

| variable | default | effect |
|---|---|---|
| `MROG_ROOT` | `~/mrog` | where the tree lives (askpill loader, reader, registry, installers, audit dirs) |
| `MROG_FLEET_HOSTS` | *(unset)* | `"a b c"` ssh aliases/addresses for the FLEET pill; unset = every `Host` in `~/.ssh/config` with a `HostName`; empty string = none |
| `MROG_NOTCH_MODEL_LABEL` | `Model state` | drop-down row label for the model-state dot |
| `MROG_NOTCH_MODEL_UI` | `/usr/local/sbin/mrog-legal-ui` | what a click on the model-state dot launches via `pkexec` |
| `ASKBAR_REGISTRY` | `$MROG_ROOT/askbar/agents.yml` | the ASK registry path alone |
| `MROG_NOTCH_FLEET` | `1` | `0` = no FLEET pill and no fleet helper child |
| `MROG_NOTCH_ASKPILL` | `1` | `0` = no ASK pill |
| `MROG_NOTCH_NOTE` | `1` | `0` = no NOTE pill (also off if GtkSourceView 4 is missing) |
| `MROG_NOTCH_SNAP` | `1` | `0` = no LAYOUTS pill and no drag-to-snap watcher |
| `MROG_NOTCH_GPU` | `auto` | `auto` read only while the card is already awake · `ac` sample on mains · `force` always · `off` never |
| `MROG_NOTCH_DGPU` | `0000:01:00.0` | PCI address of the discrete GPU (for `runtime_status`) |
| `MROG_NOTCH_HOME` | `~/Documents/mrog` | root for captures and notes |
| `MROG_NOTCH_SHOTDIR` | `$HOME/Screenshots` | screenshots (`shot-<ts>.png`) |
| `MROG_NOTCH_RECDIR` | `$HOME/Recordings` | recordings (`rec-<ts>.mkv`) |
| `MROG_NOTCH_NOTEDIR` | `$HOME/Notes` | scratchpad file + `state.json` |
| `MROG_NOTCH_ASK` | `1` | `0` = capture silently, no Delete/Open/Copy/Save/Keep dialog. **Not** the ASK pill — that is `_ASKPILL` |
| `MROG_NOTCH_HIDE_FULLSCREEN` | `1` | hide pills while the focused window is fullscreen |
| `MROG_NOTCH_HIDE_MAXIMIZED` | `1` | hide pills while it is maximised |
| `MROG_NOTCH_SHELL_LEASE` | `/run/mrog/lease.json` | root-lease file to watch (amber dot) |
| `MROG_NOTCH_INPUT_LEASE` | `/run/mrog/input-lease.json` | input-lease file to watch (red dot, STOP capsule) |
| `MROG_NOTCH_PANIC` | `$XDG_RUNTIME_DIR/mrog/input-panic` | panic flag: present = `INPUT HALTED` |
| `MROG_NOTCH_MODEL_STATE` | `/tmp/.mrog_model_state.json` | model-state file (LEGAL/NORMAL/SPLIT dot) |
| `MROG_NOTCH_RMB_QUIT` | `0` | `1` = right-click on the system pill quits the process |
| `MROG_NOTCH_DEBUG` | unset | `1` = print relayout geometry |

Overriding the lease/panic paths is how the indicators are **proven without arming a real
lease**: point them at a fake file, watch the dot change.

Pill positions are class constants (`ANCHOR`, `ANCHOR_FRAC` in `notch/notch.py`): system
`center`, LAYOUTS `frac 0.26`, NOTE `frac 0.74`, FLEET `right`. The ASK pill can be nudged at
runtime with `bin/askpill-pos --left|--right`.

The window layouts live in `__main__` of `notch.py` (`LAYOUTS = [...]`, zones as work-area
fractions) and, for the CLI, in `~/.config/mrog/workspaces.json` (generated on first run;
`term` is the per-zone launch command).

## 2. The ASK registry — `askbar/agents.yml`

Copy `askbar/agents.example.yml` to `askbar/agents.yml` and edit. Every field is explained at
the top of the example. Validate:

```bash
python3 askbar/_regcheck.py askbar/agents.yml
```

The checker refuses: unknown keys (nothing reads them, so the check you meant to add is not
running), a non-absolute first token in any command (a non-interactive ssh shell has almost
nothing on PATH — three of five routes were dead for a day because of this), a `vision`
that is not a real YAML bool, a health probe whose `ok` regex matches its own command (it
would pass on the echo), a `followup: resume` row missing `{sid}` in a command, and a
`native` row carrying resume-only commands.

Then prove the routes, not the file:

```bash
askbar/ask-selftest             # health probes only, free
askbar/ask-selftest --full      # + a canary round trip per row (skips paid rows)
askbar/ask-selftest --full --paid
```

### Where the question goes

`ask` writes `ask_<stamp>.txt` — a provenance header, your question, the OCR text — and,
for a `vision: true` agent, the `.png` beside it. The `.txt` is always the reference handed
to the agent; a sighted agent finds the image path inside it. The clipboard gets
`host:/path` for you.

Refused captures (secret scan) stay in `~/.askbar/staging` (mode 700) and never reach a
drop. `ask --force` overrides and records why in the sidecar.

### Timeouts

`ASKBAR_CAPTURE_TIMEOUT` (default 45 s) bounds every interactive grab so a hung capture
tool cannot hold the X grab forever. `agent_timeout` per row bounds the selftest canary.

## 3. File contracts (what the pill reads, so other tools can feed it)

All reads are on the 1 Hz tick, all tolerate a missing or malformed file — a status chip
must never be able to take the pill down.

**Root lease** — `/run/mrog/lease.json` (amber dot, `ROOT <scope> m:ss`):
```json
{"scope": "t1", "expires_at": 1758050000}
```

**Input lease** — `/run/mrog/input-lease.json` (red dot, STOP capsule, auto-hide suppressed):
```json
{"scope": "click", "expires_at": 1758050000}
```
Clicking the red dot or the STOP capsule runs the lease layer's revoke. The pill only
*displays* leases; granting is the companion `mrog-lease` / `mrog-input` layer
([docs/03-input-control.md](docs/03-input-control.md)), which is not in this repo.

**Panic** — the file `$XDG_RUNTIME_DIR/mrog/input-panic` exists ⇒ `INPUT HALTED`.

**Model state** — `$MROG_NOTCH_MODEL_STATE`:
```json
{"state": "LEGAL", "detail": "gpu-box LEGAL / mini LEGAL", "phase": "idle", "target": null}
```
(the original per-host shape `{"fleet": …, "studio": {"mode": …}, "mini": {"mode": …}}` is still
read). `state` ∈ `LEGAL | NORMAL | SPLIT` colours the dot; `phase` other than `idle`/`done` shows
`→ target (phase)` while a swap runs. Lives in `/tmp`, so it is gone after a reboot until the
writer runs again — the pill shows `no reading yet`. The writer here is a Dreamzs tool
([docs/09-dreamzs-weights.md](docs/09-dreamzs-weights.md)); anything can write it.

**Fleet helper** — `mrog-fleet-helper` prints one JSON line per sweep on stdout:
```json
{"ts": 1758050000, "hosts": [{"name": "hub", "addr": "192.0.2.132", "up": true, "ms": 3}]}
```
Flags: `--period 30 --timeout 1.5 --port 22 --once`. Hosts: the `FLEET` list at the top of
the file, resolved through `~/.ssh/config`.

**ASK status** — `ask` writes `~/.askbar/last` (`ok` / `refused` / `failed`) and the pill
greens or dims on it; `~/.askbar/selected` holds the current agent id (so `ask-now` on a
hotkey sends to whatever the pill shows).

## 4. Storage

```
$MROG_NOTCH_HOME/Screenshots/   shot-<ts>.png
$MROG_NOTCH_HOME/Recordings/    rec-<ts>.mkv
$MROG_NOTCH_HOME/Notes/         scratch.txt + state.json
~/.askbar/                      staging/ (700), last, selected, spawn.log
~/.config/mrog/workspaces.json  layouts for the `workspace` CLI
~/.local/state/mrog-reader/     last.log (reader button)
```

## 5. The unit

`notch/mrog-notch.service` — `WantedBy=default.target` (**not** `graphical-session.target`:
Cinnamon on Mint never activates it, so a unit wired there is enabled, symlinked and never
starts), an `ExecStartPre` that waits up to 30 s for the X server, `StartLimitBurst=0` in
`[Unit]` (under `[Service]` it is silently ignored), `Restart=on-failure` (a right-click quit
is a clean exit and stays down).

`notch/10-guard.conf` is the drop-in that adds the runaway fence: `CPUQuota=50%`,
`MemoryMax=500M`, and `ExecStart` swapped to `bin/mrog-notch-guard`. Install it to
`~/.config/systemd/user/mrog-notch.service.d/`; remove it to roll back.
