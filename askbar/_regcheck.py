#!/usr/bin/env python3
# _regcheck.py — integrity check for askbar/agents.yml.
#
# FAILURE CLASS THIS CATCHES (CLAUDE.md Rule 8 clause 5):
#   "A hand edit to agents.yml silently drops an agent ROW or a required KEY."
#   YAML is indentation-significant: mis-indenting one line folds a row into its
#   neighbour, or turns a key into a scalar. The file still PARSES, `ask --list`
#   still prints something, and the missing route only shows up the next time a
#   human tries to use it. Parsing is not validating.
#   NOT the class "the drop path is wrong" — a path can be well-formed and still
#   point at a machine the agent cannot read. That is proven by effect, not here.
#
# SECOND FAILURE CLASS, ADDED 2026-09-07 (stated separately because it is a different
# claim and clause 5 says to name it):
#   "A row is WELL-FORMED but carries a value the code cannot honour."
#   Three of the five rows shipped `ask_cmd: "claude {q}"` — a bare command name. The
#   PATH a non-interactive `ssh host "cmd"` gets holds none of Hub's real bin
#   dirs, so those three routes were dead for a day while `ask` printed OK. Two rows
#   carried `drop: "hub:~/asks"`, which becomes a RELATIVE remote path and then
#   resolves against whatever directory the agent is standing in. And `drop_via:
#   hermes_capture` named a branch that no longer exists. None of these are typos;
#   every one parses, and every one is now refused HERE, statically, so a future row
#   cannot reintroduce them. Shapes only — whether the binary exists on that host is
#   proven by effect in `ask`'s dispatch preflight, not here.
#
# THIRD FAILURE CLASS, ADDED 2026-09-07 (HERMES-VGE stage 3; named separately because it is
# again a different claim):
#   "A row silently loses a CHECK, so ask-selftest stops testing something and nobody notices."
#   Three shapes of this, all measured on this registry:
#     (a) `vision` written as a QUOTED string. ask:191 compares it as text against the literal
#         "False", so `vision: "false"` reads as TRUE and a .png is shipped to a text-only
#         agent -- for hermes, into an ACL-ed one-way inbox it can never delete. The row is
#         well-formed YAML and the old check passed it. Now `vision` must be a real bool.
#     (b) An OPTIONAL key misspelled (`healh:` for `health:`). A required key typo already
#         surfaces as a missing key; an optional one does not, and the row just quietly stops
#         being probed -- it degrades to SKIP and reads as "nothing to test here". KNOWN_KEYS
#         refuses any key not deliberately listed.
#     (c) A `health:` probe with no `ok`, or an `ok` that is not a valid regex. It would run
#         and never match, so the route would fail forever for a reason that is not its fault.
#   Shapes only, still: whether the probe actually PASSES on this machine is proven by effect
#   in ask-selftest, not here.
#
# FOURTH FAILURE CLASS, ADDED 2026-09-07 (HERMES-VGE stage 4; again a different claim):
#   "The registry cannot say WHERE THE AGENT READS, so the one defect that has cost the most
#    here is undetectable without an LLM call."
#   The 2026-09-07 F2 bug was a drop on Hub read by an agent on GpuBox. EVERY cheap
#   check passed -- the path was absolute, the directory existed, it was writable, the command
#   resolved -- because none of them knew which machine the agent stands on. `ask_host` does NOT
#   answer that: for dreamzs it names Hub, where the BRIDGE runs, while the agent itself is
#   on GpuBox. So the registry now carries `agent_ssh`, the ssh destination of the process that
#   OPENS THE FILE, and it is REQUIRED -- its absence is precisely the gap that hid F2.
#   With it the wrong-machine class is decidable for free: drop host and agent host must be the
#   same machine, and that account must be able to read the drop. Proven by effect in
#   ask-selftest's drop-agentside check; refused here only as a shape.
#
# FIFTH, ADDED IN THE SAME PASS:
#   "A route that is waiting on a HUMAN is reported with the same word as a route that is
#    BROKEN, so the real breakage hides inside the known backlog."
#   Three of five routes are waiting on Chris (a Claude Code trust prompt, an OpenAI account
#   entitlement, a `cn login`). Calling those FAIL trains him to skim past FAIL. A probe may
#   therefore declare `blocked_on:` -- but only WITH a `blocked_since:` date, so the wait is
#   COUNTABLE and ask-selftest can escalate it back to FAIL once it has gone stale. A blocked
#   state with no clock is just a mute button.
#
# Verdict is the printed WORD: PASS / FAIL. Never the exit code.
import datetime, re, sys, yaml

