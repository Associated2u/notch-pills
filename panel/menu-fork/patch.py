#!/usr/bin/env python3
"""Turn the menu's single "Add to panel" into one item per bar.

Deliberately tiny: both new items just shell out to `panel-app`, which already
knows how to write each bar's very different data model and push the change
into the live applet. Keeping the logic OUT of the forked file is the whole
point - the fork should be as close to upstream as possible so it is cheap to
re-apply when Cinnamon updates.
"""
import re
import sys

OLD_ITEM = ('        menuItem = new ApplicationContextMenuItem(this, _("Add to panel"), '
            '"add_to_panel", "xsi-list-add");\n        menu.addMenuItem(menuItem);\n')
NEW_ITEM = ('        menuItem = new ApplicationContextMenuItem(this, _("Add to bottom bar"), '
            '"mrog_add_bottom", "xsi-list-add");\n        menu.addMenuItem(menuItem);\n'
            '        menuItem = new ApplicationContextMenuItem(this, _("Add to left bar"), '
            '"mrog_add_left", "xsi-list-add");\n        menu.addMenuItem(menuItem);\n')

OLD_CASE = '            case "add_to_panel":\n'
NEW_CASE = ('            case "mrog_add_bottom":\n'
            '                Util.spawnCommandLine("' + "$HOME" + '/bin/panel-app add bottom "'
            ' + this._appButton.app.get_id());\n'
            '                break;\n'
            '            case "mrog_add_left":\n'
            '                Util.spawnCommandLine("' + "$HOME" + '/bin/panel-app add left "'
            ' + this._appButton.app.get_id());\n'
            '                break;\n'
            '            case "add_to_panel":\n')


def main(path, home):
    src = open(path).read()
    if "mrog_add_bottom" in src:
        print("already patched"); return 0
    if src.count(OLD_ITEM) != 1:
        print(f"ANCHOR MISS: expected 1 'Add to panel' menu item, found "
              f"{src.count(OLD_ITEM)} - upstream changed, patch NOT applied", file=sys.stderr)
        return 1
    if src.count(OLD_CASE) != 1:
        print(f"ANCHOR MISS: expected 1 'add_to_panel' case, found "
              f"{src.count(OLD_CASE)} - upstream changed, patch NOT applied", file=sys.stderr)
        return 1
    src = src.replace(OLD_ITEM, NEW_ITEM).replace(OLD_CASE, NEW_CASE.replace("$HOME", home))
    open(path, "w").write(src)
    print("patched: two bar choices added, both delegating to panel-app")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
