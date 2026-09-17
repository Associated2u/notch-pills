#!/usr/bin/env python3
"""
speedreader - SETTINGS window.

Right-click the reader button and this opens. Every control writes straight
to ~/.config/mrog/reader.json, which is the single source of truth that the
button, the CLI and the voice lab all read - so a change here is live for the
very next read, no restart.

Runs as its own process so that nothing in here can take the pill down.
"""
import os, sys, subprocess, importlib.util
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("reader", os.path.join(HERE, "reader.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)

US = "English (America)"
VOICES = [                      # the shortlist the author actually auditioned, winners first
    f"{US}+klatt", f"{US}+Alex", f"{US}+Storm",
    f"{US}", "English (Great Britain)",
    f"{US}+klatt2", f"{US}+klatt3", f"{US}+klatt4", f"{US}+klatt5", f"{US}+klatt6",
    f"{US}+Andy", f"{US}+Michael", f"{US}+Max", f"{US}+Alicia", f"{US}+Gene2",
    f"{US}+Robosoft", f"{US}+Robosoft3", f"{US}+Denis", f"{US}+norbert",
    f"{US}+Tweaky", f"{US}+anikaRobot", f"{US}+whisper",
]
SAMPLE = ("The reader now speaks every word, and the follow-along window "
          "lights each one as it is said.")

def _hex(rgba):
    return "#%02x%02x%02x" % (round(rgba.red * 255), round(rgba.green * 255),
                              round(rgba.blue * 255))

def wpm(rate):
    """Linear fit to klatt as MEASURED on 2026-09-04: rate 20->267, 40->329,
    60->395, 80->448, 100->506. Slope 3.0 wpm per rate unit."""
    return int(207 + rate * 3.0)


class Settings(Gtk.Window):
    def __init__(self):
        super().__init__(title="SpeedReader settings")
        self.set_default_size(520, -1)
        self.set_position(Gtk.WindowPosition.MOUSE)
        self.set_keep_above(True)
        self.set_border_width(14)
        self.cfg = R.load_config()
        self._test = None

        grid = Gtk.Grid(column_spacing=14, row_spacing=10)
        self.add(grid)
        row = [0]
        def add(label, widget, hint=None):
            l = Gtk.Label(label=label, xalign=1.0)
            l.get_style_context().add_class("dim-label")
            grid.attach(l, 0, row[0], 1, 1)
            grid.attach(widget, 1, row[0], 2, 1)
            if hint:
                h = Gtk.Label(xalign=0); h.set_markup(f"<small>{hint}</small>")
                h.get_style_context().add_class("dim-label")
                row[0] += 1; grid.attach(h, 1, row[0], 2, 1)
            row[0] += 1
            return widget

        # ---- voice ---------------------------------------------------------
        self.voice = Gtk.ComboBoxText.new_with_entry()
        for v in VOICES: self.voice.append_text(v)
        self.voice.get_child().set_text(self.cfg["voice"])
        vb = Gtk.Box(spacing=6); vb.pack_start(self.voice, True, True, 0)
        t = Gtk.Button(label="Test"); t.connect("clicked", self.on_test)
        vb.pack_start(t, False, False, 0)
        add("Voice", vb, "klatt / Alex / Storm were the three that stayed clear at speed")

        # ---- rate / pitch --------------------------------------------------
        self.rate = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -100, 100, 1)
        self.rate.set_value(self.cfg["rate"]); self.rate.set_hexpand(True)
        self.rate.connect("value-changed", lambda s: self.rate_hint.set_markup(
            f"<small>≈ {wpm(int(s.get_value()))} words per minute</small>"))
        add("Rate", self.rate)
        self.rate_hint = Gtk.Label(xalign=0); self.rate_hint.get_style_context().add_class("dim-label")
        self.rate_hint.set_markup(f"<small>≈ {wpm(self.cfg['rate'])} words per minute</small>")
        grid.attach(self.rate_hint, 1, row[0], 2, 1); row[0] += 1

        pb = Gtk.Box(spacing=8)
        for name in ("easy", "medium", "fast", "superfast"):
            label = "Super fast" if name == "superfast" else name.capitalize()
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda _w, n=name: self.rate.set_value(R.PRESETS[n]))
            pb.pack_start(btn, False, False, 0)
        add("Presets", pb, "one-tap speed - sets the rate above")

        self.pitch = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -100, 100, 1)
        self.pitch.set_value(self.cfg["pitch"])
        add("Pitch", self.pitch)

        # ---- style ---------------------------------------------------------
        self.style = {}
        sb = Gtk.Box(spacing=10); first = None
        for name, blurb in (("verbatim", "every word"), ("skim", "2x"),
                            ("structure", "2.4x"), ("gist", "10x")):
            b = Gtk.RadioButton.new_with_label_from_widget(first, f"{name}  ({blurb})")
            first = first or b
            b.set_active(self.cfg["style"] == name)
            self.style[name] = b; sb.pack_start(b, False, False, 0)
        add("Reads", sb, "only <b>verbatim</b> can drive the follow-along window - a skimmed voice leaves the eye nothing to follow")

        # ---- numbers -------------------------------------------------------
        self.numbers = {}
        nb = Gtk.Box(spacing=10); nf = None
        for name, blurb in (("skip", "skip unimportant"), ("normal", "read all"),
                            ("digits", "digit by digit")):
            b = Gtk.RadioButton.new_with_label_from_widget(nf, f"{name} ({blurb})")
            nf = nf or b
            b.set_active(self.cfg.get("numbers", "skip") == name)
            self.numbers[name] = b; nb.pack_start(b, False, False, 0)
        add("Numbers", nb, "IDs, versions, timestamps, hashes - kept, dropped, or read as digits; currency, %, years and small counts are always read")

        # A reminder of the fixed click model - not configurable, by request.
        add("Clicks", Gtk.Label(
            label="left = read aloud     right = read-along window     middle / hold = these settings",
            xalign=0), None)

        # ---- toggles -------------------------------------------------------
        tb = Gtk.Box(spacing=16)
        self.redact  = Gtk.CheckButton(label="Redact secrets");  self.redact.set_active(self.cfg.get("redact", True))
        self.earcons = Gtk.CheckButton(label="Earcons");         self.earcons.set_active(self.cfg.get("earcons", True))
        self.code    = Gtk.CheckButton(label="Read code blocks out"); self.code.set_active(self.cfg.get("code") == "speak")
        for w in (self.redact, self.earcons, self.code): tb.pack_start(w, False, False, 0)
        add("", tb)

        # ---- colours -------------------------------------------------------
        self.colors = {}
        cb = Gtk.Box(spacing=6)
        for key, tip in (("win_bg", "window"), ("win_text", "text"),
                         ("win_sentence", "sentence"), ("win_word", "word"),
                         ("win_live", "read text")):
            rgba = Gdk.RGBA(); rgba.parse(self.cfg.get(key, R.DEFAULTS[key]))
            btn = Gtk.ColorButton.new_with_rgba(rgba)
            btn.set_tooltip_text(tip)
            self.colors[key] = btn
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            lbl = Gtk.Label(); lbl.set_markup(f"<small>{tip}</small>")
            lbl.get_style_context().add_class("dim-label")
            box.pack_start(btn, False, False, 0); box.pack_start(lbl, False, False, 0)
            cb.pack_start(box, False, False, 0)
        tst = Gtk.Button(label="Test"); tst.connect("clicked", self.on_test_colours)
        cb.pack_start(tst, False, False, 8)
        add("Window colours", cb, "the follow-along window")

        # ---- buttons -------------------------------------------------------
        bb = Gtk.Box(spacing=8); bb.set_halign(Gtk.Align.END)
        traypid = os.path.expanduser("~/.local/state/mrog-reader/tray.pid")
        try:
            os.kill(int(open(traypid).read()), 0); tray_alive = True
        except Exception:
            tray_alive = False
        if tray_alive:
            q = Gtk.Button(label="Quit tray")
            q.connect("clicked", self._quit_tray)
            bb.pack_start(q, False, False, 0)
        c = Gtk.Button(label="Cancel"); c.connect("clicked", lambda *_: Gtk.main_quit())
        s = Gtk.Button(label="Save");   s.connect("clicked", self.on_save)
        s.get_style_context().add_class("suggested-action")
        bb.pack_start(c, False, False, 0); bb.pack_start(s, False, False, 0)
        grid.attach(bb, 0, row[0], 3, 1)

        self.connect("destroy", lambda *_: Gtk.main_quit())
        self.connect("key-press-event", lambda w, e: Gtk.main_quit() if e.keyval == Gdk.KEY_Escape else None)

    # ------------------------------------------------------------------ ---
    def values(self):
        return dict(
            voice=self.voice.get_child().get_text().strip() or R.DEFAULTS["voice"],
            rate=int(self.rate.get_value()), pitch=int(self.pitch.get_value()),
            style=next(k for k, b in self.style.items() if b.get_active()),
            redact=self.redact.get_active(), earcons=self.earcons.get_active(),
            code="speak" if self.code.get_active() else "describe",
            numbers=next(k for k, b in self.numbers.items() if b.get_active()),
            **{k: _hex(btn.get_rgba()) for k, btn in self.colors.items()})

    def on_test_colours(self, _b):
        import json
        cols = {k: _hex(btn.get_rgba()) for k, btn in self.colors.items()}
        env = dict(os.environ, SR_PREVIEW=json.dumps(cols))
        subprocess.Popen([sys.executable, os.path.join(HERE, "pacer.py"), "--preview"],
                         env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_test(self, _b):
        v = self.values()
        if self._test and self._test.poll() is None:
            self._test.terminate()
        self._test = subprocess.Popen(
            ["spd-say", "-o", "espeak-ng", "-y", v["voice"],
             "-r", str(v["rate"]), "-p", str(v["pitch"]), SAMPLE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _quit_tray(self, _b):
        import signal
        try:
            os.kill(int(open(os.path.expanduser(
                "~/.local/state/mrog-reader/tray.pid")).read()), signal.SIGTERM)
        except Exception:
            pass
        Gtk.main_quit()

    def on_save(self, _b):
        cfg = R.save_config(**self.values())
        print(f"saved: {cfg}", file=sys.stderr)
        Gtk.main_quit()


if __name__ == "__main__":
    w = Settings(); w.show_all(); Gtk.main()
