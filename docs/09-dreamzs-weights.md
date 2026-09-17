# Dreamzs weight switching — the two-model LEGAL/NORMAL swap

Added FLEET-CB2, 2026-09-05.

## What this controls

Dreamzs answers from **two llama-server hosts**, and both must run the same
weight family or the fleet is incoherent:

| host | NORMAL (abliterated) | LEGAL (non-abliterated) | daemon |
|---|---|---|---|
| GpuBox | `Huihui-Qwen3-Next-80B-A3B-Instruct-abliterated.i1-Q4_K_M.gguf` | `Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf` (48,410,988,384 B) | `com.profmeme.llama-qwen3next` |
| Mini | `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K.gguf` | `Qwen3.6-35B-A3B-MXFP4_MOE.gguf` (21,706,144,736 B) | `com.donny.llama-qwen36` |

GpuBox serves `main, ops, vault, assist, plan, counsel`.
Mini serves `router` and every `-fast` twin.

**LEGAL is the working mode.** Chris's ruling 2026-09-05: training runs on
non-abliterated weights; the abliterated pair is **experimental, manual only**.
That is why NORMAL is drawn amber, never green — "will not refuse" must never
read as the safe state.

## The controls

### Centre pill (the everyday one)

    ●  ▶  CPU 7.7%  RAM 8.0/23.1G
    │  └── weights triangle
    └───── lease dot

**Weights triangle** — centre pill only (`SystemPill.SHOWS_WEIGHTS = True`;
every other pill inherits `False`). Colour is the fleet state:

| colour | meaning |
|---|---|
| green | LEGAL — non-abliterated, able to refuse. Training mode. |
| amber | NORMAL — abliterated. Experimental only. |
| red | **SPLIT** — the two hosts disagree. See *Failure modes*. |
| pulsing | a swap is running. It takes minutes; solid = loaded. |

Click it → polkit password dialog → the swap runs **detached**. The terminal is
not the progress bar; the triangle is.

**Lease dot** — unrelated to weights, documented in `03-input-control.md`.
Grey idle, red input lease, amber root lease. Click grants (`input 10 click`)
or stops whatever is live.

### Other routes

    dreamzs-legal-mode              toggle, interactive, typed YES
    dreamzs-legal-mode --status     print state, change nothing (exit 1 = split)
    dreamzs-legal-mode --menu       pick a target explicitly
    dreamzs-legal-mode --toggle-bg  detached; what the triangle calls
    dreamzs-legal-mode --check-routes  can the button work? changes nothing

`--check-routes` is the one that matters after any change to the Macs. It asks
each host, over a FRESH non-interactive connection (`BatchMode=yes`, no TTY, no
password fallback), whether the wrapper answers passwordless:

    gpubox:     BACKGROUND-CAPABLE (wrapper, passwordless, no TTY)
    mini-wg: BACKGROUND-CAPABLE (wrapper, passwordless, no TTY)

Exit 0 means the triangle can swap in the background. **Running
`dreamzs-swap-daemon check` at the end of an `ssh -t` install session proves
nothing** — that session already holds a cached sudo timestamp, and that exact
accident is what made the first background swap half-succeed and leave the fleet
SPLIT.

The favourites-bar launcher runs the bare form (interactive).

## Fleet-wide: how a remote session flips it

**The state is not stored anywhere authoritative — it is derived.** `ps` argv on
the GpuBox and the Mini is the only truth, which is why `current_model()` reads
that and never a plist (`launchctl kickstart` uses a *cached* job definition, so
a plist can say one thing while the loaded weights say another).

Consequences:

- Any host that can SSH to **both** GpuBox and Mini can read or flip the fleet.
  Copy `~/bin/dreamzs-legal-mode` there and it works — no daemon, no shared
  state store, nothing to keep in sync.
- **Hub is the second button and it is installed** (`hub:~/bin/dreamzs-legal-mode`,
  FLEET-CB2 2026-09-05). Always-on, already reaches both hosts. Verified by
  effect: both machines report identical fleet state.
- `/tmp/.dreamzs_mode.json` on the laptop is a **cache for the pill only**. If
  it is stale, wrong or missing, run `--status` and it is rewritten. Never treat
  it as authoritative.
- If the laptop is offline, Hub flips it and the laptop picks up the truth
  the next time anything reads.

### ONE file, not two copies

The same script runs on the laptop and on Hub. Two copies would drift --
that has already happened twice on this machine (the notch, repo vs
`~/.local/bin`, 49 lines apart; and the systemd user units). So it resolves what
differs at runtime:

