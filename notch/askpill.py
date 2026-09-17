"""askpill — the ASK pill: pick an agent, type, capture, send.

Rebuilt 2026-09-06 after Chris's review of v1. v1 was an agent SELECTOR, not an Ask Bar: the
text box, the capture controls and the drag-to-window gesture only ever existed in the
standalone askbar.py and were never carried across. Everything below exists because he named
it as missing.

WHAT THE FRAMEWORK FORCED, and it is all in 02-pills.md / notch.py:

  * tick() runs at 1 Hz on the GTK main loop -- "No subprocess, no network". So this pill NEVER
    runs a capture inline. It spawns ask-now with GLib.spawn_async and returns immediately.
    Blocking here freezes system/LAYOUTS/NOTE/FLEET too.

  * apply_input_shape() must follow the drawn capsule. v1 overrode on_pill_click and dropped
    the base's call to it, and also changed the pill's WIDTH for a flash; the input region
    stopped matching the pixels and the window swallowed clicks across the screen -- a frozen
    desktop with nothing in any log. The pad is now the thing that changes size, and every
    state change re-shapes.

  * 🔴 RIGHT-CLICK QUITS A PILL (notch.py on_click -> Gtk.main_quit). There is a logged
    incident of Chris right-clicking and losing every panel. Right-click over THIS pill is
    swallowed and opens the pad instead. Never let a button-3 fall through to the base.

  * An embedded editor needs the keyboard, so set_accept_focus(True) BEFORE realise -- the same
    note NotePill carries.

CLICK vs DRAG. v1 cycled the agent on button-press, so any attempt to drag the pill changed
the model instead. Press position is now recorded and the action only fires if the release
lands within DRAG_SLOP of it; anything further is a drag and is left alone.
"""
import os, time
import cairo
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

STATE_DIR = os.path.expanduser("~/.askbar")
SELECTED  = os.path.join(STATE_DIR, "selected")
LAST      = os.path.join(STATE_DIR, "last")
REGISTRY  = os.environ.get("ASKBAR_REGISTRY") or os.path.join(
    os.path.expanduser(os.environ.get("MROG_ROOT", "~/mrog")), "askbar", "agents.yml")
ASK_PICK  = os.path.expanduser("~/bin/ask-pick")   # one entry point; see its header
DRAG_SLOP = 6          # px; beyond this a press+release is a drag, not a click


def _hex_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _load_intents():
    """From the registry, so the pad's buttons and ask-pick's menu can never disagree."""
    try:
        import yaml
        d = yaml.safe_load(open(REGISTRY))
        return [(i["id"], i["label"], i.get("capture", "region")) for i in d.get("intents", [])], \
               {i["id"]: " ".join(i["prompt"].split())[:150] for i in d.get("intents", [])}
    except Exception:
        return [], {}


def _load_agents():
    try:
        import yaml
        return yaml.safe_load(open(REGISTRY))["agents"]
    except Exception:
        return [{"id": "?", "label": "ASK", "color": "#666666",
                 "model": "registry missing", "vision": True, "drop": "-"}]


