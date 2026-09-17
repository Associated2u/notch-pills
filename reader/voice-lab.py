#!/usr/bin/env python3
"""
speedreader - VOICE LAB.

espeak-ng exposes 816 English voice/accent combinations here. That is useless
as a menu, so this auditions a curated spread, then lets you sweep rate and
pitch on whichever one you liked and save it.

    ./voice-lab.py                     audition the shortlist
    ./voice-lab.py --try Andy          longer sample of one voice
    ./voice-lab.py --sweep Andy        the same voice at 5 speeds
    ./voice-lab.py --pitch Andy        the same voice at 5 pitches
    ./voice-lab.py --set Andy --rate 35 --set-pitch -10     save it
    ./voice-lab.py --show              what is configured now
    ./voice-lab.py --all               every en-US variant (long!)
"""
import argparse, os, subprocess, sys, time, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("r", os.path.join(HERE, "reader.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)

US = "English (America)"

# A spread across timbre, not a dump. Crispness matters more than prettiness
# when you are listening at speed - a "nicer" voice that smears consonants at
# 300 wpm is worse than a plain one that does not.
SHORTLIST = [
    (f"{US}",            "plain default - the espeak baseline"),
    ("English (Great Britain)", "same engine, British vowels"),
    (f"{US}+Andy",       "warmer male, softer attack"),
    (f"{US}+Michael",    "male, brighter and more forward"),
    (f"{US}+Alex",       "male, lower and flatter - low fatigue"),
    (f"{US}+Max",        "male, heavier"),
    (f"{US}+Alicia",     "female, clear mid"),
    (f"{US}+Storm",      "female, more intonation"),
    (f"{US}+klatt",      "classic formant robot - very crisp"),
    (f"{US}+klatt3",     "klatt, smoother variant"),
    (f"{US}+whisper",    "breathy and quiet - least tiring, least clear"),
    (f"{US}+Gene2",      "unusual timbre, easy to tell apart"),
]

# Round 2, built from the first audition: klatt best, Alex liked, Storm understood.
# The common property is high consonant contrast and INVARIANT phonemes, so
# this set probes that axis rather than sampling at random.
ROUND2 = [
    (f"{US}+klatt2",     "klatt family - your best, second voicing"),
    (f"{US}+klatt4",     "klatt, brighter transients"),
    (f"{US}+klatt5",     "klatt, lower and heavier"),
    (f"{US}+klatt6",     "klatt, thinnest and sharpest"),
    (f"{US}+Robosoft",   "openly robotic - maximum phoneme invariance"),
    (f"{US}+Robosoft3",  "robosoft, lower register"),
    (f"{US}+Tweaky",     "thin and very clipped - extreme end of the axis"),
    (f"{US}+anikaRobot", "robotic but higher pitch - tests if pitch matters"),
    (f"{US}+Denis",      "flat male, Alex-adjacent, less robotic"),
    (f"{US}+norbert",    "flat male, firmer consonants than Alex"),
]

SAMPLE = ("Bluetooth audio profile findings. The card offers hands free only, "
          "no A2DP sink, though the device advertises Audio Sink and BlueZ "
          "found four endpoints. Sixteen kilohertz, mono.")
SHORT  = "The quick brown fox jumps over the lazy dog. Sixteen kilohertz, mono."

def say(text, voice, rate=20, pitch=0):
    subprocess.run(["spd-say", "-w", "-o", "espeak-ng", "-y", voice,
                    "-r", str(rate), "-p", str(pitch), text], check=False)

def resolve(name: str) -> str:
    """Accept 'Andy' or the full 'English (America)+Andy'."""
    if name.startswith("English"):
        return name
    return f"{US}+{name}"

def audition(voices, text, rate, pitch):
    for i, (v, blurb) in enumerate(voices, 1):
        short = v.replace("English (America)", "US").replace(
            "English (Great Britain)", "GB")
        print(f"  {i:2}. {short:22} {blurb}")
        sys.stdout.flush()
        say(f"Voice {i}. {short.split('+')[-1]}", v, rate=-10, pitch=40)
        time.sleep(0.15)
        say(text, v, rate, pitch)
        time.sleep(0.35)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--try", dest="one")
    ap.add_argument("--sweep")
    ap.add_argument("--pitch", dest="pitchsweep")
    ap.add_argument("--set")
    ap.add_argument("--rate", type=int, default=20)
    ap.add_argument("--set-pitch", dest="setpitch", type=int, default=0)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--set-pacer", dest="setpacer", choices=["auto","on","off"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--more", action="store_true", help="round 2 shortlist")
    a = ap.parse_args()

    if a.show:
        cfg = R.load_config()
        print(f"  config : {R.CONFIG}")
        for k, v in cfg.items():
            print(f"  {k:7}: {v}")
        return

    if a.setpacer and not a.set:
        print(f"  saved -> {R.save_config(pacer=a.setpacer)}"); return

    if a.set:
        v = resolve(a.set)
        kw = dict(voice=v, rate=a.rate, pitch=a.setpitch)
        if a.setpacer: kw["pacer"] = a.setpacer
        cfg = R.save_config(**kw)
        print(f"  saved -> {cfg}")
        say("This is now your reader voice.", v, a.rate, a.setpitch)
        return

    if a.one:
        v = resolve(a.one)
        print(f"  {v} @ rate {a.rate} pitch {a.setpitch}")
        say(SAMPLE, v, a.rate, a.setpitch); return

    if a.sweep:
        v = resolve(a.sweep)
        for r in (0, 20, 40, 60, 80):
            print(f"  rate {r:>3}  (~{80 + (r + 100) * 1.85:.0f} wpm)"); sys.stdout.flush()
            say(f"Rate {r}.", v, -10, 40); say(SHORT, v, r, a.setpitch)
            time.sleep(0.3)
        return

    if a.pitchsweep:
        v = resolve(a.pitchsweep)
        for p in (-50, -25, 0, 25, 50):
            print(f"  pitch {p:>4}"); sys.stdout.flush()
            say(f"Pitch {p}.", v, -10, 40); say(SHORT, v, a.rate, p)
            time.sleep(0.3)
        return

    if a.all:
        out = subprocess.run(["spd-say", "-L"], capture_output=True, text=True).stdout
        vs = [(l.rsplit(None, 2)[0].strip(), "")
              for l in out.split("\n") if " en-US " in f" {l} " and "America)" in l]
        print(f"  {len(vs)} en-US voices - ctrl-c to stop")
        audition(vs, SHORT, a.rate, a.setpitch); return

    if a.more:
        print(f"round 2 - {len(ROUND2)} voices at rate {a.rate}. ctrl-c to stop.\n")
        audition(ROUND2, SAMPLE, a.rate, a.setpitch)
        print("\n  sweep the ones you like:  ./voice-lab.py --sweep klatt4")
        print("  then save:                ./voice-lab.py --set klatt4 --rate 40")
        return

    print(f"auditioning {len(SHORTLIST)} voices at rate {a.rate}. ctrl-c to stop.\n")
    audition(SHORTLIST, SAMPLE, a.rate, a.setpitch)
    print("\n  pick one:   ./voice-lab.py --try Andy")
    print("  then speed: ./voice-lab.py --sweep Andy")
    print("  then save:  ./voice-lab.py --set Andy --rate 35")

if __name__ == "__main__":
    main()