# codex retired 2026-09-08 (FLEET-H36) — Chris does not use it in this setup. The row is
# kept verbatim in RETIRED_codex_row.FLEET-H36.yml; the LESSONS it taught (--version exits
# 0 on a broken config; a prompt-echoing agent fakes a probe token) stay in the comments
# of ask-selftest, because those are about a failure CLASS, not about this row.
# FLEET-V26: the expected row set comes FROM THE REGISTRY (top-level `expected_ids:`), so
# the checker is not pinned to one fleet. Absent => the vanished-row check is skipped with a
# note; present => a missing or extra row is a named failure, exactly as before.
EXPECTED_IDS = None
REQUIRED = ["id", "label", "color", "model", "vision",
            "drop", "drop_via", "launch", "ask_host", "agent_ssh", "ask_cmd", "constraints"]
# The drop_via values `ask` actually implements. A value outside this set is not a
# harmless label: it falls through ask's case statement and the capture is never
# dropped at all. `hermes_capture` was retired 2026-09-07 -> `spine_md`.
KNOWN_DROP_VIA = {"auto", "local", "spine_md"}
# Every key a row is ALLOWED to carry. An unlisted key is refused rather than ignored, because
# an ignored key is a check that silently stopped running (see failure class three, shape b).
# Extend this list deliberately when you add a field, the same way EXPECTED_IDS is extended.
KNOWN_KEYS = set(REQUIRED) | {"health", "test_cmd", "paid", "agent_timeout",
                              # FLEET-4HY: how the ask window continues after the first answer
                              "followup", "followup_cmd", "session_cmd", "sid_cmd"}
KNOWN_PROBE_KEYS = {"what", "cmd", "ok", "ok_in_cmd",
                    "blocked_on", "blocked_since", "blocked_grace_days"}
# How long a `blocked_on` probe may stay BLOCKED before ask-selftest escalates it back to FAIL.
DEFAULT_GRACE_DAYS = 14