| differs | how it is resolved |
|---|---|
| Mini alias — laptop has `mini-wg`, Hub only `mini` | tries each, takes the first with a **real `Host` block** |
| freeze table — remote from the laptop, local on Hub | `FREEZE_LOCAL=1` if `~/.openclaw/UPDATES/freeze_table.sh` is executable here |

SSH to the Mini works over the LAN from Hub: **pf blocks the model port
(:8080, :18910), not sshd.** The WireGuard alias is only needed where the script
must reach the model port, which this one never does.

To update both, edit the laptop copy and:

    scp ~/bin/dreamzs-legal-mode hub:~/bin/dreamzs-legal-mode

## Failure modes

**SPLIT** — GpuBox and Mini on different families. Half the profiles answer from
each. Any grade measured across them describes a fleet that does not exist.
- The triangle goes red; `--status` exits 1.
- `--toggle-bg` **refuses** — "the other way" is ambiguous.
- The curriculum **refuses to score at all**.
- Fix: `--menu`, pick the target explicitly, finish or roll back.

**FROZEN window** — a show is on air or within ±30 min.
- Interactive offers a typed `FORCE` override, because Chris is there to make
  that call.
- **Background refuses outright.** No one is there to make it, and taking the
  fleet down mid-show is exactly what the check exists for.

**A host down** — no swap. It cannot verify what it replaced if nothing is
running.

## After a swap

1. **Reload the Open WebUI page.** It caches the model list. `sync_owui_persona`
   re-points the persona, but the browser will keep the old list until reloaded.
2. Grades are keyed **`profile::abl`** or **`profile::legal`** and are *never*
   averaged. A grade measured on one family says nothing about the other.
   `dreamzs_trust.py report` and the curriculum both scope to the live family.

## Files

| path | what |
|---|---|
| `~/bin/dreamzs-legal-mode` | the switch (laptop; copy to Hub for the second button) |
| `~/mrog/input/mrog-legal-ui` | polkit target — authenticates, then **drops back to the user** |
| `~/mrog/input/com.mrog.legal.policy` | polkit action `com.mrog.legal.toggle` |
| `/tmp/.dreamzs_mode.json` | pill cache: `fleet`, `phase`, `target`, per-host mode |
| `~/mrog/audit/legal-mode-*.log` | one log per background swap |
| `gpubox:~/models/swap_llama.sh` · `mini:~/models/swap_llama.sh` | does the actual stop-load-verify |

### Why a root wrapper for something that needs no root

`dreamzs-legal-mode` makes **zero** sudo calls — it is pure SSH. The polkit step
is not a privilege grant, it is an **authorisation**: the swap takes every
Dreamzs profile dark for minutes, and that deserves a deliberate act. It
replaces the typed `YES`.

`pkexec` runs its target as root, but the swap needs *Chris's* SSH keys, so
`mrog-legal-ui` authenticates and then `runuser`s straight back to the invoking
user. **Root is the gate, never the context the work happens in.** The script
path is hardcoded — a pkexec target that takes a program to run as an argument
is a privilege escalation with extra steps.

## Why the background swap needs a root wrapper on the Macs

The button could not work as first built. `swap_llama.sh` needs root, and a
**detached job has no TTY for a remote sudo prompt**. It appeared to work once
only because an earlier interactive swap had left a cached sudo timestamp on the
GpuBox — the Mini's had expired, so that host aborted and the fleet went SPLIT.
Intermittent success is worse than consistent failure.

**NOPASSWD on the commands it uses was not an option.** Measured, the script
needs five distinct privileged binaries:

    true · cp / cp -p · launchctl bootout / bootstrap · plutil -insert / -lint / -remove

Granting the two launchctl calls alone still prompts at `cp` and `plutil`. And
NOPASSWD on `cp` or `plutil` with free arguments **is unrestricted root** —
`sudo cp <anything> <anywhere>` rewrites any file on the machine.

So `dreamzs-swap-daemon` follows the pattern `mrog-apply` and `mrog-lease-ui`
already use: one root-owned entry point taking a **verb, never a path**, with
label/plist/model hardcoded per host. The sudoers grant names that one path, and
is a strictly *narrower* surface than granting the commands it wraps.

**The escalation it deliberately avoids:** it does **not** exec
`~/models/swap_llama.sh`. That lives in a user-writable home, and a NOPASSWD
wrapper that runs a user-writable script is arbitrary root with extra steps. It
runs the root-owned copy at `/usr/local/sbin/dreamzs-swap-llama.sh` and refuses
to start if that file is not root-owned and non-user-writable — verified on
every invocation, not just at install.

`swap_one()` tries the wrapper first and falls back to `ssh -t` where it is not
installed, so the switch keeps working either way. Without a TTY **and** without
the wrapper it now refuses loudly instead of half-swapping.

