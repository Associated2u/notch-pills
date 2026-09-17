#!/usr/bin/env python3
# ============================================================================
#  mrog-notch - a standalone top-centre notch for the laptop (Route B).
#
#  Deliberately NOT a Cinnamon applet. An applet is JS running inside the
#  Cinnamon process, so any stall in it freezes the whole desktop - which has
#  already happened here once (a desklet made a 51s call on Cinnamon's main
#  loop). This owns its own process and its own main loop, so the daemon +
#  state-file split that an applet would need is unnecessary: every sensor
#  below is a /proc or /sys read costing well under a millisecond.
#
#  Hard rule kept anyway: NOTHING in tick() may block. No subprocess, no
#  network, no nvidia-smi (it spawns a process AND wakes the dGPU under PRIME
#  on-demand, which costs battery). If you add a sensor that can block, put it
#  in a separate process and read its state file here.
#
#  Runs as chris. No root, ever.
# ============================================================================
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource
except Exception:          # no gir1.2-gtksource-4 -> the note pill stays off
    GtkSource = None
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import cairo
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import time

from Xlib import display as xdisplay
from Xlib import X

W, PILL_H, PANEL_H = 760, 30, 229
PANEL_W = 430       # the drop-down is fixed width and centred
RADIUS = 16
PEEK_H = 4          # invisible strip left behind when hidden, so hover can reveal it
SLIT_H = 6          # height of the drop slivers at the very top of the screen
SNAP_W = 22         # width of the camera button at the right of the pill
REC_W = 16          # width of the record button beside it

# READER button (mrog reader). Kept in its own module so this file carries
# only geometry; if the module is absent the notch runs exactly as before.
# FLEET-V26: the tree can live anywhere; MROG_ROOT names it (default ~/mrog).
MROG_ROOT = os.path.expanduser(os.environ.get("MROG_ROOT", "~/mrog"))
sys.path.insert(0, os.path.join(MROG_ROOT, "reader"))
try:
    from notch_button import ReaderButton, READER_W
except Exception:
    ReaderButton, READER_W = None, 0

# Everything these pills produce lands under ONE folder, so there is exactly
# one place to look and one thing to back up.
MROGDIR = os.path.expanduser(os.environ.get("MROG_NOTCH_HOME", "~/Documents/mrog"))
SHOTDIR = os.path.expanduser(os.environ.get("MROG_NOTCH_SHOTDIR",
                                            os.path.join(MROGDIR, "Screenshots")))
RECDIR = os.path.expanduser(os.environ.get("MROG_NOTCH_RECDIR",
                                           os.path.join(MROGDIR, "Recordings")))
NOTEDIR = os.path.expanduser(os.environ.get("MROG_NOTCH_NOTEDIR",
                                            os.path.join(MROGDIR, "Notes")))
# Ask what to do with a capture once it exists. 0 = silent, straight to disk.
ASK_AFTER_CAPTURE = os.environ.get("MROG_NOTCH_ASK", "1") != "0"
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

# Overridable so the indicator can be proven without arming a real lease.
SHELL_LEASE = os.environ.get("MROG_NOTCH_SHELL_LEASE", "/run/mrog/lease.json")
INPUT_LEASE = os.environ.get("MROG_NOTCH_INPUT_LEASE", "/run/mrog/input-lease.json")
# FLEET-CB2 2026-09-05. A MODEL-STATE dot: some external tool writes a small JSON
# file saying which model family is live (and, while a swap runs, which way it is
# going); the pill shows it as a coloured dot and a drop-down row, and a click
# launches that tool's UI through polkit. The indicator lives HERE and not on a
# launcher icon because a Cinnamon launcher icon change needs a full Cinnamon
# restart -- far too heavy for a toggle flipped often. The notch already polls.
#
# FLEET-V26: generic contract, configurable. The file may carry either
#   {"state": "LEGAL|NORMAL|SPLIT", "detail": "...", "phase": "idle|...", "target": "..."}
# or the original fleet shape {"fleet": ..., "studio": {"mode":..}, "mini": {"mode":..}}.
# LEGAL = green, NORMAL = amber, SPLIT = red, anything else = idle.
MODEL_STATE = os.environ.get("MROG_NOTCH_MODEL_STATE", "/tmp/.mrog_model_state.json")
MODEL_LABEL = os.environ.get("MROG_NOTCH_MODEL_LABEL", "Model state")
MODEL_UI = os.environ.get("MROG_NOTCH_MODEL_UI", "/usr/local/sbin/mrog-legal-ui")
DOT_LEGAL = (0.33, 0.78, 0.44)
DOT_NORMAL = (0.88, 0.63, 0.19)
DOT_SPLIT = (0.88, 0.31, 0.31)
PANIC_FILE = os.environ.get("MROG_NOTCH_PANIC", f"{RUNTIME}/mrog/input-panic")

# Get out of the way when a window claims the whole screen.
HIDE_ON_FULLSCREEN = os.environ.get("MROG_NOTCH_HIDE_FULLSCREEN", "1") != "0"
HIDE_ON_MAXIMIZED = os.environ.get("MROG_NOTCH_HIDE_MAXIMIZED", "1") != "0"

# GPU: auto | ac | force | off.
#
# Default "auto". Measured on this machine: keeping the dGPU awake costs
# 13.3 W, against a 65.7 Wh battery - about 4.9 h of runtime for two numbers
# that, while the card is idle, say nothing useful anyway. "auto" shows real
# figures whenever anything else is using the card, which is exactly when they
# matter, and costs nothing the rest of the time. Opening the drop-down also
# asks for a live reading on demand - see GpuProbe.request().
GPU_MODE = os.environ.get("MROG_NOTCH_GPU", "auto").lower()
DGPU_PCI = os.environ.get("MROG_NOTCH_DGPU", "0000:01:00.0")

BG = (0.055, 0.055, 0.075, 0.93)
FG = (0.90, 0.90, 0.94)
DIM = (0.52, 0.52, 0.58)
DOT_IDLE = (0.23, 0.23, 0.27)
DOT_SHELL = (0.88, 0.63, 0.19)
DOT_INPUT = (0.88, 0.31, 0.31)
OK_GREEN = (0.36, 0.80, 0.45)
REC_RED = (0.90, 0.26, 0.26)
ACCENT = (0.20, 0.72, 0.85)
KILL_BG = (0.62, 0.09, 0.09, 0.97)


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return default


def _find_temp_input():
    """Locate the package-temperature file once, at startup."""
    import glob
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = (_read(f"{hw}/name", "") or "").strip()
        if name in ("coretemp", "k10temp", "zenpower"):
            for lbl in sorted(glob.glob(f"{hw}/temp*_label")):
                if "Package" in (_read(lbl, "") or ""):
                    return lbl.replace("_label", "_input")
            if os.path.exists(f"{hw}/temp1_input"):
                return f"{hw}/temp1_input"
    for tz in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        if (_read(f"{tz}/type", "") or "").strip() in ("x86_pkg_temp", "acpitz"):
            return f"{tz}/temp"
    return None


def _on_ac():
    """True while a mains adapter is online. A free sysfs read."""
    import glob
    for online in glob.glob("/sys/class/power_supply/*/online"):
        if (_read(online, "") or "").strip() == "1":
            return True
    return False


def _find_battery():
    import glob
    for ps in sorted(glob.glob("/sys/class/power_supply/*")):
        if (_read(f"{ps}/type", "") or "").strip() == "Battery":
            return ps
    return None