class AskPad(Gtk.Box):
    """The body: one line to type in, and the capture verbs. A Box, so the pill hosts it
    directly -- the same shape ScratchPad uses for NotePill."""

    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.owner = owner
        self.set_border_width(10)

        # 🔴 A PAD WITH NO BACKGROUND IS UNREADABLE. The pill's window is transparent except
        # where the capsule is drawn, so an embedded Box inherits whatever is behind it --
        # Chris's first look: "hard to see without a background in it". Painted here in the
        # panel's own palette rather than left to the theme, so it matches the pills.
        self.set_name("askpad")
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        #askpad { background: rgba(14,14,18,0.97);
                  border: 1px solid rgba(255,255,255,0.10);
                  border-radius: 12px; }
        #askpad entry { background: rgba(255,255,255,0.06); color: #e6e6ea;
                        border: 1px solid rgba(255,255,255,0.12); border-radius: 8px;
                        padding: 6px 8px; }
        #askpad button { background: rgba(255,255,255,0.07); color: #dcdce2;
                         border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;
                         padding: 4px 6px; }
        #askpad button:hover { background: rgba(255,255,255,0.14); }
        #askpad button:checked { background: rgba(96,165,250,0.30);
                                 border: 1px solid rgba(147,197,253,0.65);
                                 color: #ffffff; font-weight: bold; }
        #askpad button:checked:hover { background: rgba(96,165,250,0.42); }
        #askpad label { color: #9aa0aa; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("ask… (Enter sends, Esc closes)")
        self.entry.connect("activate", lambda *_: self.owner.send_intent(None, self.mode))
        self.pack_start(self.entry, False, False, 0)

        # 🔴 MODE ARMS, INTENT FIRES. The first pad welded them together: clicking "region"
        # captured AND sent, so there was no moment between grabbing something and committing
        # it -- Chris hit that immediately. Mode is now sticky state; the intent row is the
        # verb, and what you click says WHAT YOU WANT rather than how to grab it.
        self.mode = "region"
        self.mode_btns = {}
        mrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        mrow.pack_start(self._dim("grab:"), False, False, 0)
        # ≣ page reads the window's WHOLE document through accessibility -- everything
        # below the fold, which a screenshot can never reach. It is also the only grab that
        # takes no X grab at all, so it cannot freeze anything.
        for label, mode in (("▣ window", "window"), ("⬚ region", "region"),
                            ("▢ screen", "screen"), ("≣ page", "page"),
                            ("○ none", "none")):
            b = Gtk.ToggleButton(label=label)
            b.set_active(mode == self.mode)
            b.connect("toggled", self._on_mode, mode)
            self.mode_btns[mode] = b
            mrow.pack_start(b, True, True, 0)
        self.pack_start(mrow, False, False, 0)

        # Intents come from the registry, so rewording one or adding a sixth never touches
        # this file. Each button captures in the ARMED mode and sends.
        irow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        irow.pack_start(self._dim("ask:"), False, False, 0)
        for iid, label, cap in owner.intents:
            b = Gtk.Button(label=label)
            b.set_tooltip_text(owner.intent_tip(iid))
            b.connect("clicked", lambda _b, i=iid, c=cap: self.owner.send_intent(i, c))
            irow.pack_start(b, True, True, 0)
        self.pack_start(irow, False, False, 0)

        self.who = Gtk.Label()
        self.who.set_xalign(0.0)
        self.who.set_ellipsize(Pango.EllipsizeMode.END)
        self.pack_start(self.who, False, False, 0)

        nxt = Gtk.Button(label="↷ next agent")
        nxt.set_tooltip_text("also: click the coloured dot on the pill")
        nxt.connect("clicked", lambda *_: self.owner.cycle_agent())
        self.pack_start(nxt, False, False, 0)

    def _dim(self, text):
        l = Gtk.Label(label=text)
        l.set_xalign(0.0)
        return l

    def _on_mode(self, btn, mode):
        if not btn.get_active():
            # keep one always armed -- an unset mode would make the intent buttons ambiguous
            if self.mode == mode:
                btn.set_active(True)
            return
        self.mode = mode
        for m, b in self.mode_btns.items():
            if m != mode and b.get_active():
                b.set_active(False)
        try:
            self.refresh(self.owner.agent, self.owner._read_last())
        except Exception:
            pass          # a status line must never be able to take the pill down

    def refresh(self, agent, last):
        vis = "" if agent.get("vision") else "   · no vision, sends OCR text"
        ts, who, status = (last + ("", "", ""))[:3]
        tail = f"\nlast: {ts} {who} {status}" if ts else ""
        arm = f"   ·  will grab: {self.mode}"
        self.who.set_markup(
            f"<small><b>{GLib.markup_escape_text(agent['label'])}</b>  "
            f"{GLib.markup_escape_text(agent['model'])}{GLib.markup_escape_text(vis)}"
            f"{GLib.markup_escape_text(arm)}"
            f"{GLib.markup_escape_text(tail)}</small>")