def main(path):
    errs = []
    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
    except Exception as e:
        print("FAIL — agents.yml does not parse: %s" % e)
        return
    if not isinstance(doc, dict) or "agents" not in doc:
        print("FAIL — no top-level 'agents:' key")
        return
    rows = doc["agents"]
    if not isinstance(rows, list):
        print("FAIL — 'agents:' is not a list (got %s)" % type(rows).__name__)
        return

    ids = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            errs.append("row %d is not a mapping (got %s) — indentation collapsed it"
                        % (i, type(r).__name__))
            continue
        rid = r.get("id", "<no id>")
        ids.append(rid)
        at = r.get("agent_timeout")
        if at is not None and (not isinstance(at, int) or isinstance(at, bool) or at <= 0):
            errs.append("row '%s' has agent_timeout %r; want a positive integer of seconds" % (rid, at))
        for k in REQUIRED:
            if k not in r:
                errs.append("row '%s' is missing required key '%s'" % (rid, k))
        d = r.get("drop")
        if isinstance(d, str):
            if ":" not in d:
                errs.append("row '%s' drop '%s' has no HOST: prefix — a capture would land "
                            "on whatever machine ran ask" % (rid, d))
            elif not d.split(":", 1)[1].startswith("/"):
                errs.append("row '%s' drop '%s' is not an ABSOLUTE path — a relative or ~/ "
                            "drop resolves against the agent's cwd, which nothing controls "
                            "(this is how a sandboxed agent once read sandbox/sandbox/asks "
                            "and how a remote one got a bare inbox/... it had to guess)" % (rid, d))
        dv = r.get("drop_via")
        if dv is not None and dv not in KNOWN_DROP_VIA:
            errs.append("row '%s' drop_via '%s' is not one ask implements %s — the capture "
                        "would fall through and never be dropped"
                        % (rid, dv, sorted(KNOWN_DROP_VIA)))
        c = r.get("ask_cmd")
        if isinstance(c, str):
            if "{q}" not in c:
                errs.append("row '%s' ask_cmd has no {q} placeholder — the agent would be "
                            "started with no reference to read" % rid)
            first = c.split(" ", 1)[0] if c.strip() else ""
            if not first.startswith("/"):
                errs.append("row '%s' ask_cmd starts with '%s', which is not an ABSOLUTE path "
                            "— a bare name is not found on the thin PATH a non-interactive "
                            "ssh gets, and that killed 3 of 5 routes on 2026-09-06" % (rid, first))
        # --- agent_ssh: the machine and account that OPENS the dropped file ------------
        a_ssh = r.get("agent_ssh")
        if a_ssh is not None:
            if not isinstance(a_ssh, str) or "@" not in a_ssh or not a_ssh.split("@")[-1].strip():
                errs.append("row '%s' agent_ssh %r is not a USER@HOST ssh destination -- it names "
                            "the machine the agent process runs on and the account it runs as, "
                            "which is the ONE fact that makes the wrong-machine class decidable "
                            "without an LLM call (it is not ask_host: for a bridged row ask_host is the "
                            "BRIDGE host while the agent is on another box)" % (rid, a_ssh))
            elif isinstance(d, str) and ":" in d:
                # Not resolved here -- string equality would call `gpubox` and
                # `gpuuser@192.0.2.82` different machines. Proven by effect in
                # ask-selftest's drop-agentside check, which resolves both.
                pass
        # --- vision must be a real BOOL, not a string that looks like one -------------
        if "vision" in r and not isinstance(r["vision"], bool):
            errs.append("row '%s' vision is %s %r, not a YAML bool. `ask` compares it as TEXT "
                        "(ask:191, against the literal \"False\"), so a quoted \"false\" reads "
                        "as TRUE and ships a .png to an agent that cannot open it -- into an "
                        "ACL-ed one-way inbox, in hermes's case"
                        % (rid, type(r["vision"]).__name__, r["vision"]))
        # --- followup contract (FLEET-4HY) ----------------------------------------------
        # `resume` rows need all three commands, absolute like ask_cmd, and the two that
        # target a thread must name it with {sid} -- a followup_cmd without {sid} would
        # silently start a NEW conversation per turn, which is the defect this exists to end.
        fu = r.get("followup", "native")
        if fu not in ("native", "resume"):
            errs.append("row '%s' followup is %r — must be 'native' or 'resume'" % (rid, fu))
        elif fu == "resume":
            for k in ("followup_cmd", "session_cmd", "sid_cmd"):
                v = r.get(k)
                if not isinstance(v, str) or not v.strip():
                    errs.append("row '%s' followup: resume needs %s" % (rid, k)); continue
                if not v.split()[0].startswith("/"):
                    errs.append("row '%s' %s starts with '%s', not an ABSOLUTE path (same "
                                "non-interactive-PATH trap as ask_cmd)" % (rid, k, v.split()[0]))
                if k != "sid_cmd" and "{sid}" not in v:
                    errs.append("row '%s' %s has no {sid} placeholder — every turn would open a "
                                "fresh session instead of continuing this one" % (rid, k))
        else:
            for k in ("followup_cmd", "session_cmd", "sid_cmd"):
                if k in r:
                    errs.append("row '%s' has %s but followup is native — nothing would run it"
                                % (rid, k))
        # --- unknown keys are refused, not ignored -------------------------------------
        for k in sorted(set(r) - KNOWN_KEYS):
            errs.append("row '%s' has unknown key '%s' — nothing reads it, so whatever check it "
                        "was meant to add is not running (add it to KNOWN_KEYS deliberately)"
                        % (rid, k))
        # --- health probes -------------------------------------------------------------
        h = r.get("health")
        if h is not None:
            if not isinstance(h, list):
                errs.append("row '%s' health is %s, expected a list of probes"
                            % (rid, type(h).__name__))
            else:
                for j, p in enumerate(h):
                    if not isinstance(p, dict):
                        errs.append("row '%s' health[%d] is not a mapping" % (rid, j))
                        continue
                    for need in ("what", "cmd", "ok"):
                        if not p.get(need):
                            errs.append("row '%s' health[%d] is missing '%s' — a probe without "
                                        "both a command and a word to match cannot decide "
                                        "anything" % (rid, j, need))
                    # --- blocked_on must carry a CLOCK ------------------------------
                    if p.get("blocked_on") is not None:
                        if not isinstance(p["blocked_on"], str) or not p["blocked_on"].strip():
                            errs.append("row '%s' health[%d] blocked_on is empty -- say WHO must "
                                        "act and WHAT they must do, or drop the key" % (rid, j))
                        since = p.get("blocked_since")
                        if since is None:
                            errs.append("row '%s' health[%d] declares blocked_on with no "
                                        "blocked_since -- a blocked state with no clock never "
                                        "escalates and is just a mute button" % (rid, j))
                        else:
                            try:
                                dt = datetime.date(*[int(x) for x in str(since).split("-")])
                                if dt > datetime.date.today():
                                    errs.append("row '%s' health[%d] blocked_since %s is in the "
                                                "future" % (rid, j, since))
                            except Exception:
                                errs.append("row '%s' health[%d] blocked_since %r is not "
                                            "YYYY-MM-DD" % (rid, j, since))
                        g = p.get("blocked_grace_days", DEFAULT_GRACE_DAYS)
                        if not isinstance(g, int) or isinstance(g, bool) or g < 1:
                            errs.append("row '%s' health[%d] blocked_grace_days %r must be a "
                                        "positive int" % (rid, j, g))
                    elif p.get("blocked_since") is not None or p.get("blocked_grace_days") is not None:
                        errs.append("row '%s' health[%d] carries blocked_since/blocked_grace_days "
                                    "with no blocked_on -- nothing reads them, so the escalation "
                                    "clock is not running" % (rid, j))
                    for pk in sorted(set(p) - KNOWN_PROBE_KEYS):
                        errs.append("row '%s' health[%d] has unknown key '%s' — nothing reads "
                                    "it (add it to KNOWN_PROBE_KEYS deliberately)" % (rid, j, pk))
                    if isinstance(p.get("ok"), str):
                        # 🔴 A PROBE THAT MATCHES ITS OWN COMMAND PROVES NOTHING. Measured
                        # 2026-09-07 on a probe written that same hour: `codex exec ... 'Reply
                        # with exactly: CODEXPROBE'` with ok=/CODEXPROBE/ reported PASS while
                        # the API refused the request, because codex echoes the user prompt and
                        # the wanted word sat in that echo. Green by construction, inside the
                        # check built to end green-by-construction. A probe whose word really is
                        # decided locally and echoed by the command (a shell `if ... echo WORD`)
                        # sets `ok_in_cmd: true` — deliberate and countable, not assumed.
                        if not p.get("ok_in_cmd"):
                            try:
                                if re.search(p["ok"], str(p.get("cmd", "")), re.S):
                                    errs.append("row '%s' health[%d] ok %r MATCHES ITS OWN "
                                                "COMMAND — it would pass on the echo of its own "
                                                "input. Fix the probe, or set ok_in_cmd: true if "
                                                "the command genuinely decides locally"
                                                % (rid, j, p["ok"]))
                            except re.error:
                                pass
                        try:
                            re.compile(p["ok"])
                        except re.error as e:
                            errs.append("row '%s' health[%d] ok %r is not a valid regex (%s) — it "
                                        "would never match and the route would fail forever for "
                                        "a reason that is not its fault" % (rid, j, p["ok"], e))
        # --- test_cmd (the NON-INTERACTIVE one-shot form used by --full) ---------------
        t = r.get("test_cmd")
        if t is not None:
            if not isinstance(t, str) or not t.strip():
                errs.append("row '%s' test_cmd is empty" % rid)
            else:
                if "{q}" not in t:
                    errs.append("row '%s' test_cmd has no {q} placeholder — the canary round "
                                "trip would run with no reference to read" % rid)
                tf = t.split(" ", 1)[0]
                if not tf.startswith("/"):
                    errs.append("row '%s' test_cmd starts with '%s', not an ABSOLUTE path — same "
                                "thin-PATH trap that killed 3 of 5 routes on 2026-09-06"
                                % (rid, tf))
        if "paid" in r and not isinstance(r["paid"], bool):
            errs.append("row '%s' paid is %s, expected a bool — a non-bool is TRUTHY, which "
                        "would silently exclude the row from --full" % (rid, type(r["paid"]).__name__))
    got = set(ids)
    exp = doc.get("expected_ids")
    if exp is None:
        print("NOTE — no top-level expected_ids: in %s; a vanished row would NOT be a named failure" % path)
    elif not isinstance(exp, list) or not all(isinstance(x, str) for x in exp):
        errs.append("expected_ids must be a list of row ids")
    else:
        expected = set(exp)
        for miss in sorted(expected - got):
            errs.append("agent row '%s' is GONE from the registry" % miss)
        for extra in sorted(got - expected):
            errs.append("unexpected agent row '%s' (add it to expected_ids deliberately)" % extra)
        if len(rows) != len(expected):
            errs.append("expected %d agent rows, found %d" % (len(expected), len(rows)))

    if errs:
        print("FAIL — %d problem(s) in %s" % (len(errs), path))
        for e in errs:
            print("    - %s" % e)
        return
    probed = sum(1 for r in rows if isinstance(r, dict) and r.get("health"))
    blocked = sum(1 for r in rows if isinstance(r, dict)
                  for p in (r.get("health") or []) if isinstance(p, dict) and p.get("blocked_on"))
    print("PASS — %s: %d rows [%s], every required key present, %d carrying health probes, "
          "%d probe(s) declared blocked_on with a date"
          % (path, len(rows), " ".join(ids), probed, blocked))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "agents.yml")
