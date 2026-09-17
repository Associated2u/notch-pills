#!/usr/bin/env python3
"""Registry reader for ask/the bar. Keeps YAML parsing out of shell."""
import sys, shlex, yaml

# 🔴 `vision` IS COERCED TO A CANONICAL BOOL HERE, ONCE, AND THE COERCION FAILS CLOSED.
# Until 2026-09-07 this handed the field over as a raw str(), so a row written `vision: "false"`
# arrived in the shell as the string "false". `ask` then compared it TWO DIFFERENT WAYS -- a
# lowercased set match in send_png() and a literal `= "False"` at the sidecar NOTE -- and the
# two vocabularies disagreed on exactly that value: MEASURED 2026-09-07, a quoted "false"
# suppressed the "no vision backend -- the text IS the payload" note while still (correctly)
# withholding the .png. One field, two readings, is the drift that produced the original bug.
#
# THE RULE NOW: the agent is treated as sighted ONLY for a real YAML bool True. Every other
# value -- "true", "false", "yes", 1, None, a list -- is NO VISION, and A_VISION_BAD carries the
# offending value so `ask` can say out loud that the registry is wrong.
#
# 🎯 IT IS DELIBERATELY NOT SYMMETRICAL, AND A QUOTED "true" IS *NOT* HONOURED. The two mistakes
# cost different amounts: a vision agent that receives only the OCR sidecar is degraded and can
# ask for more, while a text-only agent that receives a .png holds a file it cannot open -- and
# for hermes that file lands in an ACL-ed one-way inbox it can never delete. Fail toward NOT
# sending. _regcheck.py refuses a non-bool statically; this makes the refusal true at run time
# too, because a static check nobody ran is not a guard.
def vision_of(row):
    v = row.get("vision")
    if v is True:
        return "True", ""
    bad = "" if isinstance(v, bool) else "%s %s" % (type(v).__name__, v)
    # Sanitise: this string is interpolated into a shell assignment via %r, and a stray quote
    # in a registry value must never become a shell metacharacter.
    bad = "".join(c if (c.isalnum() or c in " _.:-/") else "?" for c in bad)[:60]
    return "False", bad

mode, path = sys.argv[1], sys.argv[2]
d = yaml.safe_load(open(path))
if mode == "list":
    for a in d["agents"]:
        vis, bad = vision_of(a)
        print("%-9s %-8s %-22s vision=%-5s%s %s"
              % (a["id"], a["color"], a["model"], vis, " !NOT-A-BOOL" if bad else "", a["drop"]))
    sys.exit(0)
if mode == "intents":
    for i in d.get("intents", []):
        print("%s\t%s\t%s" % (i["id"], i["label"], i.get("capture", "region")))
    sys.exit(0)
if mode == "prompt":
    for i in d.get("intents", []):
        if i["id"] == sys.argv[3]:
            print(" ".join(i["prompt"].split()))
            sys.exit(0)
    sys.exit(1)
want = sys.argv[3]
for a in d["agents"]:
    if a["id"] == want:
        vis, bad = vision_of(a)
        # FLEET-4HY: the follow-up contract (see ask-shell). Absent => native, i.e. the old
        # window behaviour, so a row that never heard of follow-ups is unchanged.
        # 🔴 shlex.quote, NOT %r. MEASURED FLEET-4HY 2026-09-16: %r picks DOUBLE quotes for a
        # string that contains a single quote, and `eval` then expands $-words inside it on the
        # LAPTOP -- sid_cmd's `awk '{print $NF}'` became `awk '{print }'` and the session id
        # came back as the whole table row. Every earlier field merely happened to be
        # quote-free. shlex.quote always yields a single-quoted, expansion-proof word.
        fields = [("A_LABEL", a["label"]), ("A_COLOR", a["color"]), ("A_MODEL", a["model"]),
                  ("A_VISION", vis), ("A_VISION_BAD", bad), ("A_DROP", a["drop"]),
                  ("A_DROPVIA", a["drop_via"]), ("A_LAUNCH", a["launch"]),
                  ("A_ASKHOST", a.get("ask_host", "")), ("A_ASKCMD", a.get("ask_cmd", "")),
                  ("A_FOLLOWUP", a.get("followup", "native")),
                  ("A_FOLLOWUP_CMD", a.get("followup_cmd", "")),
                  ("A_SESSION_CMD", a.get("session_cmd", "")), ("A_SID_CMD", a.get("sid_cmd", ""))]
        print("; ".join("%s=%s" % (k, shlex.quote(str(v))) for k, v in fields))
        sys.exit(0)
print("no such agent %r — try: %s" % (want, ", ".join(x["id"] for x in d["agents"])), file=sys.stderr)
sys.exit(1)
