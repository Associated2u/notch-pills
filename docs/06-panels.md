# The two Cinnamon bars

## Why the GUI could only edit one

They are **different applets with different data models**:

| bar | applet | key |
|---|---|---|
| bottom | `grouped-window-list@cinnamon.org` | `pinned-apps` |
| left | `panel-launchers@cinnamon.org` | `launcherList` |

The menu's "Add to panel" resolves a **single role provider**
(`Roles.PANEL_LAUNCHER`) — only one launcher applet can hold `panellauncher`,
and Cinnamon logs `Role locked: panellauncher`. So the menu has exactly one
target and no concept of choosing. There is no setting for this.

**Bar-to-bar dragging is impossible**: `panel-launchers.handleDragOver()` needs a
`LauncherDraggable` or `isDraggableApp`, and `grouped-window-list` never sets
that on its own app groups. Dragging out of the *menu* onto either bar does work.

## `~/bin/panel-app`

    panel-app bars | list <bottom|left> | search <term>
    panel-app add <bar> <app> [index] | remove <bar> <app|index>
    panel-app move <bar> <from> <to>  | copy <app> <src> <dst>
    panel-app edit-mode on|off        | apply

`copy` is the thing the GUI cannot do. `edit-mode` toggles Cinnamon's panel edit
mode, which drags **applets between panels** — not launchers into a launcher
applet, which is why it looked broken.

## 🔴 Writing the JSON is only half the job

Measured on Cinnamon 6.6.9:

- **`ReloadXlet` returns success and does not re-read the list.**
- **`restartCinnamon()` does not either** — it reloads the shell *in-process*;
  the Cinnamon PID never changes.

The applet caches its list in memory and `_reload()` iterates whatever *it*
holds. The fix is to push the list into the **live applet object** over
Cinnamon's own `Eval` dbus method:

    left  : d.applet.launcherList = [...]; d.applet._reload()
    bottom: d.applet.settings.setValue('pinned-apps', [...]);
            d.applet.pinnedFavorites.onFavoritesChange()

Reach the instance via `imports.ui.appletManager.definitions` — **`appletObj` is
empty on 6.6.9**, which is why introspection kept returning blank. `panel-app`
does this automatically on every write; applies in under two seconds, no restart.

## The menu fork

`~/.local/share/cinnamon/applets/menu@cinnamon.org` — a **9-line diff** over the
3030-line stock file, adding **Add to bottom bar** / **Add to left bar**, both
shelling out to `panel-app` so the fork stays minimal.

Cinnamon loads applets from `~/.local/share/cinnamon/applets` **first**
(`findExtensionDirectory` checks the user dir before the system dirs), so this is
a user-level override with no root, reverted by deleting one directory.

🔴 **Only `cinnamon --replace` loads new applet CODE.** Neither `ReloadXlet` nor
`restartCinnamon()` will. Windows are not closed by it.

    install.sh   apply      revert.sh   undo      check.sh   has upstream moved?

**The cost:** it forks a 3030-line upstream file. Mint's updates will not reach
the copy until `install.sh` is re-run. `patch.py` refuses to apply if its anchors
have moved, rather than producing a broken menu.
