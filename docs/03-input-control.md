# Input control

## The shape of it

    mrog-input-lease   root, password-gated, NOT in any NOPASSWD rule   ARMS it
    mrog-input         unprivileged, no setuid                          USES it
    mrog-input-kill    root, NOPASSWD, deletes one file, nothing else   STOPS it

On X11, XTEST input needs no root at all, so the verb surface is a plain
unprivileged binary. The only privileged pieces are arming (costs a password)
and killing (deliberately free).

**The asymmetry is the design: stopping input is free, starting it is not.**

## The six gates

Every mutating event passes all six, in order:

1. **panic file** — the no-password halt
2. **live lease** — self-expiring, 15 min ceiling
3. **scope** — `click` and `type` are armed separately
4. **budget + rate** — 400 events max, 60 ms floor between events
5. **human-motion abort** — the pointer moved without us
6. **window denylist** — re-checked before *every* event

## Proven, not assumed

Every gate was driven to fail on its own stated failure class
(`~/MROG_INPUT_PROOF_2026-09-04.md`):

| gate | result |
|---|---|
| live lease | `REFUSED (no-lease)` |
| panic | `REFUSED (panic)` |
| scope | `type`/`key` → `REFUSED (scope-is-click-need-type)` |
| denylist | `click` on gnome-terminal → `REFUSED (denied-class)` |
| human-motion | pointer moved past the radius → panic latched |
| budget | **not exercised** — needs 400 events |

Positive case too: a granted lease permits, and the event is logged with the
target window's class and title.

## Why the denylist matters most

**Typing into a terminal bypasses `guard-bash` entirely.** That hook inspects
Bash *tool calls*; it cannot see keystrokes delivered to a terminal window. So
terminals are denied by class, and VS Code with them — its integrated terminal
lives in a window whose `WM_CLASS` is indistinguishable from the editor's.

Also denied: polkit and password prompts, keyring and password managers, VM
consoles, and titles matching TIER-REAL services.

## The safe radius

🔴 The drift tolerance was **3 px, per axis** — unusable. A hand resting on a
mouse exceeds it, and *a safety feature that cries wolf gets switched off*, which
is worse than not having one.

Now a **radius of 212 px = 1.5 inches** at this panel's 141 dpi, compared as
squares so it stays integer arithmetic. Per-axis was a box: a diagonal drag had
to travel further to trip. `input-policy.conf` carries the recompute formula.

    hand resting  0.33in  allowed        1.5in diagonal  abort
    1in any dir   1.00in  allowed        2in grab        abort

## Stopping it

**The best kill switch is grabbing the mouse.** The motion abort fires on
movement the agent did not cause and destroys the lease. No button, no command,
no memory — which is the whole problem with kill switches in a panic.

The **STOP capsule** is the backstop and the confirmation: a red capsule at the
top-left of the *work area* (so it never covers the favourites bar), sized to its
text, showing a countdown, appearing only while a lease is live.

🔴 It sits above fullscreen windows because a `Gtk.WindowType.POPUP` is
**override-redirect** — the WM does not manage it, so it is not stacked under a
fullscreen client the way `DOCK` pills are.

Both paths call `mrog-input-kill`, which deletes the root-owned lease. Deleting
the soft flag by hand no longer brings input back.

## Extending it

New verbs go in the `case` in `mrog-input` and **must** call `gate <scope>`
before acting and `record` after. A verb that skips `gate` is a hole.
Read-only verbs (`where`, `window`, `shot`) deliberately skip it — Level 0.

## The limits, stated honestly

- `/etc/sudoers.d/99-chris-apt` **does not exist**; passwordless apt is gone and
  the remaining four NOPASSWD rules were each read and cleared. `env_reset` and
  `secure_path` are set. **The model is enforcing, not advisory.**
- An earlier version of this document claimed the opposite, from a stale audit
  note repeated without re-checking. **Re-measure a security premise before
  building on it.**
