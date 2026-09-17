#!/usr/bin/env python3
"""
READER button for the mrog notch pill.                        SID: LINUX-E3X

Click once, then EITHER:
    click a window          -> reads that whole window
    highlight some words    -> reads exactly those words
Highlight always wins, and a held mouse button suppresses the window timer so
that a slow drag is never cut short by it.

Click again at any point to cancel or to stop talking.
"""
import os, signal, subprocess, threading, time, math

READER_W = 20
READER   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reader.py")
LOG      = os.path.expanduser("~/.local/state/mrog-reader/last.log")
AMBER    = (0.95, 0.72, 0.25)

WIN_SETTLE   = 1.6      # s a new window must sit still before we read it
ARM_TIMEOUT  = 25.0     # s before an unused arm gives up
POLL         = 0.10

try:
    from Xlib import display as _xdisplay
    _DPY = _xdisplay.Display()
    _ROOT = _DPY.screen().root
except Exception:
    _DPY = _ROOT = None

BUTTON1_MASK = 0x100


class ReaderButton:
    def __init__(self, style=None, rate=None):
        self.state = "idle"                  # idle | armed | reading
        self.proc  = None
        # NO defaults here. ~/.config/mrog/reader.json is the single source of
        # truth and reader.py reads it. The first cut kept its own fallbacks
        # and passed them as explicit flags, so the button silently overrode
        # every setting the voice lab wrote - style and rate both.
        self.style = style or os.environ.get("MROG_READER_STYLE") or None
        self.rate  = rate  or os.environ.get("MROG_READER_RATE")  or None
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        # X11's PRIMARY keeps whatever was last highlighted - possibly hours
        # ago, in another app. Without remembering what we have already acted
        # on, the "you already highlighted something" shortcut fires on EVERY
        # click and the arm path can never be reached. Whatever is selected at
        # startup counts as already seen.
        self._seen_sel = self._selection()
        self._pacer = "off"          # set per click: left = off, right = on
        self.paused = False

    # ------------------------------------------------------------ probes ---
    @staticmethod
    def _selection() -> str:
        try:
            return subprocess.run(["xclip", "-o", "-selection", "primary"],
                                  capture_output=True, text=True, timeout=1).stdout
        except Exception:
            return ""

    @staticmethod
    def _active_window() -> str:
        try:
            return subprocess.run(["xdotool", "getactivewindow"],
                                  capture_output=True, text=True, timeout=1).stdout.strip()
        except Exception:
            return ""

    @staticmethod
    def _win_class(wid: str) -> str:
        try:
            out = subprocess.run(["xprop", "-id", wid, "WM_CLASS"],
                                 capture_output=True, text=True, timeout=1).stdout
            return out.split("=", 1)[1].strip().lower() if "=" in out else ""
        except Exception:
            return ""

    # Pointing at the Claude app and OCR-ing its pixels would be daft - the
    # transcript is on disk as clean markdown. 5 ms and exact, instead of
    # 800 ms and garbled.
    CLAUDE_CLASSES = ("com.anthropic.claude", "claude-desktop")

    def _read_window(self, wid: str):
        cls = self._win_class(wid)
        if any(c in cls for c in self.CLAUDE_CLASSES):
            self._spawn("claude", "--delta")
        else:
            self._spawn("window", "--window", wid)

    @staticmethod
    def _button_held() -> bool:
        """A drag in progress. PRIMARY does not update until mouse-up, so
        without this a slow highlight loses the race to the window timer."""
        if _ROOT is None:
            return False
        try:
            return bool(_ROOT.query_pointer().mask & BUTTON1_MASK)
        except Exception:
            return False

    # ------------------------------------------------------------ running ---
    def poll(self):
        if self.proc is not None and self.proc.poll() is not None:
            self.proc = None
            self.paused = False
            if self.state in ("reading", "paused"):
                self.state = "idle"
        return self.state

    def _spawn(self, *args):
        # stderr goes to a real file. The first cut sent it to DEVNULL, which
        # is why a crash in the window path looked like "the button does
        # nothing" instead of a traceback.
        try:
            log = open(LOG, "w")
        except Exception:
            log = subprocess.DEVNULL
        cmd = [READER, *args, "--pacer", self._pacer]
        if self.style: cmd += ["--style", self.style]      # env override only
        if self.rate:  cmd += ["--rate", str(self.rate)]
        self.proc = subprocess.Popen(
            cmd,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.state = "reading"

    # --------------------------------------------------------------- arm ---
    def _watch(self):
        sel0 = self._selection()
        win0 = self._active_window()
        seen_win, seen_at = None, 0.0
        deadline = time.monotonic() + ARM_TIMEOUT

        while self.state == "armed" and time.monotonic() < deadline:
            time.sleep(POLL)

            # 1. a new highlight always wins
            sel = self._selection()
            if sel.strip() and sel != sel0 and len(sel.split()) >= 2:
                self._seen_sel = sel
                self._spawn("selection")
                return

            # 2. otherwise a window that has been clicked and left alone
            if self._button_held():
                seen_win, seen_at = None, 0.0      # mid-drag, hold everything
                continue
            w = self._active_window()
            if w and w != win0:
                if w != seen_win:
                    seen_win, seen_at = w, time.monotonic()
                elif time.monotonic() - seen_at >= WIN_SETTLE:
                    self._read_window(w)
                    return
            else:
                seen_win, seen_at = None, 0.0

        if self.state == "armed":
            self.state = "idle"

    # ------------------------------------------------------------ actions ---
    def open_settings(self):
        """Own process: a crash in a dialog must never take the pill down."""
        subprocess.Popen([os.path.join(os.path.dirname(READER), "settings.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def click(self, button: int = 1, pacer=None):
        """notch.py calls click(button=ev.button).
          1 left   -> read aloud (audio only)
          3 right  -> read + follow-along window
          2 middle -> settings
        Left or right while reading stops; a second click while armed cancels.

        `pacer=` is accepted for the OLD caller (click(pacer=bool)) so a repo
        state where notch.py has not yet been updated does not crash: it maps
        to right/left. notch.py in this tree passes button=.
        """
        if pacer is not None:
            button = 3 if pacer else 1
        if button == 2:
            self.open_settings(); return
        # While a read is active: left pauses/resumes, right stops.
        if self.state in ("reading", "paused"):
            if button == 3:
                self.stop()
            else:
                self._playpause()
            return
        if self.state == "armed":
            self.state = "idle"; return          # second click cancels
        self._pacer = "on" if button == 3 else "off"
        # A FRESH highlight reads immediately; a stale one arms instead, so a
        # highlight is only ever auto-read once.
        sel = self._selection()
        if sel.strip() and sel != self._seen_sel and len(sel.split()) >= 3:
            self._seen_sel = sel
            self._spawn("selection"); return
        self.state = "armed"
        threading.Thread(target=self._watch, daemon=True).start()

    def _playpause(self):
        if self.proc is None or self.proc.poll() is not None:
            self.state = "idle"; self.paused = False; return
        try:
            os.kill(self.proc.pid, signal.SIGUSR1)
            self.paused = not self.paused
            self.state = "paused" if self.paused else "reading"
        except Exception:
            pass

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 15)
            except Exception:
                try: self.proc.terminate()
                except Exception: pass
        self.proc  = None
        self.state = "idle"

    # --------------------------------------------------------------- draw ---
    def draw(self, cr, bx, pill_h, dim, green):
        st  = self.poll()
        col = {"idle": dim, "armed": AMBER, "reading": green,
               "paused": AMBER}[st]
        cy  = pill_h / 2
        cr.set_source_rgb(*col)
        cr.set_line_width(1.4)
        cr.new_path()
        if st == "reading":
            # PAUSE bars - the button is now a pause control
            cr.rectangle(bx, cy - 5.5, 2.4, 11); cr.fill()
            cr.rectangle(bx + 4.1, cy - 5.5, 2.4, 11); cr.fill()
        elif st == "paused":
            # filled PLAY triangle - click to resume
            cr.move_to(bx, cy - 5.5); cr.line_to(bx, cy + 5.5)
            cr.line_to(bx + 6.5, cy); cr.close_path(); cr.fill()
        else:
            cr.move_to(bx, cy - 5.5); cr.line_to(bx, cy + 5.5)
            cr.line_to(bx + 6.5, cy); cr.close_path(); cr.stroke()

        if st in ("reading", "paused"):
            return                       # bars / triangle read cleanly alone
        t = time.monotonic()
        for i, r in enumerate((5.0, 8.5)):
            a = (0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 3))) if st == "armed" else 0.75
            cr.set_source_rgba(*col, a)
            cr.new_sub_path()
            cr.arc(bx + 8.0, cy, r, -0.85, 0.85)
            cr.stroke()
