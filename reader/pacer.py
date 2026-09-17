#!/usr/bin/env python3
"""
speedreader - the PACER.

The point of this is NOT to replace reading. The audio speaks the compressed
structure track; this shows the FULL text and lights up the region currently
being spoken. Ear gets the index, eye gets the detail.

Everything is dimmed except the live span, which is what turns it from a
document into a pacer - the eye stops hunting for its place.

The highlight is delayed by the real A2DP transport delay (BlueZ reports it,
measured 320 ms on Ray-Ban Meta glasses). Without that the light runs ahead of the
sound and the whole effect inverts.
"""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango
import os, json

# Palette defaults. Overridable per-key from the config (keys below) or, for
# the live Test preview, from the SR_PREVIEW env var (same keys as JSON).
PALETTE = {
    "win_bg":       "#141417",   # window background
    "win_text":     "#5c6068",   # dimmed (not-yet-read) text
    "win_live":     "#f2f4f8",   # the sentence being read
    "win_sentence": "#2b3040",   # highlight behind the current sentence
    "win_word":     "#5a6fb5",   # the word cursor
}

def load_palette():
    pal = dict(PALETTE)
    env = os.environ.get("SR_PREVIEW")
    if env:                                    # live preview from the settings dialog
        try: pal.update({k: v for k, v in json.loads(env).items() if k in PALETTE})
        except Exception: pass
        return pal
    try:                                       # else the saved config
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "reader", os.path.join(os.path.dirname(os.path.abspath(__file__)), "reader.py"))
        R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
        cfg = R.load_config()
        pal.update({k: cfg[k] for k in PALETTE if k in cfg})
    except Exception:
        pass
    return pal


def bt_delay_ms(default=0) -> int:
    """Live A2DP transport delay. BlueZ reports it in 1/10 ms."""
    try:
        import dbus
        bus = dbus.SystemBus()
        mgr = dbus.Interface(bus.get_object("org.bluez", "/"),
                             "org.freedesktop.DBus.ObjectManager")
        # The transport sits "idle" whenever nothing is playing, and this is
        # called BEFORE the first word. Filtering on State=="active" returned
        # 0 with no error, which silently disabled sync - prefer active, but
        # accept any transport that reports a delay.
        best = None
        for _path, ifaces in mgr.GetManagedObjects().items():
            t = ifaces.get("org.bluez.MediaTransport1")
            if not t or "Delay" not in t:
                continue
            d = int(t.get("Delay", 0)) // 10
            if not (0 < d <= 1500):
                continue
            if str(t.get("State", "")) == "active":
                return d
            best = d if best is None else max(best, d)
        if best is not None:
            return best
    except Exception:
        pass
    return default


