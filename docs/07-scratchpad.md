# The NOTE pill and its scratchpad

## What it is, and what it is not

A real `GtkSourceView` (171 languages) living **inside** the NOTE pill's own
window, dropping into the top-right corner. Deliberately **not** an attempt at
Notepad++: this is the quick-capture half. Anything that deserves a session, a
plugin or a 500 MB file goes to Kate via **Open in Kate**, which saves first and
then hands the file over.

That division of labour is why it stays small.

## Sizes

Three, all right-anchored to the same edge, measured from the running app:

| | | |
|---|---|---|
| **S** | 460x320 | a small box in the corner |
| **M** | 960x600 | half the corner |
| **L** | 1382x1008 | the whole corner |

## Behaviour

- **Autosave** debounced 1.5 s, plus on close. Nothing is lost by closing it.
- **Reopens exactly where you were** — file, cursor offset and size restored from
  `Notes/state.json`.
- Ctrl+F find (Enter next, Shift+Enter previous), Ctrl+S, Ctrl+N, Esc closes.
- **Recent** lists recently-used text files from `Gtk.RecentManager`.

## Three traps

🔴 **A `Gtk.Box` toolbar pushes its parent out rather than clipping.** The S size
could not get below the toolbar's natural width until the toolbar went into a
`ScrolledWindow` with `propagate_natural_width=False`.

🔴 **A style scheme colours syntax, not the widget.** The editor rendered white
against the dark pill; the background is now set outright with CSS.
`Adwaita-dark` does not exist here — the dark schemes are `oblivion`, `cobalt`,
`solarized-dark`.

🔴 **A `DOCK` window takes no keyboard focus.** `set_accept_focus(True)` **before
realise** is what makes an embedded editor typable.

## Cost

The editor takes the notch from 50 MB to ~62 MB. That is the price of a real
editor rather than a text box; it could be made lazy on first open if that ever
matters.