## Install (root-owned, Chris runs these)

    sudo install -o root -g root -m 0755 ~/mrog/input/mrog-legal-ui /usr/local/sbin/mrog-legal-ui
    sudo install -o root -g root -m 0644 ~/mrog/input/com.mrog.legal.policy /usr/share/polkit-1/actions/com.mrog.legal.policy

Until these run the triangle shows status correctly but clicking does nothing.

## Traps

- **`ps` argv is the only truth.** Not the plist, not `launchctl list`.
- **Neither box holds two copies.** GpuBox 64 GB vs a 48 GB model, Mini 32 GB vs
  20 GB. The running model stops *before* the new one loads — the outage is
  structural, not a bug.
- **Editing `~/mrog/notch/notch.py` alone does nothing.** The service runs
  `~/.local/bin/mrog-notch`, a separate copy. They had drifted by 49 lines.
  Install, then confirm the restart by a MainPID change.
- **Right-click on the pill quits it** (`Gtk.main_quit()`). Both buttons now
  swallow right-click, but everywhere else on the pill still quits — that is how
  Chris lost every top panel once.
- **A swap cannot be rehearsed.** Testing it *is* the outage, which is why split
  detection and finish-or-roll-back exist instead of a dry-run.
- **`ssh -G <alias>` is NOT a test that an alias exists.** For an unknown alias
  it echoes the alias back as the hostname, so a naive "does it print a
  hostname" check passes for aliases the host cannot resolve. It picked
  `mini-wg` on Hub, which cannot resolve it, and the switch reported
  the Mini **DOWN while the Mini was serving perfectly** — a false negative that
  would have blocked the swap. A real `Host` block rewrites hostname to
  something *other* than the alias; that is the test.

---

## The two favourites-bar buttons (2026-09-05)

There are now three ways to swap, and they all do the same thing:

| Control | Runs | Terminal? | Notes |
|---|---|---|---|
| Notch triangle (centre pill) | `--toggle-bg` | no | detached, logs to `~/mrog/audit/legal-mode-*.log` |
| **Dreamzs Legal Mode** icon (favourites bar) | `--toggle` | yes | full toggle, no confirmation — same as the triangle |
| Hub `~/bin/dreamzs-legal-mode` | `--toggle` | yes | identical script, host-portable |

The launcher is a **full toggle**, not a one-way switch: `Exec` has no argument,
and a bare invocation falls through to `''|--toggle`, which reads the fleet and
swaps to the other family. LEGAL→NORMAL and NORMAL→LEGAL both work from it. It
refuses to guess on a SPLIT fleet — use the right-click menu and name a target.

**Right-click the icon** (the Cinnamon launcher applet renders desktop actions
above "Launch", `applet.js:34`):

- *Which weights are loaded now?* — `--status-hold`, shows both hosts, changes nothing
- *Pick a target explicitly* — `--menu`, the only safe way out of SPLIT
- *Check the swap routes* — `--routes-hold`, answers "can the triangle work"
  without swapping

Each action holds the terminal open. An action that opens a window and closes it
in the same frame shows nothing and reads as a dead click.

### Laptop Pills button

`~/bin/mrog-pills` (`toggle` / `on` / `off` / `status`), favourites bar, monitor
icon. This exists because right-clicking a pill quits it and there was **no way
back without a terminal**. Right-click gives On / Off / Status directly.

It toggles `mrog-notch.service`, and it **enables and disables** as well as
starting and stopping. The unit is enabled, so `stop` alone turns the pills off
only until the next login — "leave it off" would have quietly un-left itself
overnight. `status` prints both: `pills: inactive   at login: disabled`.

`turn_off` clears stragglers by PID from `ps`, never `pkill -f mrog-notch` —
that pattern matches the script's own command line and kills the caller. It has
done so twice.

## Traps (added 2026-09-05)

- 🔴 **Desktop notifications were switched OFF machine-wide.**
  `org.cinnamon.desktop.notifications display-notifications` was `false`, so
  every `notify-send` in the fleet returned success and rendered nothing. A
  notification path can be fully built, syntactically perfect, and invisible.
  Turned on 2026-09-05. To put it back:

      gsettings set org.cinnamon.desktop.notifications display-notifications false

- **Adding a launcher does NOT need a full Cinnamon restart** — that trap is
  about *icon* changes. A launcher-list edit needs only the applet reloaded:

      dbus-send --session --dest=org.Cinnamon --type=method_call /org/Cinnamon \
        org.Cinnamon.ReloadXlet string:'panel-launchers@cinnamon.org' string:'APPLET'

  Edit `~/.config/cinnamon/spices/panel-launchers@cinnamon.org/15.json`
  (`launcherList.value`), validate the JSON, then reload. Same call re-reads
  desktop actions after a `.desktop` edit.
