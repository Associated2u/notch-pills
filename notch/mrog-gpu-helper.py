#!/usr/bin/env python3
# ============================================================================
#  mrog-gpu-helper - reads dGPU memory + temperature in a SHORT-LIVED process.
#
#  Why a separate process at all: ctypes.CDLL never dlclose()s, so once
#  libnvidia-ml is loaded the ~20 MB it drags in (libcuda 3.7 MB +
#  libnvidia-ml 1.0 MB + ~15 MB of driver anon) stays resident for the life of
#  the process, even after nvmlShutdown() and even after the fds close.
#  Releasing NVML recovers the 13.3 W; it does NOT recover the megabytes.
#  Putting it here means the notch itself stays at its 50 MB floor and the
#  driver's memory is handed back to the kernel when this exits.
#
#  Prints one JSON object per line on stdout:
#     {"state":"ok","used":339,"total":4096,"temp":54}
#     {"state":"error","msg":"..."}
#  Exits 0 on its own once the card has no user but us - see --grace. The
#  parent applies the cooldown before spawning another one.
#
#  Run as chris. No root.
# ============================================================================
import argparse
import ctypes
import json
import os
import signal
import sys
import time


class Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong)]


def emit(**kw):
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pci", default="0000:01:00.0")
    ap.add_argument("--period", type=float, default=2.0)
    ap.add_argument("--grace", type=int, default=8,
                    help="samples at the client floor before exiting (0 = never)")
    a = ap.parse_args()

    power = f"/sys/bus/pci/devices/{a.pci}/power/runtime_status"

    # Die with the parent rather than linger holding 13.3 W of GPU.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    try:
        import ctypes.util  # noqa: F401
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(1, signal.SIGTERM)          # PR_SET_PDEATHSIG
    except Exception:
        pass

    try:
        nvml = ctypes.CDLL("libnvidia-ml.so.1")
        if nvml.nvmlInit_v2() != 0:
            emit(state="error", msg="nvmlInit_v2 failed")
            return 1
        h = ctypes.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
            emit(state="error", msg="no device 0")
            return 1
    except Exception as e:
        emit(state="error", msg=str(e))
        return 1

    def resolve(base):
        for suffix in ("_v3", "_v2", ""):
            fn = getattr(nvml, base + suffix, None)
            if fn is not None:
                return fn
        return None

    gfx = resolve("nvmlDeviceGetGraphicsRunningProcesses")
    comp = resolve("nvmlDeviceGetComputeRunningProcesses")

    def clients():
        """Asking for 0 slots returns the count in n with rc=7, no allocation."""
        total = 0
        for fn in (gfx, comp):
            if fn is None:
                continue
            n = ctypes.c_uint(0)
            if fn(h, ctypes.byref(n), None) in (0, 7):
                total += n.value
        return total

    floor = None
    idle_for = 0
    try:
        while True:
            m, t = Mem(), ctypes.c_uint()
            ok_m = nvml.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0
            ok_t = nvml.nvmlDeviceGetTemperature(h, 0, ctypes.byref(t)) == 0
            emit(state="ok",
                 used=m.used // 2**20 if ok_m else 0,
                 total=m.total // 2**20 if ok_m else 0,
                 temp=t.value if ok_t else None)

            if a.grace:
                c = clients()
                # Running minimum, so a helper that starts during a game still
                # settles to the true idle floor (1 = Xorg) once it exits.
                floor = c if floor is None else min(floor, c)
                idle_for = idle_for + 1 if c <= floor else 0
                if idle_for >= a.grace:
                    break

            # If the card somehow went down under us, stop.
            try:
                if open(power).read().strip() != "active" and not a.grace:
                    break
            except Exception:
                pass

            time.sleep(a.period)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