class AskPill(Notch):                                       # noqa: F821 - injected by notch.py
    ANCHOR        = "frac"
    # Tunable, because the system pill is CONTENT-sized and its real width is not knowable from
    # here. 0.38 put this pill on top of it. Chris can nudge without a redeploy.
    ANCHOR_FRAC   = float(os.environ.get("ASKPILL_FRAC", "0.30"))
    BUTTONS       = False
    NEEDS_SENSORS = False
    NEEDS_GPU     = False
    MIN_PILL_W    = 110
    PAD_W, PAD_H  = 360, 150

    def __init__(self):
        os.makedirs(STATE_DIR, exist_ok=True)
        self.agents = _load_agents()
        self.intents, self._tips = _load_intents()
        self.idx = 0
        try:
            sel = open(SELECTED).read().strip()
            self.idx = next(i for i, a in enumerate(self.agents) if a["id"] == sel)
        except Exception:
            pass
        self.pad = None
        self.pad_open = False
        self._press = None
        self._last = ("", "", "")
        self._last_mtime = 0.0
        super().__init__()

    @property
    def agent(self):
        return self.agents[self.idx]

    # -- body: canvas underneath, pad on top (NotePill's shape) ----------------
    def build_body(self):
        self.set_accept_focus(True)          # before realise, or the entry never gets keys
        self.fixed = Gtk.Fixed()
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.fixed.put(self.area, 0, 0)
        self.area.set_size_request(self.win_w, self.win_h)
        self.add(self.fixed)
        self.pad = AskPad(self)
        self.fixed.put(self.pad, 0, PILL_H)   # noqa: F821
        self.pad.connect("size-allocate", self._pad_reshaped)
        self.pad.set_no_show_all(True)        # the window show_all()s; the pad opens on click
        # The base connects ONLY button-press (notch.py:549). Without this the release
        # handler never fires and the click-vs-drag test silently does nothing.
        self.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("button-release-event", self.on_release)
        self.connect("key-press-event", self._on_key)

    def pad_rect_now(self):
        """🔴 MEASURE THE PAD, DO NOT HARDCODE IT.

        PAD_W/PAD_H were fixed at 360x150 when the pad was one entry and four buttons in a
        single row. The mode/intent split added a second row and a fifth button, so GTK drew a
        pad bigger than the shape -- and a control that is visible but not clickable is the
        same class of defect as the frozen-desktop incident, just quieter. The size now comes
        from what GTK actually wants to draw.

        The constants survive as a FLOOR, not a ceiling: the pad never shrinks below the size
        Chris is used to aiming at.

        Clamped to the window because the base fixes the window size deliberately ("a window
        that resizes under an anchored pill drags the pill with it") -- so the pad may claim
        any of the 760x229 below the pill, and never a pixel more.
        """
        if not self.pad_open:
            return (0, 0, 0, 0)
        nat = self.pad.get_preferred_size()[1]
        w = min(max(self.PAD_W, nat.width),  self.win_w - 16)
        h = min(max(self.PAD_H, nat.height), self.win_h - PILL_H - 4)  # noqa: F821
        x = max(0, min(self.pill_x, self.win_w - w))
        return (x, PILL_H, w, h)                                       # noqa: F821

    def apply_input_shape(self):
        """🔴 THE PAD MUST BE IN THE SHAPE OR IT CANNOT BE CLICKED.

        A pill window is far larger than what it draws; the input shape is what makes the rest
        click-through. The base shapes the CAPSULE only, so an embedded pad would be invisible
        to the pointer -- you would see buttons and nothing would happen. NotePill unions its
        pad rect for exactly this reason and this mirrors it.
        """
        gdkwin = self.get_window()
        if not gdkwin:
            return
        region = cairo.Region(cairo.RectangleInt(self.pill_x, 0, self.pill_w, PILL_H))  # noqa: F821
        if self.pad_open:
            x, y, w, h = self.pad_rect_now()
            region.union(cairo.RectangleInt(x, y, w, h))
        gdkwin.input_shape_combine_region(region, 0, 0)

    def _pad_reshaped(self, _w, _alloc):
        if self.pad_open:
            self._place_pad()
            self.apply_input_shape()

    def _place_pad(self):
        x, y, w, h = self.pad_rect_now()
        if self.pad_open:
            self.pad.set_size_request(w, h)
            self.fixed.move(self.pad, x, y)

    # -- state ---------------------------------------------------------------
    def _read_last(self):
        try:
            st = os.stat(LAST)
            if st.st_mtime != self._last_mtime:
                self._last_mtime = st.st_mtime
                self._last = tuple(open(LAST).read().strip().split("\t"))[:3]
        except Exception:
            pass
        return self._last

    def lease_state(self):
        return ("idle", _hex_rgb(self.agent["color"]), "")

    def pill_parts(self):
        parts = [self.agent["label"].upper()]
        _, _, status = (self._read_last() + ("", "", ""))[:3]
        if status == "refused":
            parts.append("REFUSED")
        return parts

    def panel_rows(self, kind, dot, label):
        rows = [(("● " if i == self.idx else "  ") + a["label"],
                 a["model"] if a.get("vision") else a["model"] + "   (text only)",
                 _hex_rgb(a["color"]) if i == self.idx else DIM)      # noqa: F821
                for i, a in enumerate(self.agents)]
        rows.append(("drop", self.agent["drop"], DIM))                # noqa: F821
        ts, who, status = (self._read_last() + ("", "", ""))[:3]
        rows.append(("last", f"{ts}  {who}  {status}" if ts else "nothing sent yet",
                     OK_GREEN if status == "ok" else                  # noqa: F821
                     DOT_INPUT if status == "refused" else DIM))      # noqa: F821
        return rows

    # -- pad ------------------------------------------------------------------
    def open_pad(self):
        self.pad_open = True
        self.pad.refresh(self.agent, self._read_last())
        # no_show_all keeps the window-wide show_all() from revealing the pad at startup, but
        # it would gag THIS show_all() too -- lift it here or the pad can never open at all.
        self.pad.set_no_show_all(False)
        self.pad.show_all()
        self._place_pad()
        self.apply_input_shape()
        self.present()
        self.pad.entry.grab_focus()

    def close_pad(self):
        self.pad_open = False
        self.pad.hide()
        self.apply_input_shape()
        self.queue_draw()

    def cycle_agent(self):
        self.idx = (self.idx + 1) % len(self.agents)
        try:
            open(SELECTED, "w").write(self.agent["id"])
        except Exception:
            pass
        if self.pad_open:
            self.pad.refresh(self.agent, self._read_last())
        self.queue_draw()
        self.apply_input_shape()

    # -- click, with drag rejected -------------------------------------------
    def on_click(self, w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        # 🔴 Swallow button 3. The base turns it into Gtk.main_quit() and Chris has already
        # lost every panel that way once.
        if ev.button == 3:
            self._press = None
            self.open_pad() if not self.pad_open else self.close_pad()
            return True
        if ev.button == 1:
            self._press = (ev.x, ev.y, time.time())
        return True

    def on_release(self, w, ev):
        p, self._press = self._press, None
        if p is None or ev.button != 1:
            return True
        if abs(ev.x - p[0]) > DRAG_SLOP or abs(ev.y - p[1]) > DRAG_SLOP:
            return True                      # a drag, not a click -- do nothing
        on_dot = (ev.y <= PILL_H and self.pill_x <= ev.x <= self.pill_x + 40)  # noqa: F821
        if on_dot:
            self.cycle_agent()
        elif ev.y <= PILL_H:
            self.open_pad() if not self.pad_open else self.close_pad()
        return True

    def _on_key(self, _w, ev):
        if Gdk.keyval_name(ev.keyval) == "Escape" and self.pad_open:
            self.close_pad()
            return True
        return False

    # -- send: NEVER blocks the main loop ------------------------------------
    def intent_tip(self, iid):
        return self._tips.get(iid, "")

    def send_intent(self, intent, capture_mode):
        """Fire ONE intent, grabbing in whatever mode the pad has armed.

        intent=None is Enter with something typed: no preset, just the question. The armed
        mode always wins over the intent's registry default -- the pad SHOWS which grab is
        armed, and a button that silently grabs something other than what is displayed is the
        same welded-together surprise this split exists to remove.
        """
        mode = self.pad.mode if self.pad else capture_mode
        text = self.pad.entry.get_text().strip() if self.pad else ""
        argv = [ASK_PICK, intent or "-", mode]
        if text:
            argv += ["--", text]
        try:
            pid = GLib.spawn_async(argv, flags=GLib.SpawnFlags.DO_NOT_REAP_CHILD)[0]
        except Exception:
            return
        # 🔴 DO_NOT_REAP_CHILD IS A PROMISE THAT *WE* WILL REAP. Nothing did: there was
        # no child_watch_add and no spawn_close_pid anywhere in the panel, so every ASK
        # send left a <defunct> entry parented to the notch for the life of the process.
        # Measured 2026-09-07 by driving the real pad four times: 0 -> 4 zombies, all
        # state Z. The flag itself is correct and stays -- reaping inside GLib's own
        # child watch is what keeps send_intent non-blocking, which is the whole point
        # of spawning instead of calling. The watch fires on exit, reaps, and releases
        # the pid; the callback deliberately ignores the exit status, because ask-pick
        # reports its own outcome through ~/.askbar/last and a second opinion here would
        # be a second source of truth.
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid,
                             lambda p, _status: GLib.spawn_close_pid(p))
        if self.pad:
            self.pad.entry.set_text("")
        self.close_pad()

    def tick(self):
        super().tick()
        if self.pad_open:
            self.pad.refresh(self.agent, self._read_last())
