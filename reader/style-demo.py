#!/usr/bin/env python3
"""
mrog reader - reading STYLE DEMO  (SID: LINUX-E3X)

Speaks ONE representative block of Claude output six different ways so you can
choose a default with your ears. Nothing is installed and nothing is written
outside this file's own temp dir.

  ./style-demo.py            play all six, in order
  ./style-demo.py 3          play only style 3
  ./style-demo.py --list     print the styles without speaking
"""
import os, subprocess, sys, math, struct, wave, tempfile, textwrap, time

TMP = tempfile.mkdtemp(prefix="mrog-reader-")
SR  = 16000            # match the HFP sink exactly; no resampling

# ---------------------------------------------------------------- earcons ---
# Short non-speech tones that stand in for spoken structure words.
# "Bullet point three" is ~1.1 s of speech. A tick is 0.09 s.
# 150 ms of leading silence: the HFP SCO link needs a moment to come up or the
# attack of a short sound is swallowed.
def tone(path, freqs, ms=90, vol=0.28, lead_ms=150):
    n_lead = int(SR * lead_ms / 1000)
    n = int(SR * ms / 1000)
    frames = bytearray(b"\x00\x00" * n_lead)
    for i in range(n):
        t = i / SR
        env = min(1.0, i / (SR * 0.008)) * min(1.0, (n - i) / (SR * 0.020))
        s = sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
        frames += struct.pack("<h", int(max(-1, min(1, s * env * vol)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(bytes(frames))
    return path

EARCON = {
    "heading": tone(f"{TMP}/heading.wav", [660, 990], 130),   # rising, "new section"
    "bullet":  tone(f"{TMP}/bullet.wav",  [880],      70),    # tick, "next item"
    "code":    tone(f"{TMP}/code.wav",    [180, 240], 150),   # low thud, "code"
    "warn":    tone(f"{TMP}/warn.wav",    [520, 780], 200),   # buzz, "careful"
    "done":    tone(f"{TMP}/done.wav",    [520, 660], 120),   # settle, "end"
}
def earcon(k):
    subprocess.run(["paplay", EARCON[k]], check=False)

# -------------------------------------------------------------- the voice ---
def say(text, rate=0, pitch=0, voice=None):
    """rate/pitch are speech-dispatcher's -100..100. espeak ~ 80..450 wpm."""
    cmd = ["spd-say", "-w", "-r", str(rate), "-p", str(pitch)]
    if voice:
        cmd += ["-y", voice]
    cmd.append(text)
    subprocess.run(cmd, check=False)

def tag(label):
    say(f"Style {label}", rate=-10, pitch=60)
    time.sleep(0.25)

# ------------------------------------------------------- the source block ---
# Deliberately typical: a heading, hedged prose, a bullet list, a code fence,
# and a warning. This is the shape that costs you nine hours.
VERBATIM = """
Bluetooth audio profile findings.

Okay, so I've gone ahead and taken a look at the Bluetooth card that was
created for the glasses, and it turns out that there's actually something
important here that I think you should be aware of. The card that PipeWire
enumerated is only offering the hands-free profiles, and it is not offering
the A2DP sink profile at all, even though the device itself does advertise
the Audio Sink UUID and BlueZ did successfully discover four separate A2DP
endpoints during the pairing handshake.

Here are the profiles that are currently being offered:

- Off, which is the null profile.
- Headset Head Unit, the generic HSP and HFP profile.
- Headset Head Unit with the CVSD codec, which runs at eight kilohertz.
- Headset Head Unit with the mSBC codec, which runs at sixteen kilohertz.

The currently active profile is the mSBC one, which means that the sink is
running at sixteen thousand hertz, single channel, signed sixteen bit little
endian. You can confirm this yourself by running the following command:

```
pactl list cards | grep -A20 bluez_card
```

Please note that this is important, because the hands-free profile also holds
the microphone open for the duration, and that is going to drain the battery
on the glasses considerably faster than a normal audio-only connection would.
"""

# ----------------------------------------------------------- the six styles --
# NOTE: styles 2-6 were authored by the model, which is exactly what the
# production reader would do live. Style 1 is the raw text.

STYLES = []

STYLES.append(("1", "Verbatim", "everything, natural pace - the baseline", lambda: (
    say(VERBATIM, rate=0),
)))

STYLES.append(("1b", "Verbatim, fast", "same words, espeak pushed near its ceiling", lambda: (
    say(VERBATIM, rate=75),
)))

STYLES.append(("2", "De-fluffed", "same structure, filler and hedging stripped", lambda: (
    say("Bluetooth audio profile findings.", rate=10, pitch=25),
    say("PipeWire's card offers hands-free profiles only. No A2DP sink, "
        "despite the device advertising Audio Sink and BlueZ finding four "
        "A2DP endpoints during pairing. Profiles offered: off. "
        "Headset head unit. Same with CVSD at eight kilohertz. "
        "Same with mSBC at sixteen. Active profile is mSBC, so the sink is "
        "sixteen kilohertz, mono, signed sixteen bit. "
        "Hands-free also holds the microphone open, which drains the glasses "
        "battery faster than audio-only would.", rate=25),
)))

STYLES.append(("3", "Earcons + channels", "structure becomes tones; code and warnings change voice", lambda: (
    earcon("heading"),
    say("Bluetooth audio profile findings", rate=10, pitch=30),
    say("Card offers hands-free only. No A2DP sink, though the device "
        "advertises Audio Sink and BlueZ found four endpoints.", rate=25),
    earcon("bullet"), say("off", rate=30),
    earcon("bullet"), say("headset head unit", rate=30),
    earcon("bullet"), say("with CVSD, eight kilohertz", rate=30),
    earcon("bullet"), say("with mSBC, sixteen kilohertz. active", rate=30),
    say("Sink is sixteen kilohertz mono.", rate=25),
    earcon("code"),
    say("one bash line, greps the bluez card out of pactl", rate=20, pitch=-40),
    earcon("warn"),
    say("Hands-free holds the microphone open. Battery cost.",
        rate=10, pitch=-25),
)))

STYLES.append(("4", "Gist", "one line per idea - about a fifth of the words", lambda: (
    say("Glasses gave us hands-free only, not A2DP. "
        "So: sixteen kilohertz mono, and the microphone stays open, "
        "which costs battery.", rate=20),
)))

STYLES.append(("5", "Headline, drill-down", "speaks the shape; you say 'more' to open a node", lambda: (
    earcon("heading"),
    say("Bluetooth audio profile findings.", rate=10, pitch=30),
    say("Three things. One: no A2DP, hands-free only. "
        "Two: four profiles offered, mSBC active. "
        "Three: a battery warning.", rate=20),
    earcon("done"),
    say("Say more, two, to open the profile list.", rate=15, pitch=-20),
)))

STYLES.append(("6", "Pacer", "audio carries the gist while your eyes read the full text",
    lambda: (
    say("Reading the audio track only. On screen, the full text would be "
        "highlighting in step with this voice.", rate=15, pitch=-20),
    time.sleep(0.3),
    earcon("heading"),
    say("Audio profiles.", rate=15, pitch=30),
    say("No A2DP.", rate=10), time.sleep(0.9),
    say("Hands-free only.", rate=10), time.sleep(0.9),
    say("Sixteen kilohertz, mono.", rate=10), time.sleep(0.9),
    earcon("warn"),
    say("Microphone stays open. Battery.", rate=5),
)))

# ------------------------------------------------------------------- main ---
def main():
    args = sys.argv[1:]
    if "--list" in args:
        for n, name, blurb, _ in STYLES:
            print(f"  {n:<3} {name:<22} {blurb}")
        return
    pick = args[0] if args else None
    for n, name, blurb, play in STYLES:
        if pick and n != pick:
            continue
        print(f"\n=== Style {n}: {name} — {blurb}")
        sys.stdout.flush()
        tag(f"{n}. {name}")
        t0 = time.time()
        play()
        print(f"    ({time.time() - t0:.1f}s)")
        time.sleep(0.6)
    earcon("done")

if __name__ == "__main__":
    main()