class Pacer(Gtk.Window):
    def __init__(self, text: str, on_close=None, delay_ms=None, header=""):
        super().__init__(title="SpeedReader")
        self.on_close = on_close
        self.delay    = bt_delay_ms() if delay_ms is None else delay_ms
        self.set_default_size(940, 720)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)

        self.pal = load_palette()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        self.hdr = Gtk.Label(xalign=0)
        self.hdr.set_markup(
            f"<span foreground='{self.pal['win_text']}' size='small'>  {header}   "
            f"sync +{self.delay} ms   ·   Esc to stop</span>")
        box.pack_start(self.hdr, False, False, 8)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(sw, True, True, 0)

        self.tv = Gtk.TextView()
        self.tv.set_editable(False)
        self.tv.set_cursor_visible(False)
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.tv.set_left_margin(56); self.tv.set_right_margin(56)
        self.tv.set_top_margin(28);  self.tv.set_bottom_margin(360)
        self.tv.set_pixels_above_lines(7); self.tv.set_pixels_below_lines(7)
        self.tv.set_pixels_inside_wrap(6)
        sw.add(self.tv)

        self.buf = self.tv.get_buffer()
        self.buf.set_text(text)
        self.dim = self.buf.create_tag("dim", foreground=self.pal["win_text"])
        self.buf.apply_tag(self.dim, self.buf.get_start_iter(), self.buf.get_end_iter())
        kinds = ("heading", "warn", "code", "bullet", "bold", "lead", "table")
        self.hot = {k: self.buf.create_tag(
            f"hot_{k}", foreground=self.pal["win_live"],
            background=self.pal["win_sentence"], weight=Pango.Weight.SEMIBOLD)
            for k in kinds}
        self._live = None
        self._word = None
        # The word cursor sits ON TOP of the line highlight: line = where you
        # are, word = exactly where the voice is. Lose your place, look for the
        # bright one.
        self.hotword = self.buf.create_tag("hotword", foreground="#ffffff",
                                           background=self.pal["win_word"],
                                           underline=Pango.Underline.SINGLE,
                                           weight=Pango.Weight.BOLD)
        self._style_markdown(text)

        css = Gtk.CssProvider()
        css.load_from_data((
            f"window,textview{{background:{self.pal['win_bg']};}}"
            f"textview text{{background:{self.pal['win_bg']};}}"
            # GTK3 CSS has NO line-height property - it rejects the whole
            # stylesheet, not just that line. Line spacing is set on the
            # TextView with pixels_above/below_lines instead.
            "textview{font-family:'Inter','Cantarell','DejaVu Sans',sans-serif;"
            "font-size:16px;}").encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.connect("key-press-event", self._key)
        self.connect("destroy", lambda *_: self._quit())

    # ------------------------------------------------------------------ ---
    def _style_markdown(self, text):
        """Render the markup instead of reading it aloud to your eyes.

        The markers are hidden with an INVISIBLE tag rather than deleted, so
        every source offset the extractor produced still lands on the right
        character. Deleting them would have meant maintaining a source->display
        offset map, which is a bug factory.
        """
        import re as _re
        b = self.buf
        inv  = b.create_tag("inv",  invisible=True)
        bold = b.create_tag("bold", weight=Pango.Weight.BOLD)
        head = b.create_tag("head", weight=Pango.Weight.BOLD, scale=1.35,
                            pixels_above_lines=18, pixels_below_lines=6)
        mono = b.create_tag("mono", family="monospace", scale=0.94)

        def tag(t, a, c):
            if 0 <= a < c <= b.get_char_count():
                b.apply_tag(t, b.get_iter_at_offset(a), b.get_iter_at_offset(c))

        for m in _re.finditer(r'^(#{1,6})\s+(.+)$', text, _re.M):
            tag(inv, m.start(1), m.start(2))
            tag(head, m.start(2), m.end(2))
        for m in _re.finditer(r'```[^\n]*\n(.*?)```', text, _re.S):
            tag(inv, m.start(), m.start(1))
            tag(mono, m.start(1), m.end(1))
            tag(inv, m.end(1), m.end())
        for m in _re.finditer(r'\*\*(.+?)\*\*', text):
            tag(inv, m.start(), m.start(1)); tag(inv, m.end(1), m.end())
            tag(bold, m.start(1), m.end(1))
        for m in _re.finditer(r'`([^`\n]+)`', text):
            tag(inv, m.start(), m.start(1)); tag(inv, m.end(1), m.end())
            tag(mono, m.start(1), m.end(1))
        # single-asterisk / underscore italics - the markers, not the words
        ital = b.create_tag("ital", style=Pango.Style.ITALIC)
        for m in _re.finditer(r'(?<![*\w])\*(?!\*)([^*\n]+?)\*(?!\*)', text):
            tag(inv, m.start(), m.start(1)); tag(inv, m.end(1), m.end())
            tag(ital, m.start(1), m.end(1))
        # a markdown table's |---|---| separator row is layout, not content
        for m in _re.finditer(r'^\|[\s:|-]+\|\s*$', text, _re.M):
            tag(inv, m.start(), m.end())
        for m in _re.finditer(r'\[([^\]]+)\]\(([^)]*)\)', text):
            tag(inv, m.start(), m.start(1)); tag(inv, m.end(1), m.end())

    def schedule(self, kind, _text, a, b):
        """Called from the speaker thread the moment a chunk starts speaking.
        The listener does not hear it for `delay` ms, so wait that long."""
        GLib.timeout_add(self.delay, self._light, kind, a, b)

    def _light(self, kind, a, b):
        if self._live:
            self.buf.remove_tag(self._live[0],
                                self.buf.get_iter_at_offset(self._live[1]),
                                self.buf.get_iter_at_offset(self._live[2]))
        n = self.buf.get_char_count()
        a, b = max(0, min(a, n)), max(0, min(b, n))
        if a >= b:
            return False
        tag = self.hot.get(kind, self.hot["lead"])
        ia, ib = self.buf.get_iter_at_offset(a), self.buf.get_iter_at_offset(b)
        self.buf.apply_tag(tag, ia, ib)
        self._live = (tag, a, b)
        # keep the live line ~a third down, not jammed at the bottom edge
        self.tv.scroll_to_iter(ia, 0.0, True, 0.0, 0.34)
        return False

    def word(self, a, b):
        """Speaker thread -> the moment a word's index mark fires."""
        GLib.timeout_add(self.delay, self._light_word, a, b)

    def _light_word(self, a, b):
        if self._word:
            self.buf.remove_tag(self.hotword,
                                self.buf.get_iter_at_offset(self._word[0]),
                                self.buf.get_iter_at_offset(self._word[1]))
        n = self.buf.get_char_count()
        a, b = max(0, min(a, n)), max(0, min(b, n))
        if a < b:
            self.buf.apply_tag(self.hotword, self.buf.get_iter_at_offset(a),
                               self.buf.get_iter_at_offset(b))
            self._word = (a, b)
        return False

    def finish(self):
        GLib.timeout_add(self.delay + 700, self._quit)

    def _key(self, _w, ev):
        if ev.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self._quit()
        return False

    def _quit(self, *_):
        if self.on_close:
            cb, self.on_close = self.on_close, None
            cb()
        try: Gtk.main_quit()
        except Exception: pass
        return False


if __name__ == "__main__":
    import sys, re, itertools
    if "--preview" in sys.argv:
        SAMPLE = ("## SpeedReader preview\n\n"
                  "This is what the follow-along window looks like. Everything is "
                  "dimmed except the **sentence being read**, and a bright cursor "
                  "marks the exact word as it is spoken.\n\n"
                  "- The window colour, the text, the sentence highlight and the "
                  "word cursor are all yours to set.\n"
                  "- Pick colours in the settings window, then press Test.\n\n"
                  "Press Escape to close this preview.")
        win = Pacer(SAMPLE, header="preview", delay_ms=0)
        spans, off = [], 0
        for para in SAMPLE.split("\n"):
            if para.strip() and not para.startswith("|"):
                a = SAMPLE.index(para, off)
                spans.append((a, a + len(para))); off = a + len(para)
        cyc = itertools.cycle(spans)
        def tick():
            a, b = next(cyc)
            win._light("lead", a, b)
            for i, m in enumerate(re.finditer(r"\S+", SAMPLE[a:b])):
                wa, wb = a + m.start(), a + m.end()
                GLib.timeout_add(140 * i,
                                 lambda wa=wa, wb=wb: (win._light_word(wa, wb), False)[1])
            return True
        tick()
        GLib.timeout_add(2800, tick)
        win.show_all()
        Gtk.main()
