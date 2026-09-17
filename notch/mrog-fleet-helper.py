#!/usr/bin/env python3
# ============================================================================
#  mrog-fleet-helper - reachability of the five fleet machines.
#
#  Lives in its own process for the same reason the GPU helper does: this one
#  touches the NETWORK, and nothing that can block may ever run on the UI loop.
#  The precedent is on this machine already - fleet-status v1 called restic over
#  sftp (51 s) from a desklet's refresh timer and froze the whole desktop.
#
#  A TCP connect to port 22 rather than ping: ICMP is filtered in places on this
#  fleet, sshd is not, and a refused connection still proves the host is up.
#
#  Hosts come from ~/.ssh/config so this stays true when addresses move. Prints
#  one JSON object per line:
#     {"ts":..,"hosts":[{"name":"hub","addr":"192.0.2.132","up":true,"ms":3}]}
#
#  Run as chris. No root. Read-only: it opens a socket and closes it.
# ============================================================================
import argparse
import concurrent.futures as cf
import json
import os
import socket
import sys
import time

# Order matters - it is the order they appear in the panel.
# FLEET-V26: which hosts. MROG_FLEET_HOSTS="a b c" (ssh aliases or addresses); unset =
# every Host in ~/.ssh/config that has a HostName, in file order. An empty string = none.
def fleet_hosts(cfg):
    env = os.environ.get("MROG_FLEET_HOSTS")
    if env is not None:
        return env.split()
    return [a for a in cfg if "*" not in a and "?" not in a]


def ssh_hosts():
    """-> {alias: hostname} from ~/.ssh/config, so a moved box is picked up."""
    out, cur = {}, []
    path = os.path.expanduser("~/.ssh/config")
    try:
        for raw in open(path, errors="ignore"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition(" ")
            key = key.lower().strip()
            val = val.strip()
            if key == "host":
                cur = val.split()
            elif key == "hostname" and cur:
                for alias in cur:
                    out[alias] = val
    except Exception:
        pass
    return out


def probe(name, addr, port, timeout):
    t0 = time.monotonic()
    try:
        with socket.create_connection((addr, port), timeout=timeout):
            pass
        return {"name": name, "addr": addr, "up": True,
                "ms": int((time.monotonic() - t0) * 1000)}
    except ConnectionRefusedError:
        # Refused still proves the host answered.
        return {"name": name, "addr": addr, "up": True,
                "ms": int((time.monotonic() - t0) * 1000), "note": "refused"}
    except Exception:
        return {"name": name, "addr": addr, "up": False, "ms": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", type=float, default=30.0)
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    cfg = ssh_hosts()
    targets = [(n, cfg.get(n, n)) for n in fleet_hosts(cfg)]
    if not targets:
        sys.stdout.write(json.dumps({"ts": int(time.time()), "hosts": []}) + "\n")
        sys.stdout.flush()
        if a.once:
            return
        time.sleep(a.period)

    while True:
        with cf.ThreadPoolExecutor(max_workers=len(targets)) as ex:
            rows = list(ex.map(lambda t: probe(t[0], t[1], a.port, a.timeout), targets))
        sys.stdout.write(json.dumps({"ts": int(time.time()), "hosts": rows}) + "\n")
        sys.stdout.flush()
        if a.once:
            return 0
        time.sleep(a.period)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