class Sensors:
    def __init__(self):
        self.temp_path = _find_temp_input()
        self.bat_path = _find_battery()
        self._cpu_prev = self._cpu_raw()
        self._net_prev = self._net_raw()
        self._net_when = time.monotonic()
        self.cpu = 0.0
        self.mem_used = self.mem_total = 0
        self.temp = None
        self.bat_pct = None
        self.bat_status = ""
        self.bat_watts = None
        self.rx = self.tx = 0.0
        self.uptime = 0

    @staticmethod
    def _cpu_raw():
        line = (_read("/proc/stat", "") or "").split("\n", 1)[0].split()
        if len(line) < 5:
            return (0, 0)
        v = [int(x) for x in line[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        return (sum(v), idle)

    @staticmethod
    def _net_raw():
        rx = tx = 0
        for ln in (_read("/proc/net/dev", "") or "").split("\n")[2:]:
            if ":" not in ln:
                continue
            iface, rest = ln.split(":", 1)
            if iface.strip() == "lo":
                continue
            f = rest.split()
            if len(f) >= 9:
                rx += int(f[0])
                tx += int(f[8])
        return (rx, tx)

    def sample(self):
        total, idle = self._cpu_raw()
        pt, pi = self._cpu_prev
        dt, di = total - pt, idle - pi
        if dt > 0:
            self.cpu = max(0.0, min(100.0, 100.0 * (dt - di) / dt))
        self._cpu_prev = (total, idle)

        mt = ma = 0
        for ln in (_read("/proc/meminfo", "") or "").split("\n"):
            if ln.startswith("MemTotal:"):
                mt = int(ln.split()[1])
            elif ln.startswith("MemAvailable:"):
                ma = int(ln.split()[1])
                break
        self.mem_total, self.mem_used = mt, mt - ma

        if self.temp_path:
            raw = _read(self.temp_path)
            if raw and raw.strip().lstrip("-").isdigit():
                self.temp = int(raw) / 1000.0

        if self.bat_path:
            cap = _read(f"{self.bat_path}/capacity")
            self.bat_pct = int(cap) if cap and cap.strip().isdigit() else None
            self.bat_status = (_read(f"{self.bat_path}/status", "") or "").strip()
            pw = _read(f"{self.bat_path}/power_now")
            if pw and pw.strip().lstrip("-").isdigit():
                self.bat_watts = abs(int(pw)) / 1e6
            else:
                cn = _read(f"{self.bat_path}/current_now")
                vn = _read(f"{self.bat_path}/voltage_now")
                if cn and vn and cn.strip().lstrip("-").isdigit() and vn.strip().isdigit():
                    self.bat_watts = abs(int(cn)) * int(vn) / 1e12

        now = time.monotonic()
        rx, tx = self._net_raw()
        span = max(0.001, now - self._net_when)
        self.rx = (rx - self._net_prev[0]) / span
        self.tx = (tx - self._net_prev[1]) / span
        self._net_prev, self._net_when = (rx, tx), now

        up = _read("/proc/uptime", "0")
        self.uptime = int(float(up.split()[0]))


class GpuProbe:
    """dGPU memory + temperature that neither wakes a sleeping card nor keeps
    the notch fat.

    All of this is forced by measurement on this machine, 2026-09-04:
      nvmlInit_v2() from cold   1437 ms, and drags the dGPU suspended -> active
      a sample once NVML is up     0.23 ms
      re-suspend after the last NVML client exits   ~30 s
      idle graphics clients        1  (Xorg, 4 MiB) - NOT zero
      dGPU awake and idle          13.3 W, against a 65.7 Wh battery
      dGPU suspended               0 W - the card is powered down
      NVML's memory footprint      ~20 MB, and NOT returned on shutdown
    The card sits suspended ~98% of uptime under PRIME on-demand.

    So nothing here loads NVML. A short-lived helper process does that and
    streams JSON lines; when it exits, the kernel takes its ~20 MB back. This
    class only reads runtime_status, which is free, and decides when a helper
    should exist. Three things it has to get right, all found the hard way:

      * While a helper holds NVML, runtime_status stays "active" BECAUSE OF IT,
        so "stop when the card goes idle" can never fire from here. The helper
        owns that decision, using the client count against a running-minimum
        floor, and exits by itself.
      * Re-suspend takes ~30 s, far slower than any poll, so respawning the
        moment a helper exits would see "active" and latch forever. Hence
        COOLDOWN, which must exceed that 30 s.
      * The 1437 ms init must never land on the UI loop - hence the thread,
        and hence a helper rather than an in-process import.

    MROG_NOTCH_GPU: auto (default) | ac | force | off.
    """

    PERIOD = 2.0        # seconds between poll decisions
    COOLDOWN = 45.0     # must exceed the measured ~30 s re-suspend delay

    def __init__(self):
        self.power_path = f"/sys/bus/pci/devices/{DGPU_PCI}/power/runtime_status"
        # (state, used_MiB, total_MiB, temp_C) - replaced as one atomic rebind
        self.snapshot = ("off" if GPU_MODE == "off" else "asleep", 0, 0, None)
        self._proc = None
        self._forced_helper = False  # was the live helper spawned with no self-exit?
        self._cooldown_until = 0.0
        self.on_demand = False   # set while the drop-down is open
        if GPU_MODE != "off":
            threading.Thread(target=self._loop, daemon=True).start()

    def request(self, want):
        """Ask for a live reading regardless of power state - used while the
        drop-down is open, so 'show me the GPU' costs 13.3 W and ~20 MB only
        for as long as you are actually looking at it."""
        self.on_demand = bool(want)
        if want:
            self._cooldown_until = 0.0   # an explicit ask overrides the cooldown

    def _spawn(self, forced):
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "mrog-gpu-helper.py")
        if not os.path.exists(helper):
            helper = os.path.expanduser("~/.local/bin/mrog-gpu-helper")
        cmd = [sys.executable, helper, "--pci", DGPU_PCI,
               "--period", str(self.PERIOD),
               "--grace", "0" if forced else "8"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        self._forced_helper = forced

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._forced_helper = False
        self._cooldown_until = time.monotonic() + self.COOLDOWN

    def _loop(self):
        while True:
            try:
                awake = (_read(self.power_path, "") or "").strip() == "active"
                forced = (GPU_MODE == "force"
                          or (GPU_MODE == "ac" and _on_ac())
                          or self.on_demand)
                want = awake or forced

                if self._proc is not None and self._proc.poll() is not None:
                    # Helper decided the card had no user but itself and left.
                    self._proc = None
                    self._cooldown_until = time.monotonic() + self.COOLDOWN
                    self.snapshot = ("asleep", 0, 0, None)

                # A forced helper never exits by itself, and while it lives the
                # card reads "active" BECAUSE OF IT - so `want` can never fall.
                # Closing the drop-down has to stop it explicitly or it runs for
                # ever, holding 13.3 W. This is the same latch as the power
                # state, one level up.
                if self._proc is not None and self._forced_helper and not forced:
                    self._stop()
                    self.snapshot = ("asleep", 0, 0, None)
                elif not want:
                    if self._proc is not None:
                        self._stop()
                    self.snapshot = ("asleep", 0, 0, None)
                elif self._proc is None:
                    if time.monotonic() < self._cooldown_until:
                        self.snapshot = ("asleep", 0, 0, None)
                    else:
                        self.snapshot = ("waking", 0, 0, None)
                        self._spawn(forced)
                else:
                    # Drain whatever the helper has written without blocking.
                    line = None
                    while select.select([self._proc.stdout], [], [], 0)[0]:
                        chunk = self._proc.stdout.readline()
                        if not chunk:
                            break
                        line = chunk
                    if line:
                        d = json.loads(line)
                        if d.get("state") == "ok":
                            self.snapshot = ("ok", d.get("used", 0),
                                             d.get("total", 0), d.get("temp"))
                        else:
                            self.snapshot = ("error", 0, 0, None)
            except Exception:
                self._stop()
                self.snapshot = ("error", 0, 0, None)
            time.sleep(self.PERIOD)

    def line(self):
        state, used, total, temp = self.snapshot
        if state == "off":
            return None
        if state == "asleep":
            return "asleep"
        if state == "waking":
            return "waking\u2026"
        if state == "error":
            return "n/a"
        t = f"   {temp}\u00b0C" if temp is not None else ""
        return f"{used} / {total} MiB{t}"


class WindowWatch:
    """True when the focused window has claimed the whole screen.

    Its own X connection, deliberately separate from GTK's: one round trip per
    tick, no subprocess, and a dead window id can only ever cost us a False.
    """

    def __init__(self):
        self.ok = False
        try:
            self.d = xdisplay.Display()
            self.root = self.d.screen().root
            self.a_active = self.d.intern_atom("_NET_ACTIVE_WINDOW")
            self.a_state = self.d.intern_atom("_NET_WM_STATE")
            self.a_fs = self.d.intern_atom("_NET_WM_STATE_FULLSCREEN")
            self.a_mv = self.d.intern_atom("_NET_WM_STATE_MAXIMIZED_VERT")
            self.a_mh = self.d.intern_atom("_NET_WM_STATE_MAXIMIZED_HORZ")
            self.ok = True
        except Exception:
            pass

    def covered(self):
        if not self.ok:
            return False
        try:
            p = self.root.get_full_property(self.a_active, X.AnyPropertyType)
            if not p or not p.value or not p.value[0]:
                return False
            w = self.d.create_resource_object("window", p.value[0])
            sp = w.get_full_property(self.a_state, X.AnyPropertyType)
            if not sp or not sp.value:
                return False
            states = set(sp.value)
            if HIDE_ON_FULLSCREEN and self.a_fs in states:
                return True
            if HIDE_ON_MAXIMIZED and self.a_mv in states and self.a_mh in states:
                return True
            return False
        except Exception:
            return False


def read_model_mode():
    """(mode, colour, detail, phase) for the model family currently loaded.

    Never raises and never blocks: a stale or missing file reads as unknown,
    because a status chip must not be able to take the pill down.
    """
    try:
        with open(MODEL_STATE) as f:
            d = __import__("json").load(f)
    except Exception:
        # 🔴 FOUR VALUES, NOT THREE. Both callers unpack four
        # (`mode, mcol, mdetail, _mphase = read_model_mode()` in the panel rows, and
        # `_wmode, _wcol, _wdetail, _wphase` in the SystemPill draw), so returning a
        # 3-tuple here made the CALLER raise -- in on_draw, on every frame. The
        # docstring above promises "Never raises", and it was true of this function and
        # false of the pill that uses it.
        # It is not a rare path: MODEL_STATE lives in /tmp, so it is GONE after every
        # reboot until something writes it. Measured 2026-09-07 on a freshly rebooted
        # machine: 15 ValueError tracebacks in the first 6 seconds of panel life.
        # "idle" is the same default the success path uses for a missing phase key.
        return ("?", DOT_IDLE, "no reading yet", "idle")
    fleet = str(d.get("state") or d.get("fleet") or "?")
    phase = str(d.get("phase", "idle"))
    col = {"LEGAL": DOT_LEGAL, "NORMAL": DOT_NORMAL,
           "SPLIT": DOT_SPLIT}.get(fleet, DOT_IDLE)
    if d.get("detail"):
        detail = str(d["detail"])
    else:                       # the original per-host shape
        parts = [(k, (d.get(k) or {}).get("mode", "?")) for k in ("studio", "mini")
                 if isinstance(d.get(k), dict)]
        detail = " / ".join("%s %s" % kv for kv in parts) or "?"
    if phase not in ("idle", "done"):
        # A swap takes MINUTES. Saying which way it is going, while it goes,
        # is the whole reason Chris does not have to sit in the terminal.
        detail = "%s -> %s  (%s)" % (detail, d.get("target") or "?", phase)
    return (fleet, col, detail, phase)


def read_lease(path):
    """Returns (live, seconds_left, dict) - never raises, never blocks."""
    try:
        with open(path) as f:
            d = json.load(f)
        left = int(d.get("expires_at", 0) - time.time())
        return (left > 0, left, d)
    except Exception:
        return (False, 0, {})


def human_rate(bps):
    for unit, div in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if bps >= div:
            return f"{bps / div:.1f}{unit}"
    return f"{bps:.0f}"


def rounded(cr, x, y, w, h, r, top=True, bottom=True):
    cr.new_sub_path()
    if top:
        cr.arc(x + r, y + r, r, 3.14159, 4.71239)
        cr.arc(x + w - r, y + r, r, 4.71239, 6.28319)
    else:
        cr.move_to(x, y)
        cr.line_to(x + w, y)
    if bottom:
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.14159)
    else:
        cr.line_to(x + w, y + h)
        cr.line_to(x, y + h)
    cr.close_path()


class Notch(Gtk.Window):
    # Subclass hooks. FleetPill overrides these rather than duplicating any of
    # the window, shape, hide or expand plumbing below.
    ANCHOR = "center"     # "center" | "right"
    BUTTONS = True        # draw the camera / REC controls
    # A subclass that shows neither must not inherit the probes: FleetPill did,
    # and quietly ran a SECOND gpu helper that held the card awake for nothing.
    NEEDS_SENSORS = True
    NEEDS_GPU = True
    ALWAYS_HIDDEN = False
    SHOWS_KILL = False
    # FLEET-CB2 2026-09-05. The weights control belongs to ONE pill. The first
    # version drew it in the base class, so it appeared on the fleet, note and
    # workspace pills too -- four buttons for one fleet-wide action. Same
    # pattern as SHOWS_KILL directly above: the centre pill owns it.
    SHOWS_WEIGHTS = False
    PANEL_ROW_H = 21
    MIN_PILL_W = 300
    ANCHOR_FRAC = 0.5

    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.expanded = False
        self.win_left = 0
        self.win_w, self.win_h = self.window_geometry()
        self.kill = None
        self.pill_x, self.pill_w = (W - 300) // 2, 300
        self.snap_rect = (0, 0, 0, 0)
        self.snap_flash = 0.0
        self.rec_rect = (0, 0, 0, 0)
        self.rec_proc = None
        self.rec_started = 0.0
        self.rec_path = None
        self.reader = ReaderButton() if (ReaderButton and self.BUTTONS) else None
        self.reader_rect = (0, 0, 0, 0)
        self.hidden = False     # a window has claimed the screen
        self.peeking = False    # ...but the pointer is at the top edge
        self.sensors = Sensors() if self.NEEDS_SENSORS else None
        self.gpu = GpuProbe() if self.NEEDS_GPU else None
        self.watch = WindowWatch()

        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.stick()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.set_size_request(self.win_w, self.win_h)
        self.build_body()

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.ENTER_NOTIFY_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("button-press-event", self.on_click)
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("destroy", Gtk.main_quit)

        self.show_all()
        self.reposition()
        self.apply_input_shape()
        GLib.timeout_add(1000, self.tick)
        GLib.timeout_add(5000, self.reassert)

    def snap(self):
        """Immediate full-screen shot. Spawned, never waited on - this is a
        click handler, not tick(), but the UI still must not block on it."""
        os.makedirs(SHOTDIR, exist_ok=True)
        out = os.path.join(SHOTDIR, time.strftime("shot-%Y%m%d-%H%M%S.png"))
        if shutil.which("flameshot"):
            cmd = ["flameshot", "full", "-c", "-p", out]
        else:
            geo = "%dx%d" % (self.get_screen().get_width(), self.get_screen().get_height())
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "x11grab",
                   "-video_size", geo, "-i", os.environ.get("DISPLAY", ":0"),
                   "-frames:v", "1", "-y", out]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            self.snap_flash = time.monotonic()
            GLib.timeout_add(200, self._watch_capture, proc, out, "shot")
        except Exception:
            pass

    def pill_parts(self):
        s = self.sensors
        parts = [f"CPU {s.cpu:4.1f}%",
                 f"RAM {s.mem_used / 1048576:.1f}/{s.mem_total / 1048576:.1f}G"]
        if s.temp is not None:
            parts.append(f"{s.temp:.0f}\u00b0C")
        if self.gpu.snapshot[0] == "ok":
            # Only while the card is genuinely awake - "asleep" here is noise.
            _, gu, gt_mib, gtemp = self.gpu.snapshot
            seg = f"GPU {gu / 1024:.1f}/{gt_mib / 1024:.1f}G"
            if gtemp is not None:
                seg += f" {gtemp}\u00b0C"
            parts.append(seg)
        if s.bat_pct is not None:
            arrow = "+" if s.bat_status == "Charging" else ""
            parts.append(f"{arrow}{s.bat_pct}%")
        if self.rec_proc is not None and self.rec_proc.poll() is None:
            el = int(time.monotonic() - self.rec_started)
            parts.append(f"REC {el // 60}:{el % 60:02d}")
        return parts

    def panel_rows(self, kind, dot, label):
        s = self.sensors
        rows = [("CPU", f"{s.cpu:.1f}%", FG),
                ("Memory", f"{s.mem_used / 1048576:.1f} / {s.mem_total / 1048576:.1f} GiB", FG),
                ("Package temp", f"{s.temp:.0f}\u00b0C" if s.temp is not None else "n/a", FG)]
        gpu = self.gpu.line()
        if gpu is not None:
            rows.append(("dGPU", gpu,
                         DIM if gpu in ("asleep", "waking\u2026", "n/a") else FG))
        if s.bat_pct is not None:
            w = f" \u00b7 {s.bat_watts:.1f} W" if s.bat_watts else ""
            rows.append(("Battery", f"{s.bat_pct}% {s.bat_status}{w}", FG))
        rows.append(("Network", f"rx {human_rate(s.rx)}B/s   tx {human_rate(s.tx)}B/s", FG))
        rows.append(("Uptime", f"{s.uptime // 86400}d {s.uptime % 86400 // 3600}h "
                               f"{s.uptime % 3600 // 60}m", FG))
        rows.append(("Lease", label, dot if kind in ("input", "shell") else DIM))
        # FLEET-CB2: which weight family Dreamzs is answering from. NORMAL is
        # the abliterated pair and is EXPERIMENTAL as of 2026-09-05 -- amber,
        # not green, so "will not refuse" never reads as the safe state.
        mode, mcol, mdetail, _mphase = read_model_mode()
        rows.append((MODEL_LABEL, "%s  (%s)" % (mode, mdetail),
                     mcol if mode in ("LEGAL", "NORMAL", "SPLIT") else DIM))
        return rows

    def toggle_rec(self):
        """Start/stop a screen recording. NVENC on mains, VAAPI on battery -
        NVENC spins the dGPU up for 13.3 W, which is not worth it unplugged."""
        if self.rec_proc is not None:
            try:
                self.rec_proc.send_signal(signal.SIGINT)   # let ffmpeg finalise
                self.rec_proc.wait(timeout=5)
            except Exception:
                try:
                    self.rec_proc.kill()
                except Exception:
                    pass
            self.rec_proc = None
            GLib.timeout_add(400, lambda: (self.offer(self.rec_path, "rec"), False)[1])
            return

        os.makedirs(RECDIR, exist_ok=True)
        self.rec_path = os.path.join(RECDIR, time.strftime("rec-%Y%m%d-%H%M%S.mkv"))
        sc = self.get_screen()
        geo = f"{sc.get_width()}x{sc.get_height()}"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-f", "x11grab", "-framerate", "60", "-draw_mouse", "1",
               "-video_size", geo, "-i", os.environ.get("DISPLAY", ":0")]

        # System audio = the default sink's monitor. Resolved here, at click
        # time, never in tick().
        try:
            sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                  text=True, timeout=2).stdout.strip()
            if sink:
                cmd += ["-f", "pulse", "-i", f"{sink}.monitor"]
        except Exception:
            pass

        if _on_ac():
            cmd += ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq",
                    "-rc", "vbr", "-cq", "19", "-b:v", "0"]
        else:
            cmd += ["-vaapi_device", "/dev/dri/renderD128",
                    "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "22"]
        cmd += ["-c:a", "aac", "-b:a", "192k", "-y", self.rec_path]
        try:
            self.rec_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            self.rec_started = time.monotonic()
        except Exception:
            self.rec_proc = None

    def offer(self, path, kind):
        """Capture first, ask second. The file is already safely on disk before
        this opens, so Cancel can never lose the shot - the dialog only decides
        where it ENDS UP, it is not the thing that saves it."""
        if not ASK_AFTER_CAPTURE or not os.path.exists(path):
            return
        size = os.path.getsize(path) / 1048576.0
        d = Gtk.Dialog(title="Screenshot" if kind == "shot" else "Recording",
                       transient_for=None, flags=0)
        d.set_keep_above(True)
        d.set_position(Gtk.WindowPosition.CENTER)
        box = d.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)

        if kind == "shot":
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 420, 260, True)
                box.add(Gtk.Image.new_from_pixbuf(pb))
            except Exception:
                pass
        lbl = Gtk.Label(label=f"{os.path.basename(path)}   ({size:.1f} MB)")
        lbl.set_selectable(True)
        box.add(lbl)

        d.add_button("Delete", 4)
        d.add_button("Open folder", 3)
        if kind == "shot":
            d.add_button("Copy", 2)
        d.add_button("Save as\u2026", 1)
        d.add_button("Keep", 0)
        d.set_default_response(0)
        box.show_all()

        resp = d.run()
        d.destroy()

        if resp == 4:
            try:
                os.remove(path)
            except Exception:
                pass
        elif resp == 3:
            subprocess.Popen(["xdg-open", os.path.dirname(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif resp == 2 and shutil.which("xclip"):
            subprocess.Popen(["xclip", "-selection", "clipboard", "-t", "image/png",
                              "-i", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif resp == 1:
            ch = Gtk.FileChooserDialog(title="Save as", action=Gtk.FileChooserAction.SAVE)
            ch.set_keep_above(True)
            ch.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
            ch.set_current_name(os.path.basename(path))
            ch.set_do_overwrite_confirmation(True)
            if ch.run() == Gtk.ResponseType.OK:
                dest = ch.get_filename()
                try:
                    shutil.move(path, dest)
                except Exception:
                    pass
            ch.destroy()

    def _watch_capture(self, proc, path, kind):
        """Poll for the child to finish, then offer. Never blocks the loop."""
        if proc.poll() is None:
            return True
        GLib.timeout_add(150, lambda: (self.offer(path, kind), False)[1])
        return False

    def window_geometry(self):
        """Window size. Fixed for the life of the pill - a window that resizes
        under an anchored pill drags the pill with it."""
        return (W, PILL_H + PANEL_H)

    def build_body(self):
        """Default body is a bare canvas. NotePill overrides this to host a real
        editor widget on top of the same canvas."""
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.add(self.area)

    def reposition(self):
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        g = mon.get_geometry()
        if self.ANCHOR == "right":
            self.win_left = g.x + g.width - self.win_w
        elif self.ANCHOR == "frac":
            self.win_left = g.x + int(g.width * self.ANCHOR_FRAC) - self.win_w // 2
        else:
            self.win_left = g.x + (self.win_w - 0) // 2 - self.win_w // 2 + (g.width - self.win_w) // 2 - (g.width - self.win_w) // 2 + (g.width - self.win_w) // 2
            self.win_left = g.x + (g.width - self.win_w) // 2
        self.move(self.win_left, g.y)

    def pill_x_for(self, pill_w):
        """Where the pill sits INSIDE the window. For an anchored pill this must
        depend only on the monitor, never on the window size - otherwise resizing
        the window to fit a drop-down makes the pill itself jump."""
        if self.ANCHOR == "right":
            return self.win_w - pill_w - 14
        if self.ANCHOR == "frac":
            g = self._mon_geo()
            return g.x + int(g.width * self.ANCHOR_FRAC) - pill_w // 2 - self.win_left
        return (self.win_w - pill_w) // 2

    def _mon_geo(self):
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        return mon.get_geometry()

    def reassert(self):
        # Some WMs drop keep-above after a fullscreen app exits.
        self.set_keep_above(True)
        return True

    def apply_input_shape(self):
        """Clicks land only on what is actually drawn, so the transparent area
        never steals a click from the window underneath. While hidden, all that
        is left is a few pixels of hover strip to reveal it again."""
        gdkwin = self.get_window()
        if not gdkwin:
            return
        if self.hidden and not self.peeking:
            # 🔴 THE STRIP MUST FIT INSIDE THE PILL IT REVEALS.
            #
            # The strip was a hardcoded 200px. A pill narrower than that leaves a band
            # that is inside the HIDDEN shape and outside the PEEKING one, so entering
            # it fires on_enter -> peek -> reshape -> the pointer is now outside ->
            # on_leave -> un-peek -> reshape -> inside again, forever. Measured
            # 2026-09-07 on a nested :9 at Chris's real 1920px width: 31,909 enters/s,
            # 31,908 leaves/s, 63,817 reshapes/s, and draws/s = 0 -- an EVENT storm,
            # not a draw storm. It LATCHES: moving the pointer away does not clear it,
            # only a restart does, which is why 2026-09-06 burned 11h48m of CPU.
            #
            # It is not just this process. Every reshape sends ShapeNotify to the
            # window manager, so the WM burns too: metacity went 0.2% -> 100.0% and
            # the X server 0.2% -> 18.2% off this one pointer position. That is the
            # Cinnamon 63-96% seen in all three freezes -- one cause, three hot
            # processes.
            #
            # EXACTLY TWO pills were vulnerable, not four. AskPill and NotePill
            # OVERRIDE apply_input_shape and never build a strip at all, so they never
            # had a band despite being the narrowest. The real exposure was
            # WorkspacePill (130px, ALWAYS_HIDDEN so permanently armed) and FleetPill
            # (150px, armed whenever watch.covered() is true -- i.e. whenever a window
            # is maximised or fullscreen, which is how a user actually works).
            # FleetPill's band was the 50px strip immediately LEFT of the pill: moving
            # the pointer to the top-right to reveal the fleet pill landed in it.
            #
            # min(200, pill_w) makes the strip a subset of the pill in both anchor
            # modes, so entering the strip can never land the pointer outside the shape
            # that entering installs. For pill_w >= 200 the emitted rectangle is
            # unchanged -- verified by effect: SystemPill's strip read (280,0 200x4)
            # before and after.
            sw = min(200, self.pill_w)
            hx = ((self.win_w - 14 - sw) if self.ANCHOR == "right"
                  else self.pill_x + max(0, (self.pill_w - sw) // 2))
            region = cairo.Region(cairo.RectangleInt(hx, 0, sw, PEEK_H))
        else:
            region = cairo.Region(cairo.RectangleInt(self.pill_x, 0, self.pill_w, PILL_H))
            if self.expanded:
                px = ((self.pill_x + self.pill_w - PANEL_W) if self.ANCHOR == "right"
                      else (self.win_w - PANEL_W) // 2)
                region.union(cairo.RectangleInt(px, PILL_H, PANEL_W, PANEL_H - 10))
        gdkwin.input_shape_combine_region(region, 0, 0)

    def lease_state(self):
        if os.path.exists(PANIC_FILE):
            return ("panic", DOT_IDLE, "INPUT HALTED")
        live_in, left_in, d_in = read_lease(INPUT_LEASE)
        if live_in:
            scope = d_in.get("scope", "?")
            return ("input", DOT_INPUT, f"AGENT INPUT {scope} {left_in // 60}:{left_in % 60:02d}")
        live_sh, left_sh, d_sh = read_lease(SHELL_LEASE)
        if live_sh:
            scope = d_sh.get("scope", "?")
            return ("shell", DOT_SHELL, f"ROOT {scope} {left_sh // 60}:{left_sh % 60:02d}")
        return ("idle", DOT_IDLE, "no lease")

    def tick(self):
        if self.sensors is not None:
            self.sensors.sample()

        # A live lease ALWAYS wins over auto-hide. The red dot is the only
        # signal that an agent holds your keyboard, so a fullscreen window must
        # never be able to conceal it.
        kind, _, lease_label = self.lease_state()

        # The stop button rides the lease state we already compute here, so it
        # adds no polling of its own. Only the system pill owns one.
        if self.SHOWS_KILL:
            if self.kill is None:
                self.kill = KillDot()
            if kind == "input":
                self.kill.show_for(f"STOP  {lease_label.split()[-1]}")
            else:
                self.kill.hide_now()

        want_hidden = self.ALWAYS_HIDDEN or (
            self.watch.covered() and kind not in ("input", "shell"))
        if want_hidden != self.hidden:
            self.hidden = want_hidden
            if self.hidden:
                self.expanded = False
                self.peeking = False
                if self.gpu is not None:
                    self.gpu.request(False)
            self.apply_input_shape()

        self.area.queue_draw()
        return True

    def on_enter(self, _w, _ev):
        if self.hidden and not self.peeking:
            self.peeking = True
            self.apply_input_shape()
            self.area.queue_draw()
        return False

    def on_leave(self, _w, ev):
        # Ignore the pseudo-crossings GTK sends when a grab starts or ends.
        if ev.mode != Gdk.CrossingMode.NORMAL:
            return False
        if self.peeking:
            self.peeking = False
            self.expanded = False
            if self.gpu is not None:
                self.gpu.request(False)
            self.apply_input_shape()
            self.area.queue_draw()
        return False

    def on_click(self, _w, ev):
        # The reader button claims BOTH buttons, and must be tested before the
        # global right-click-quits below or a right click would kill the pill.
        dx, dy, dw, dh = self.reader_rect
        if (self.reader is not None and ev.button in (1, 2, 3)
                and dx <= ev.x <= dx + dw and dy <= ev.y <= dy + dh):
            # left = read aloud, right = follow-along window, middle = settings
            self.reader.click(button=ev.button)
            self.area.queue_draw()
            return True
        # FLEET-CB2 2026-09-05. Right-click quits the pill, and it sits
        # directly on top of the lease dot -- Chris right-clicked while trying
        # to stop a lease and lost every top panel instead. Quit still works,
        # but not over the dot, which is now a button.
        if ev.button == 3:
            _wx = getattr(self, "weights_x", None)
            if ev.y <= PILL_H and (
                    self.pill_x <= ev.x <= self.pill_x + 40
                    or (self.SHOWS_WEIGHTS and _wx is not None
                        and _wx - 6 <= ev.x <= _wx + 18)):
                return True          # swallow: these are buttons
            # 🔴 RIGHT-CLICK NO LONGER QUITS. Chris's ruling 2026-09-06.
            # It cost him every top panel once already (see FLEET-CB2 note above), and the
            # protected zones only narrowed the target rather than removing the trap. There is
            # now a deliberate way out that cannot be hit by accident -- `mrog-pills off` --
            # so a stray right-click has no business destroying the panel.
            # Set MROG_NOTCH_RMB_QUIT=1 to restore the old behaviour.
            if os.environ.get("MROG_NOTCH_RMB_QUIT", "0") == "1":
                Gtk.main_quit()
            return True
        kind, _, _ = self.lease_state()
        on_dot = (ev.y <= PILL_H and self.pill_x <= ev.x <= self.pill_x + 40)
        # The weights bar sits just right of the dot and is its own button.
        # Hit box is deliberately larger than the triangle: an 11px shape on a
        # 30px pill is a dart-throw otherwise, which is what Chris hit first.
        _wx = getattr(self, "weights_x", None)
        on_weights = (self.SHOWS_WEIGHTS and _wx is not None and ev.y <= PILL_H
                      and _wx - 6 <= ev.x <= _wx + 18)
        if ev.button == 1 and on_weights:
            # polkit authenticates, then the model UI drops straight back to
            # the user -- the swap runs with THEIR keys, never root's. The gate
            # is the point; root is not. MROG_NOTCH_MODEL_UI names the tool.
            subprocess.Popen(["pkexec", MODEL_UI],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.area.queue_draw()
            return True
        if ev.button == 1 and on_dot and kind == "input":
            # Input lease: stopping is free and needs no password, by design.
            subprocess.Popen(["mrog-input", "revoke"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.area.queue_draw()
            return True
        if ev.button == 1 and on_dot and kind == "shell":
            # FLEET-CB2 2026-09-05: THERE WAS NO BRAKE HERE. The handler only
            # revoked an INPUT lease, so with a root lease live Chris clicked
            # the dot and nothing happened. Ending a root lease needs root, so
            # this raises polkit rather than failing silently.
            # FLEET-4HY 2026-09-17: stopping root is now free too. mrog-lease-kill is
            # the delete-only NOPASSWD twin of mrog-input-kill; `sudo -n` never prompts,
            # so if the rule is not installed it fails fast and the pkexec dialog is the
            # fallback -- exactly the behaviour this click had before.
            subprocess.Popen(["bash", "-c",
                              "sudo -n /usr/local/sbin/mrog-lease-kill 2>/dev/null"
                              " || pkexec /usr/local/sbin/mrog-lease-ui revoke"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.area.queue_draw()
            return True
        # FLEET-CB2 2026-09-05, Chris ruling. The same dot that STOPS a live
        # lease now STARTS one when nothing is armed -- the button he asked
        # for, in the place the state already lives.
        #
        # pkexec raises polkit's OWN password dialog. Nothing in this file
        # draws a password box or ever sees a password: an agent-written
        # password window is indistinguishable from phishing, and
        # input-policy.conf already denies agent input to *polkit* windows --
        # so an agent can summon this and can never click through it.
        if ev.button == 1 and on_dot and kind == "idle":
            # CORRECTED same day: this sent "t1 15" to the ROOT lease. Chris
            # asked for the command in his own note --
            #   mrog-input-lease grant 10 --scope click
            # -- the INPUT lease, the RED dot. He got orange root he never
            # asked for. The dot now grants ONLY agent input; root has to be
            # asked for by name from a terminal.
            subprocess.Popen(["pkexec", "/usr/local/sbin/mrog-lease-ui",
                              "input", "10", "click"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.area.queue_draw()
            return True
        sx, sy, sw, sh = self.snap_rect
        if ev.button == 1 and sx <= ev.x <= sx + sw and sy <= ev.y <= sy + sh:
            self.snap()
            self.area.queue_draw()
            return True
        rx, ry, rw, rh = self.rec_rect
        if ev.button == 1 and rx <= ev.x <= rx + rw and ry <= ev.y <= ry + rh:
            self.toggle_rec()
            self.area.queue_draw()
            return True
        if ev.button == 1 and ev.y <= PILL_H:
            self.on_pill_click()
            self.area.queue_draw()
        return True

    def on_pill_click(self):
        """Default: toggle the drop-down. NotePill opens a real window instead."""
        self.expanded = not self.expanded
        if self.gpu is not None:
            self.gpu.request(self.expanded)
        self.apply_input_shape()

    def on_draw(self, _w, cr):
        s = self.sensors
        kind, dot, label = self.lease_state()

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # Hidden under a fullscreen or maximized window: draw nothing at all.
        # The hover strip in apply_input_shape() is what brings it back.
        if self.hidden and not self.peeking:
            return False

        # ---- the pill -------------------------------------------------
        # Sized to its content and centred, because the content is variable
        # width (GPU appears and disappears) and a fixed pill would either
        # clip it or leave a lopsided gap.
        cr.select_font_face("Ubuntu", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        text = "   ".join(self.pill_parts())

        cr.set_font_size(12)
        tw = cr.text_extents(text).width
        lease_txt = label if kind in ("input", "shell") else None
        cr.set_font_size(11)
        lw = cr.text_extents(lease_txt).width if lease_txt else 0

        DOT_W, GAP, PAD = 9, 12, 18
        btns = (GAP + SNAP_W + 10 + REC_W) if self.BUTTONS else 0
        if self.reader is not None:
            btns += 10 + READER_W
        group = DOT_W + GAP + tw + ((GAP + lw) if lease_txt else 0) + btns
        pill_w = max(self.MIN_PILL_W, int(group) + PAD * 2)
        pill_x = self.pill_x_for(pill_w)
        if (pill_x, pill_w) != (self.pill_x, self.pill_w):
            self.pill_x, self.pill_w = pill_x, pill_w
            GLib.idle_add(self.apply_input_shape)
            GLib.idle_add(lambda: (self.area.queue_draw(), False)[1])

        rounded(cr, pill_x, 0, pill_w, PILL_H, RADIUS, top=False, bottom=True)
        cr.set_source_rgba(*BG)
        cr.fill()

        cx = pill_x + PAD
        cr.new_path()
        cr.arc(cx + DOT_W / 2, PILL_H / 2, 4.5, 0, 6.28319)
        cr.set_source_rgb(*dot)
        cr.fill()
        if kind in ("input", "shell"):
            cr.new_sub_path()
            cr.arc(cx + DOT_W / 2, PILL_H / 2, 7.5, 0, 6.28319)
            cr.set_source_rgba(*dot, 0.30)
            cr.fill()

        # FLEET-CB2 2026-09-05 -- THE WEIGHTS BAR.
        # A vertical bar, not a second dot: two dots side by side read as one
        # control with a fault. Green LEGAL, amber NORMAL (abliterated is the
        # EXPERIMENTAL state, so it is never the green one), red SPLIT. While a
        # swap runs it pulses, because the swap takes minutes and a static
        # indicator cannot tell "in progress" from "finished".
        # FLEET-CB2 2026-09-05 -- THE WEIGHTS TRIANGLE.
        # Was a 4px bar and Chris could not reliably hit it. A triangle is
        # wider at the base, reads as a control rather than a status LED, and
        # points the way the swap goes. Green LEGAL, amber NORMAL (abliterated
        # is the EXPERIMENTAL state, so it never gets to be the green one), red
        # SPLIT. It pulses while a swap runs, because that takes minutes and a
        # static shape cannot tell "in progress" from "finished".
        self.weights_x = None
        _text_x = cx + DOT_W + GAP
        if self.SHOWS_WEIGHTS:
            _wmode, _wcol, _wdetail, _wphase = read_model_mode()
            if _wmode in ("LEGAL", "NORMAL", "SPLIT"):
                wx = cx + DOT_W + 7
                self.weights_x = wx
                _a = 1.0
                if _wphase not in ("idle", "done", "failed", "frozen"):
                    _a = 0.35 + 0.65 * abs(((time.time() * 1.4) % 2.0) - 1.0)
                cy = PILL_H / 2
                cr.new_path()
                cr.move_to(wx, cy - 7)          # apex
                cr.line_to(wx + 11, cy)         # right point
                cr.line_to(wx, cy + 7)          # base
                cr.close_path()
                cr.set_source_rgba(*_wcol, _a)
                cr.fill()
                _text_x = wx + 11 + GAP

        cr.set_font_size(12)
        cr.set_source_rgb(*FG)
        cr.move_to(_text_x, PILL_H / 2 + 4)
        cr.show_text(text)

        if lease_txt:
            cr.set_font_size(11)
            cr.set_source_rgb(*dot)
            cr.move_to(cx + DOT_W + GAP + tw + GAP, PILL_H / 2 + 4)
            cr.show_text(lease_txt)

        # ---- buttons ---------------------------------------------------
        if not self.BUTTONS:
            self.snap_rect = self.rec_rect = self.reader_rect = (0, 0, 0, 0)
            return self.draw_panel(cr, pill_x, pill_w, kind, dot, label)

        # show_text() leaves a current point, and a following arc() draws a
        # LINE to it - that is what put a stripe through the camera and on to
        # the REC dot. Clear the path before any button geometry.
        cr.new_path()
        recx = pill_x + pill_w - PAD - REC_W
        recording = self.rec_proc is not None and self.rec_proc.poll() is None
        if self.rec_proc is not None and not recording:
            self.rec_proc = None
        self.rec_rect = (recx - 4, 0, REC_W + 8, PILL_H)
        cr.set_line_width(1.4)
        if recording:
            blink = (int(time.monotonic() * 2) % 2) == 0
            cr.set_source_rgba(*REC_RED, 1.0 if blink else 0.45)
            cr.new_sub_path()
            cr.arc(recx + REC_W / 2, PILL_H / 2, 5, 0, 6.28319)
            cr.fill()
        else:
            cr.set_source_rgb(*DIM)
            cr.new_sub_path()
            cr.arc(recx + REC_W / 2, PILL_H / 2, 4.6, 0, 6.28319)
            cr.stroke()

        # ---- camera button --------------------------------------------
        bx = recx - 10 - SNAP_W
        by = (PILL_H - 14) / 2
        self.snap_rect = (bx - 4, 0, SNAP_W + 8, PILL_H)
        fresh = (time.monotonic() - self.snap_flash) < 1.4
        cr.set_source_rgb(*(OK_GREEN if fresh else DIM))
        cr.set_line_width(1.4)
        # body
        rounded(cr, bx, by + 3, SNAP_W, 11, 2.5)
        cr.stroke()
        # viewfinder bump
        cr.rectangle(bx + 6, by, 7, 3)
        cr.stroke()
        # lens
        cr.new_sub_path()
        cr.arc(bx + SNAP_W / 2, by + 8.5, 3.2, 0, 6.28319)
        cr.stroke()

        # ---- reader button ---------------------------------------------
        if self.reader is not None:
            rdx = bx - 10 - READER_W
            self.reader_rect = (rdx - 4, 0, READER_W + 8, PILL_H)
            cr.new_path()
            self.reader.draw(cr, rdx, PILL_H, DIM, OK_GREEN)

        return self.draw_panel(cr, pill_x, pill_w, kind, dot, label)

    def draw_panel(self, cr, pill_x, pill_w, kind, dot, label):
        if not self.expanded:
            return False

        px = ((pill_x + pill_w - PANEL_W) if self.ANCHOR == "right"
              else (self.win_w - PANEL_W) // 2)
        pw = PANEL_W
        rounded(cr, px, PILL_H + 6, pw, PANEL_H - 16, 12, top=True, bottom=True)
        cr.set_source_rgba(*BG)
        cr.fill()

        y = PILL_H + 30
        cr.set_font_size(12)

        def row(k, v, colour=FG):
            nonlocal y
            cr.set_source_rgb(*DIM)
            cr.move_to(px + 16, y)
            cr.show_text(k)
            cr.set_source_rgb(*colour)
            ext = cr.text_extents(v)
            cr.move_to(px + pw - 16 - ext.width, y)
            cr.show_text(v)
            y += 21

        for k, v, c in self.panel_rows(kind, dot, label):
            row(k, v, c)

        cr.set_source_rgb(*DIM)
        cr.set_font_size(10)
        cr.move_to(px + 16, PILL_H + PANEL_H - 26)
        cr.show_text("click pill to close  ·  right-click to quit")
        return False


class FleetProbe:
    """Reachability of the fleet, from a child process - it touches the network,
    which must never happen on the UI loop. fleet-status v1 on this machine
    called restic over sftp (51 s) from a desklet timer and froze the desktop."""

    PERIOD = 30.0

    def __init__(self):
        self.hosts = []      # [{name, addr, up, ms}]
        self.stamp = 0
        self._proc = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _helper(self):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "mrog-fleet-helper.py")
        return here if os.path.exists(here) else os.path.expanduser(
            "~/.local/bin/mrog-fleet-helper")

    def _loop(self):
        while True:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = subprocess.Popen(
                        [sys.executable, self._helper(), "--period", str(self.PERIOD)],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                line = self._proc.stdout.readline()
                if not line:
                    self._proc = None
                    time.sleep(5)
                    continue
                d = json.loads(line)
                self.hosts, self.stamp = d.get("hosts", []), d.get("ts", 0)
            except Exception:
                self._proc = None
                time.sleep(5)

    def summary(self):
        if not self.hosts:
            return (0, 0)
        return (sum(1 for h in self.hosts if h.get("up")), len(self.hosts))


class FleetPill(Notch):
    """The upper-right pill: fleet reachability, same visual language.

    Everything about the window - shape, hide-on-fullscreen, expand, hover
    peek - is inherited. Only the content and the anchor differ.
    """

    ANCHOR = "right"
    BUTTONS = False
    NEEDS_SENSORS = False
    NEEDS_GPU = False
    MIN_PILL_W = 150

    def __init__(self):
        self.fleet = FleetProbe()
        super().__init__()

    def lease_state(self):
        up, total = self.fleet.summary()
        if total and up == total:
            return ("idle", OK_GREEN, "")
        if total:
            return ("idle", DOT_SHELL if up else DOT_INPUT, "")
        return ("idle", DOT_IDLE, "")

    def pill_parts(self):
        up, total = self.fleet.summary()
        return [f"FLEET {up}/{total}" if total else "FLEET \u2026"]

    def panel_rows(self, kind, dot, label):
        rows = []
        for h in self.fleet.hosts:
            if h.get("up"):
                rows.append((h["name"], f"{h['addr']}   {h['ms']} ms", FG))
            else:
                rows.append((h["name"], f"{h['addr']}   DOWN", DOT_INPUT))
        if not rows:
            rows = [("fleet", "probing\u2026", DIM)]
        age = int(time.time() - self.fleet.stamp) if self.fleet.stamp else None
        rows.append(("checked", f"{age}s ago" if age is not None else "-", DIM))
        return rows




# ---------------------------------------------------------------------------
#  Scratchpad - part of the pill, not a separate window
#
#  Deliberately NOT an attempt at Notepad++. This is the quick-capture half: a
#  real GtkSourceView for the note you need right now. Anything that deserves a
#  session, a plugin or a 500 MB file goes to Kate via "Open in Kate" - that is
#  the division of labour, and the reason this stays small.
#
#  It lives INSIDE the NOTE pill's own window, drawn on the same canvas and
#  dropping into the top-right corner, so it reads as one piece of UI rather
#  than an app that happens to be launched from one.
# ---------------------------------------------------------------------------
class ScratchPad(Gtk.Box):
    """The editor body. A Box, so the pill can host it directly."""

    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.owner = owner
        os.makedirs(NOTEDIR, exist_ok=True)
        self.state_path = os.path.join(NOTEDIR, "state.json")
        self.path = None
        self.dirty = False
        self._save_timer = None

        # The toolbar's natural width is wider than the S pad, and a Box will
        # push its parent out rather than clip. Scroll it instead, so the small
        # size stays small.
        tbwrap = Gtk.ScrolledWindow()
        tbwrap.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        tbwrap.set_propagate_natural_width(False)
        tbwrap.add(self._toolbar())
        tbwrap.set_size_request(-1, 42)
        self.pack_start(tbwrap, False, False, 0)

        self.buf = GtkSource.Buffer()
        self.view = GtkSource.View(buffer=self.buf)
        self.view.set_show_line_numbers(True)
        self.view.set_highlight_current_line(True)
        self.view.set_auto_indent(True)
        self.view.set_insert_spaces_instead_of_tabs(True)
        self.view.set_tab_width(4)
        self.view.set_monospace(True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        sm = GtkSource.StyleSchemeManager.get_default()
        for scheme in ("oblivion", "cobalt", "solarized-dark", "classic"):
            sch = sm.get_scheme(scheme)
            if sch:
                self.buf.set_style_scheme(sch)
                break
        # The scheme colours the syntax; it does NOT reliably colour the widget
        # itself, which came out white against the dark pill. Set it outright so
        # the pad always matches the panel it is sitting in.
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            textview, textview text { background-color: #14141a; color: #e6e6ea; }
            textview border { background-color: #1b1b23; color: #6a6a78; }
            scrolledwindow { background-color: #14141a; }
        """)
        self.view.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_propagate_natural_width(False)
        self.sw.set_min_content_width(120)
        self.sw.add(self.view)
        self.sw.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.pack_start(self.sw, True, True, 0)

        self.find_bar, self.find_entry = self._findbar()
        self.pack_start(self.find_bar, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.set_margin_start(8)
        self.status.set_margin_bottom(4)
        self.pack_start(self.status, False, False, 0)

        self.buf.connect("changed", self._on_change)
        self.buf.connect("notify::cursor-position", lambda *_: self._update_status())

    # -- chrome ------------------------------------------------------------
    def _toolbar(self):
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for m in (6, ):
            tb.set_margin_top(m); tb.set_margin_start(m)
            tb.set_margin_end(m); tb.set_margin_bottom(2)
        for name, tip in (("S", "small box"), ("M", "half the corner"),
                          ("L", "the whole corner")):
            b = Gtk.Button(label=name)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _w, n=name: self.owner.set_pad_size(n))
            tb.pack_start(b, False, False, 0)
        for label, cb, tip in (("New", self.act_new, "Ctrl+N"),
                               ("Open\u2026", self.act_open, None),
                               ("Save", self.act_save, "Ctrl+S"),
                               ("Save as\u2026", self.act_save_as, None)):
            b = Gtk.Button(label=label)
            if tip:
                b.set_tooltip_text(tip)
            b.connect("clicked", lambda _w, f=cb: f())
            tb.pack_start(b, False, False, 0)
        self.recent_btn = Gtk.MenuButton(label="Recent")
        self.recent_btn.set_popup(self._recent_menu())
        tb.pack_start(self.recent_btn, False, False, 0)

        close = Gtk.Button(label="\u2715")
        close.set_tooltip_text("Close (Esc) - it saves first")
        close.connect("clicked", lambda _w: self.owner.close_pad())
        tb.pack_end(close, False, False, 0)
        kate = Gtk.Button(label="Open in Kate")
        kate.set_tooltip_text("Hand this file to the real editor")
        kate.connect("clicked", lambda _w: self.act_kate())
        tb.pack_end(kate, False, False, 0)
        return tb

    def _recent_menu(self):
        menu = Gtk.Menu()
        rm = Gtk.RecentManager.get_default()
        n = 0
        for it in sorted(rm.get_items(), key=lambda i: i.get_modified(), reverse=True):
            try:
                mime = it.get_mime_type() or ""
                path = it.get_uri().replace("file://", "")
                if not (mime.startswith("text/") or mime in
                        ("application/json", "application/x-yaml",
                         "application/x-shellscript", "application/xml")):
                    continue
                if not os.path.exists(path):
                    continue
            except Exception:
                continue
            mi = Gtk.MenuItem(label=os.path.basename(path))
            mi.set_tooltip_text(path)
            mi.connect("activate", lambda _w, q=path: self.open_path(q))
            menu.append(mi)
            n += 1
            if n >= 15:
                break
        if not n:
            menu.append(Gtk.MenuItem(label="(no recent text files)"))
        menu.show_all()
        return menu

    def _findbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.set_margin_start(6); bar.set_margin_end(6); bar.set_margin_bottom(4)
        entry = Gtk.SearchEntry()
        entry.set_placeholder_text("Find\u2026  Enter next, Shift+Enter previous, Esc closes")
        bar.pack_start(entry, True, True, 0)
        self.settings_find = GtkSource.SearchSettings(wrap_around=True)
        self.ctx = GtkSource.SearchContext(buffer=self.buf, settings=self.settings_find)
        entry.connect("search-changed",
                      lambda e: self.settings_find.set_search_text(e.get_text()))
        entry.connect("activate", lambda _e: self.find_step(True))
        for label, fwd in (("\u25b2", False), ("\u25bc", True)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, f=fwd: self.find_step(f))
            bar.pack_start(b, False, False, 0)
        return bar, entry

    def find_step(self, forward):
        it = self.buf.get_iter_at_mark(self.buf.get_insert())
        found, a, b, _ = (self.ctx.forward(it) if forward else self.ctx.backward(it))
        if found:
            self.buf.select_range(a, b)
            self.view.scroll_to_iter(a, 0.15, False, 0, 0)

    # -- state -------------------------------------------------------------
    def _on_change(self, *_):
        self.dirty = True
        self._update_status()
        if self._save_timer:
            GLib.source_remove(self._save_timer)
        # Debounced: never lose a note, never write on every keystroke.
        self._save_timer = GLib.timeout_add(1500, self._autosave)

    def _autosave(self):
        self._save_timer = None
        self.save(silent=True)
        return False

    def _update_status(self):
        it = self.buf.get_iter_at_mark(self.buf.get_insert())
        name = os.path.basename(self.path) if self.path else "scratch"
        self.status.set_markup(
            f"<small>{GLib.markup_escape_text(name)}"
            f"{'  \u2022 modified' if self.dirty else '  \u2713 saved'}"
            f"   \u2014   line {it.get_line() + 1}, col {it.get_line_offset() + 1}"
            f"   \u2014   {self.buf.get_char_count()} chars</small>")

    def scratch_file(self):
        return os.path.join(NOTEDIR, "scratch.txt")

    def open_path(self, path, restore_offset=0):
        target = path or self.scratch_file()
        text = ""
        if os.path.exists(target):
            try:
                with open(target, errors="replace") as f:
                    text = f.read()
            except Exception as e:
                text = f"[could not read {target}: {e}]"
        self.path = None if target == self.scratch_file() else target
        lm = GtkSource.LanguageManager.get_default()
        self.buf.set_language(lm.guess_language(target, None) if path else None)
        self.buf.begin_not_undoable_action()
        self.buf.set_text(text)
        self.buf.end_not_undoable_action()
        self.dirty = False
        off = max(0, min(restore_offset, self.buf.get_char_count()))
        it = self.buf.get_iter_at_offset(off)
        self.buf.place_cursor(it)
        GLib.idle_add(lambda: (self.view.scroll_to_iter(it, 0.3, False, 0, 0), False)[1])
        self.recent_btn.set_popup(self._recent_menu())
        self._update_status()

    def save(self, silent=False):
        target = self.path or self.scratch_file()
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            a, b = self.buf.get_bounds()
            with open(target, "w") as f:
                f.write(self.buf.get_text(a, b, True))
            self.dirty = False
            self._update_status()
            self.save_state()
        except Exception as e:
            if not silent:
                self.status.set_markup("<small>save failed: "
                                       f"{GLib.markup_escape_text(str(e))}</small>")

    def act_save(self):
        self.save()

    def act_new(self):
        self.save(silent=True)
        self.path = None
        self.buf.set_text("")
        self.buf.set_language(None)
        self.dirty = False
        self._update_status()

    def act_open(self):
        ch = Gtk.FileChooserDialog(title="Open", action=Gtk.FileChooserAction.OPEN)
        ch.set_keep_above(True)
        ch.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        ch.set_current_folder(NOTEDIR)
        if ch.run() == Gtk.ResponseType.OK:
            self.save(silent=True)
            self.open_path(ch.get_filename())
        ch.destroy()

    def act_save_as(self):
        ch = Gtk.FileChooserDialog(title="Save as", action=Gtk.FileChooserAction.SAVE)
        ch.set_keep_above(True)
        ch.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        ch.set_do_overwrite_confirmation(True)
        ch.set_current_folder(NOTEDIR)
        ch.set_current_name(os.path.basename(self.path) if self.path else "note.txt")
        if ch.run() == Gtk.ResponseType.OK:
            self.path = ch.get_filename()
            self.save()
        ch.destroy()

    def act_kate(self):
        self.save(silent=True)
        target = self.path or self.scratch_file()
        exe = shutil.which("kate") or shutil.which("notepadqq") or shutil.which("xed")
        if exe:
            subprocess.Popen([exe, target], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def load_state(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def save_state(self):
        try:
            it = self.buf.get_iter_at_mark(self.buf.get_insert())
            with open(self.state_path, "w") as f:
                json.dump({"last_file": self.path,
                           "offset": it.get_offset(),
                           "size": self.owner.pad_size}, f)
        except Exception:
            pass


class NotePill(Notch):
    """The middle pill. Its drop-down IS the scratchpad, filling the top-right
    corner - small box, half the corner, or the whole corner."""

    ANCHOR = "frac"
    ANCHOR_FRAC = 0.74
    BUTTONS = False
    NEEDS_SENSORS = False
    NEEDS_GPU = False
    MIN_PILL_W = 120
    MARGIN = 14          # gap from the screen's right edge

    def __init__(self):
        self.pad = None
        self.pad_open = False
        self.pad_size = "M"
        self.pad_rect = (0, 0, 0, 0)   # x, y, w, h inside the window
        super().__init__()

    # -- body: canvas underneath, editor on top ----------------------------
    def build_body(self):
        # An embedded editor needs the keyboard, so unlike the other pills this
        # window must accept focus - set before realise, not after.
        self.set_accept_focus(True)
        self.fixed = Gtk.Fixed()
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.fixed.put(self.area, 0, 0)
        self.area.set_size_request(self.win_w, self.win_h)
        self.add(self.fixed)
        if GtkSource is not None:
            self.pad = ScratchPad(self)
            self.fixed.put(self.pad, 0, PILL_H)
        self.connect("key-press-event", self._on_key)

    def sizes(self):
        """S is a small box; M is half the corner; L is the whole corner, and
        the same proportion downwards."""
        g = self._mon_geo()
        return {"S": (460, 320),
                "M": (g.width // 2, g.height // 2),
                "L": (int(g.width * 0.72), int(g.height * 0.84))}

    def window_geometry(self):
        """Big enough for the pill AND the largest pad, and then never changed.
        The pill is anchored to the monitor; if the window resized to fit the
        pad, the pill would slide around with it. So the window is fixed and
        oversized, and the input shape keeps the empty parts click-through."""
        g = self._mon_geo()
        pad_w, pad_h = self.sizes()["L"]
        pad_left = g.x + g.width - self.MARGIN - pad_w
        pill_left = g.x + int(g.width * self.ANCHOR_FRAC) - 260
        left = min(pad_left, pill_left) - 20
        return (g.x + g.width - self.MARGIN + 10 - left,
                PILL_H + 6 + pad_h + 10)

    def reposition(self):
        g = self._mon_geo()
        pad_w, _ = self.sizes()["L"]
        pad_left = g.x + g.width - self.MARGIN - pad_w
        pill_left = g.x + int(g.width * self.ANCHOR_FRAC) - 260
        self.win_left = min(pad_left, pill_left) - 20
        self.move(self.win_left, g.y)
        self.relayout()

    # -- layout ------------------------------------------------------------
    def relayout(self):
        """Move the PAD only. The window and the pill both stay put."""
        g = self._mon_geo()
        if not self.pad_open:
            self.pad_rect = (0, 0, 0, 0)
            if self.pad:
                self.pad.hide()
            self.apply_input_shape()
            return

        pw, ph = self.sizes()[self.pad_size]
        pad_left = g.x + g.width - self.MARGIN - pw
        self.pad_rect = (pad_left - self.win_left, PILL_H + 6, pw, ph)
        if self.pad:
            self.fixed.move(self.pad, self.pad_rect[0] + 6, self.pad_rect[1] + 6)
            self.pad.set_size_request(pw - 12, ph - 12)
            self.pad.show_all()
            self.pad.find_bar.hide()
        self.area.set_size_request(self.win_w, self.win_h)
        if os.environ.get("MROG_NOTCH_DEBUG"):
            print(f"[relayout] size={self.pad_size} pad_rect={self.pad_rect} "
                  f"win=({self.win_left},{self.win_w}x{self.win_h}) "
                  f"pill_x={self.pill_x} pill_w={self.pill_w}", flush=True)
        self.apply_input_shape()

    def apply_input_shape(self):
        gdkwin = self.get_window()
        if not gdkwin:
            return
        region = cairo.Region(cairo.RectangleInt(self.pill_x, 0, self.pill_w, PILL_H))
        if self.pad_open:
            x, y, w, h = self.pad_rect
            region.union(cairo.RectangleInt(x, y, w, h))
        gdkwin.input_shape_combine_region(region, 0, 0)

    # -- behaviour ---------------------------------------------------------
    def set_pad_size(self, name):
        self.pad_size = name if name in self.sizes() else "M"
        self.relayout()
        if self.pad:
            self.pad.save_state()

    def open_pad(self):
        if self.pad is None:
            return
        st = self.pad.load_state()
        if not self.pad_open:
            self.pad_size = st.get("size", "M")
            self.pad.open_path(st.get("last_file"), restore_offset=st.get("offset", 0))
        self.pad_open = True
        self.relayout()
        self.present()
        self.pad.view.grab_focus()

    def close_pad(self):
        if self.pad:
            self.pad.save(silent=True)
            self.pad.save_state()
        self.pad_open = False
        self.relayout()

    def on_pill_click(self):
        self.close_pad() if self.pad_open else self.open_pad()

    def _on_key(self, _w, ev):
        if not self.pad_open or self.pad is None:
            return False
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        name = Gdk.keyval_name(ev.keyval)
        if ctrl and name in ("s", "S"):
            self.pad.act_save(); return True
        if ctrl and name in ("n", "N"):
            self.pad.act_new(); return True
        if ctrl and name in ("f", "F"):
            self.pad.find_bar.show_all(); self.pad.find_entry.grab_focus(); return True
        if name == "F11":
            self.set_pad_size("L" if self.pad_size != "L" else "M"); return True
        if name == "Escape":
            if self.pad.find_bar.get_visible():
                self.pad.find_bar.hide(); self.pad.view.grab_focus()
            else:
                self.close_pad()
            return True
        return False

    # -- looks -------------------------------------------------------------
    def tick(self):
        # A live pad must never be hidden by the fullscreen rule - you would be
        # typing into something that just vanished.
        if self.pad_open:
            self.hidden = False
            self.area.queue_draw()
            return True
        return super().tick()

    def lease_state(self):
        dirty = self.pad is not None and self.pad.dirty
        return ("idle", DOT_SHELL if dirty else OK_GREEN, "")

    def pill_parts(self):
        if self.pad_open and self.pad:
            name = os.path.basename(self.pad.path) if self.pad.path else "scratch"
            return [f"NOTE  {name[:20]}"]
        return ["NOTE"]

    def draw_panel(self, cr, pill_x, pill_w, kind, dot, label):
        """Draw the pad's backing panel; the editor widget sits on top of it."""
        if not self.pad_open:
            return False
        x, y, w, h = self.pad_rect
        rounded(cr, x, y, w, h, 12, top=True, bottom=True)
        cr.set_source_rgba(*BG)
        cr.fill()
        return False




# ---------------------------------------------------------------------------
#  Snap zones - drag a window to the top edge, drop it into a layout
#
#  Everything here is POLLED, and both overlay windows are input-transparent.
#  That is not laziness: while the WM is moving a window it holds a pointer
#  grab, so our windows receive no enter, motion or button events at all. The
#  only way to know where the pointer is, and what it is over, is to ask the
#  server and do the hit-testing ourselves.
#
#  Polling is adaptive - 10 Hz while nothing is held, 40 Hz during a drag - so
#  the idle cost is one X round trip every 100 ms.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
#  KillDot - the stop button, visible above everything
#
#  A POPUP window is override-redirect: the WM does not manage it, so it sits
#  above fullscreen windows, which a DOCK does not. It exists ONLY while a
#  lease is live, so at rest it costs nothing at all - and it is driven by the
#  system pill's existing 1 Hz tick, so it adds no timer either.
#
#  In a panic nobody remembers a command. This is a red button that says STOP.
# ---------------------------------------------------------------------------
class KillDot(Gtk.Window):
    H_ = 24
    PAD, SQ, GAP = 11, 8, 7

    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.label = ""
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        v = self.get_screen().get_rgba_visual()
        if v:
            self.set_visual(v)
        self.W_ = 120
        self._meas = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        self._meas.select_font_face("Ubuntu", cairo.FONT_SLANT_NORMAL,
                                    cairo.FONT_WEIGHT_BOLD)
        self._meas.set_font_size(11)
        self.set_size_request(self.W_, self.H_)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.add(self.area)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_click)
        self.realize()
        self.reposition()

    def reposition(self):
        """Anchor to the WORK AREA, not the monitor geometry - the work area
        already has the left panel subtracted, so this cannot sit on top of the
        favourites bar however wide that panel gets."""
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        a = mon.get_workarea()
        self.move(a.x + 10, a.y + 6)

    def fit(self, text):
        """Capsule sized to the words, nothing more."""
        w = int(self.PAD + self.SQ + self.GAP
                + self._meas.text_extents(text).width + self.PAD)
        if w != self.W_:
            self.W_ = w
            self.set_size_request(w, self.H_)
            self.resize(w, self.H_)

    def on_click(self, _w, _ev):
        subprocess.Popen(["mrog-input", "revoke"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.label = "STOPPED"
        self.area.queue_draw()
        return True

    def show_for(self, text):
        if self.label != "STOPPED":
            self.label = text
        self.fit(self.label or "STOP")
        if not self.get_visible():
            self.reposition()
            self.show_all()
        self.reposition()
        self.area.queue_draw()

    def hide_now(self):
        self.label = ""
        if self.get_visible():
            self.hide()

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        rounded(cr, 0, 0, self.W_, self.H_, self.H_ / 2, top=True, bottom=True)
        cr.set_source_rgba(*KILL_BG)
        cr.fill()
        # a filled square: the universal stop, readable at a glance
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(self.PAD, self.H_ / 2 - self.SQ / 2, self.SQ, self.SQ)
        cr.fill()
        cr.select_font_face("Ubuntu", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(self.PAD + self.SQ + self.GAP, self.H_ / 2 + 4)
        cr.show_text(self.label or "STOP")
        return False


class SnapZones:
    """Drag a window to a sliver at the top edge, drop it into a layout.

    Two slivers, each ONE INCH wide (computed from the monitor's real DPI, not
    a guessed pixel count), sitting side by side under the LAYOUTS pill:

        [ monitor 2 ][ this screen ]        <- left one only when 2 is plugged in

    Small on purpose. A full-width strip is far too easy to hit by accident
    while just moving a window near the top of the screen.

    Everything here is POLLED, and both overlays are input-transparent. That is
    not laziness: while the WM is moving a window it holds a pointer grab, so
    our windows receive no motion, enter or button events at all. The only way
    to know where the pointer is and what it is over is to ask the server and
    hit-test ourselves. Polling is adaptive - 200 ms idle, 25 ms during a drag -
    so the resting cost is unmeasurable.
    """

    CARD_W, CARD_H, CARD_GAP = 190, 112, 16
    DRAG_SLOP = 24          # px of movement before we believe it is a drag
    SLIVER_GAP = 10
    LINGER = 0.70           # seconds the chooser stays after the pointer leaves
    FADE_MS = 220           # then it fades rather than vanishing

    def __init__(self, layouts):
        self.layouts = layouts
        self.d = xdisplay.Display()
        self.root = self.d.screen().root
        self.a_active = self.d.intern_atom("_NET_ACTIVE_WINDOW")
        self.a_type = self.d.intern_atom("_NET_WM_WINDOW_TYPE")
        self.a_normal = self.d.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")

        self.pressed_at = None
        self.dragging = False
        self.drag_win = None
        self.armed = None       # index into self.slivers
        self.hot = None         # (layout_index, zone_index)
        self.left_at = None     # when the pointer left the chooser, or None
        self.fade_src = None
        self.slivers = []
        self.slit = self._make_overlay()
        self.chooser = self._make_overlay()
        self.slit.connect("draw", self._draw_slit)
        self.chooser.connect("draw", self._draw_chooser)
        self._layout_overlays()
        GLib.timeout_add(200, self._tick)

    # -- overlays ----------------------------------------------------------
    def _make_overlay(self):
        w = Gtk.Window(type=Gtk.WindowType.POPUP)
        w.set_app_paintable(True)
        w.set_decorated(False)
        w.set_keep_above(True)
        w.set_accept_focus(False)
        w.set_skip_taskbar_hint(True)
        v = w.get_screen().get_rgba_visual()
        if v:
            w.set_visual(v)
        w.realize()
        # Input-transparent. The WM's drag grab means we would never receive an
        # event anyway, and this guarantees we can never swallow one.
        w.get_window().input_shape_combine_region(cairo.Region(), 0, 0)
        return w

    def _monitors(self):
        disp = Gdk.Display.get_default()
        pm = disp.get_primary_monitor()
        mons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())]
        mons.sort(key=lambda m: 0 if (pm and m is pm) else 1)
        return mons

    def _inch(self, mon):
        g = mon.get_geometry()
        mm = mon.get_width_mm() or 0
        if mm <= 0:
            return 96
        return int(max(100, min(220, g.width / (mm / 25.4))))

    def _layout_overlays(self):
        """One sliver per monitor, side by side under the LAYOUTS pill."""
        mons = self._monitors()
        prim = mons[0]
        g = prim.get_geometry()
        w1 = self._inch(prim)
        centre = g.x + int(g.width * 0.26)

        self.slivers = []
        # rightmost = this screen, then one to its LEFT per extra monitor
        x = centre - w1 // 2
        self.slivers.append({"x": x, "w": w1, "mon": prim,
                             "name": prim.get_model() or "primary", "label": "here"})
        for k, m in enumerate(mons[1:], start=1):
            x = x - self.SLIVER_GAP - w1
            self.slivers.append({"x": x, "w": w1, "mon": m,
                                 "name": m.get_model() or f"monitor{k}",
                                 "label": f"screen {k + 1}"})

        left = min(s["x"] for s in self.slivers) - 2
        right = max(s["x"] + s["w"] for s in self.slivers) + 2
        self.slit_x, self.slit_w = left, right - left
        self.slit.set_size_request(self.slit_w, SLIT_H)
        self.slit.resize(self.slit_w, SLIT_H)
        self.slit.move(self.slit_x, g.y)

        n = len(self.layouts)
        cw = n * self.CARD_W + (n - 1) * self.CARD_GAP + 28
        ch = self.CARD_H + 52
        self.card_w, self.card_h = cw, ch
        self.chooser.set_size_request(cw, ch)
        self.chooser.resize(cw, ch)

    def _place_chooser(self, sliver):
        """Open it directly under the sliver you entered, nudged to stay on."""
        g = self._monitors()[0].get_geometry()
        x = sliver["x"] + sliver["w"] // 2 - self.card_w // 2
        x = max(g.x + 6, min(x, g.x + g.width - self.card_w - 6))
        self.cx, self.cy = x, g.y + SLIT_H + 6
        self.chooser.move(self.cx, self.cy)

    def card_rect(self, i):
        x = self.cx + 14 + i * (self.CARD_W + self.CARD_GAP)
        return (x, self.cy + 34, self.CARD_W, self.CARD_H)

    def zone_rect_screen(self, i, j):
        cx, cy, cw, ch = self.card_rect(i)
        fx, fy, fw, fh = self.layouts[i][2][j]
        return (int(cx + fx * cw), int(cy + fy * ch), int(fw * cw), int(fh * ch))

    # -- drawing -----------------------------------------------------------
    def _draw_slit(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        for k, s in enumerate(self.slivers):
            x = s["x"] - self.slit_x
            live = self.armed == k
            # the "other screen" sliver is dimmer so the two are tellable apart
            alpha = 0.95 if live else (0.70 if k == 0 else 0.42)
            rounded(cr, x, 0, s["w"], SLIT_H, 2, top=False, bottom=True)
            cr.set_source_rgba(*ACCENT, alpha)
            cr.fill()
        return False

    def _draw_chooser(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        rounded(cr, 0, 0, self.card_w, self.card_h, 12, top=True, bottom=True)
        cr.set_source_rgba(*BG)
        cr.fill()

        cr.select_font_face("Ubuntu", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        s = self.slivers[self.armed] if self.armed is not None else None
        msg = f"drop into a zone  \u2014  {s['name']}" if s else "drop into a zone"
        cr.set_source_rgb(*(ACCENT if s else DIM))
        ext = cr.text_extents(msg)
        cr.move_to((self.card_w - ext.width) / 2, 21)
        cr.show_text(msg)

        for i, (name, title, zones) in enumerate(self.layouts):
            cx, cy, cw, ch = self.card_rect(i)
            ox, oy = cx - self.cx, cy - self.cy
            for j, z in enumerate(zones):
                zx, zy, zw, zh = (ox + int(z[0] * cw), oy + int(z[1] * ch),
                                  int(z[2] * cw), int(z[3] * ch))
                live = self.hot == (i, j)
                cr.set_source_rgba(*ACCENT, 0.85 if live else 0.16)
                cr.rectangle(zx + 2, zy + 2, zw - 4, zh - 4)
                cr.fill()
                cr.set_source_rgba(*ACCENT, 0.9)
                cr.set_line_width(1)
                cr.rectangle(zx + 2.5, zy + 2.5, zw - 5, zh - 5)
                cr.stroke()
            hot_card = any(self.hot == (i, k) for k in range(len(zones)))
            cr.set_source_rgb(*(FG if hot_card else DIM))
            cr.set_font_size(10)
            ext = cr.text_extents(name)
            cr.move_to(ox + (cw - ext.width) / 2, oy + ch + 14)
            cr.show_text(name)
        return False

    # -- the loop ----------------------------------------------------------
    def _pointer(self):
        p = self.root.query_pointer()._data
        return p["root_x"], p["root_y"], p["mask"]

    def _active_normal_window(self):
        try:
            pr = self.root.get_full_property(self.a_active, X.AnyPropertyType)
            if not pr or not pr.value or not pr.value[0]:
                return None
            wid = pr.value[0]
            w = self.d.create_resource_object("window", wid)
            tp = w.get_full_property(self.a_type, X.AnyPropertyType)
            if tp and tp.value and self.a_normal not in set(tp.value):
                return None
            return wid
        except Exception:
            return None

    def _sliver_at(self, x, y):
        g = self._monitors()[0].get_geometry()
        if (y - g.y) > SLIT_H:
            return None
        for k, s in enumerate(self.slivers):
            if s["x"] <= x <= s["x"] + s["w"]:
                return k
        return None

    def _tick(self):
        try:
            x, y, mask = self._pointer()
        except Exception:
            GLib.timeout_add(200, self._tick)
            return False
        held = bool(mask & (1 << 8))          # Button1Mask

        if held and self.pressed_at is None:
            self.pressed_at = (x, y)
            self.drag_win = self._active_normal_window()

        if held and not self.dragging and self.pressed_at:
            dx = abs(x - self.pressed_at[0]); dy = abs(y - self.pressed_at[1])
            if (dx + dy) >= self.DRAG_SLOP and self.drag_win:
                self.dragging = True
                # An unmapped POPUP does not keep geometry set at construction -
                # both overlays sat on the OTHER monitor until this was added.
                self._layout_overlays()
                self.slit.show_all()
                self.slit.queue_draw()

        if self.dragging:
            k = self._sliver_at(x, y)
            if k is not None and self.armed != k:
                self._cancel_fade()
                self.left_at = None
                self.armed = k
                self._place_chooser(self.slivers[k])
                self.chooser.show_all()
                self.chooser.queue_draw()
                self.slit.queue_draw()
            if self.armed is not None:
                if self._still_interested(x, y):
                    self.left_at = None
                    self._cancel_fade()
                elif self.left_at is None:
                    self.left_at = time.monotonic()
                elif (self.fade_src is None
                      and time.monotonic() - self.left_at >= self.LINGER):
                    self._start_fade()

            if self.armed is not None:
                hot = None
                for i in range(len(self.layouts)):
                    for j in range(len(self.layouts[i][2])):
                        zx, zy, zw, zh = self.zone_rect_screen(i, j)
                        if zx <= x <= zx + zw and zy <= y <= zy + zh:
                            hot = (i, j)
                if hot != self.hot:
                    self.hot = hot
                    self.chooser.queue_draw()

        if not held and self.pressed_at is not None:
            if self.armed is not None and self.hot and self.drag_win:
                self._drop(self.drag_win, *self.hot, self.slivers[self.armed]["name"])
            self._reset()

        GLib.timeout_add(25 if held else 200, self._tick)
        return False

    def _chooser_rect(self, pad=18):
        return (self.cx - pad, self.cy - pad,
                self.card_w + 2 * pad, self.card_h + 2 * pad)

    def _still_interested(self, x, y):
        """Inside the armed sliver, or inside the chooser (with a margin)."""
        s = self.slivers[self.armed]
        g = self._monitors()[0].get_geometry()
        if s["x"] <= x <= s["x"] + s["w"] and (y - g.y) <= SLIT_H + 4:
            return True
        cx, cy, cw, ch = self._chooser_rect()
        return cx <= x <= cx + cw and cy <= y <= cy + ch

    def _cancel_fade(self):
        if self.fade_src:
            GLib.source_remove(self.fade_src)
            self.fade_src = None
        self.chooser.set_opacity(1.0)

    def _start_fade(self):
        """Fade out rather than blink out - a chooser that vanishes the instant
        you leave reads as a glitch, and one that lingers gets in the way."""
        steps = max(1, self.FADE_MS // 40)
        state = {"i": 0}

        def step():
            state["i"] += 1
            a = max(0.0, 1.0 - state["i"] / steps)
            self.chooser.set_opacity(a)
            if a <= 0.0:
                self.chooser.hide()
                self.chooser.set_opacity(1.0)
                self.armed = None
                self.hot = None
                self.left_at = None
                self.fade_src = None
                self.slit.queue_draw()
                return False
            return True

        self.fade_src = GLib.timeout_add(40, step)

    def _reset(self):
        self._cancel_fade()
        self.pressed_at = None
        self.dragging = False
        self.armed = None
        self.hot = None
        self.left_at = None
        self.drag_win = None
        self.slit.hide()
        self.chooser.hide()

    def _drop(self, wid, i, j, monitor):
        name = self.layouts[i][0]
        subprocess.Popen(["workspace", "place", hex(wid), name, str(j),
                          "--monitor", monitor],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class WorkspacePill(Notch):
    """Mirror of the NOTE pill on the other side of centre, and hidden until
    the pointer comes up to it."""

    ANCHOR = "frac"
    ANCHOR_FRAC = 0.26
    BUTTONS = False
    NEEDS_SENSORS = False
    NEEDS_GPU = False
    MIN_PILL_W = 130
    ALWAYS_HIDDEN = True

    def __init__(self, layouts):
        self.layouts = layouts
        super().__init__()

    def lease_state(self):
        return ("idle", ACCENT, "")

    def pill_parts(self):
        return ["LAYOUTS"]

    def panel_rows(self, kind, dot, label):
        rows = []
        for name, title, zones in self.layouts:
            rows.append((name, f"{title}   ({len(zones)})", FG))
        rows.append(("drag", "to the top edge to snap", DIM))
        rows.append(("click", "a row to arrange open windows", DIM))
        return rows

    def on_pill_click(self):
        self.expanded = not self.expanded
        self.apply_input_shape()

    def on_click(self, w, ev):
        # A click on a row in the drop-down applies that layout.
        if self.expanded and ev.button == 1 and ev.y > PILL_H:
            row = int((ev.y - (PILL_H + 30) + 14) // self.PANEL_ROW_H)
            if 0 <= row < len(self.layouts):
                subprocess.Popen(["workspace", "apply", self.layouts[row][0]],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.expanded = False
                self.apply_input_shape()
                self.area.queue_draw()
                return True
        return super().on_click(w, ev)


class SystemPill(Notch):
    SHOWS_KILL = True
    SHOWS_WEIGHTS = True


if __name__ == "__main__":
    SystemPill()
    if os.environ.get("MROG_NOTCH_FLEET", "1") != "0":
        FleetPill()
    # ASK pill. askpill.py is exec'd into THIS namespace on purpose: AskPill subclasses Notch
    # and uses DIM / OK_GREEN / DOT_INPUT, which live here. Same env-var switch as the others,
    # so `MROG_NOTCH_ASKPILL=0` turns it off exactly like FLEET / NOTE / SNAP.
    # 🔴 NOT `MROG_NOTCH_ASK` -- that is ALREADY TAKEN by ASK_AFTER_CAPTURE (line 67), which
    # controls the "what do you want to do with this capture?" dialog. Reusing it would have
    # meant turning off the ask-pill also silenced that dialog. Caught 2026-09-06.
    if os.environ.get("MROG_NOTCH_ASKPILL", "1") != "0":
        # 🔴 LOOK IN BOTH PLACES. install-notch.sh copies notch.py to
        # ~/.local/bin/mrog-notch, so at RUNTIME __file__ is in ~/.local/bin -- not in the
        # source tree where askpill.py sits. Resolving only relative to __file__ found
        # nothing and the pill silently never loaded, while the source looked correct.
        # Same lesson as CLAUDE.md Rule 2: check the path the CONSUMER opens.
        for _ap in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "askpill.py"),
                    os.path.expanduser("~/.local/bin/mrog-askpill.py"),
                    os.path.join(MROG_ROOT, "notch", "askpill.py")):
            if os.path.exists(_ap):
                exec(open(_ap).read(), globals())
                AskPill()
                break
    if os.environ.get("MROG_NOTCH_NOTE", "1") != "0" and GtkSource is not None:
        NotePill()
    if os.environ.get("MROG_NOTCH_SNAP", "1") != "0":
        LAYOUTS = [
            ("split", "Two side by side",
             [[0, 0, .5, 1], [.5, 0, .5, 1]]),
            ("main", "Big left, two right",
             [[0, 0, .66, 1], [.66, 0, .34, .5], [.66, .5, .34, .5]]),
            ("quad", "Four panes",
             [[0, 0, .5, .5], [.5, 0, .5, .5], [0, .5, .5, .5], [.5, .5, .5, .5]]),
        ]
        WorkspacePill(LAYOUTS)
        SnapZones(LAYOUTS)
    Gtk.main()
