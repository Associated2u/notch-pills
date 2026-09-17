#!/usr/bin/env python3
"""
speedreader - core engine.

Point it at text, it starts talking with minimal delay. Extraction and speech
run concurrently: chunk 1 is already being spoken while chunk 2 is still being
built, so time-to-first-word is milliseconds, not "after it read everything".

Design notes that are load-bearing:
  * Tier 0 needs NO model. Claude writes structure (headings, bold, bullets)
    and that structure IS the gist - measured 68% cut over 13 transcripts.
  * Earcons replace spoken scaffolding. "Bullet point three" is ~1.1 s of
    speech; a tick is 0.09 s. Across 2,022 tool blocks that is hours.
  * Redaction runs BEFORE the speaker, always. The glasses talk into a room.
"""
from __future__ import annotations
import os, re, sys, json, glob, math, wave, queue, struct, shutil, tempfile
import threading, subprocess, argparse, time, signal

HOME     = os.path.expanduser("~")
# Claude Code keeps one JSONL transcript per session under a directory per
# project. We read the most recently modified one, whatever project it is.
PROJGLOB = os.path.join(HOME, ".claude", "projects", "*", "*.jsonl")
STATEDIR = os.path.join(os.environ.get("XDG_STATE_HOME",
                                       os.path.join(HOME, ".local/state")), "mrog-reader")
os.makedirs(STATEDIR, exist_ok=True)

# Voice, rate, pitch and level live in one file so the notch button, the CLI
# and the voice lab all agree. Written by `voice-lab.py --set`.
CONFIG  = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                      os.path.join(HOME, ".config")), "mrog", "reader.json")
# Defaults are what testing settled on, not neutral guesses: the klatt voice
# stays intelligible at speed where natural-sounding ones smear, and only
# verbatim can drive the follow-along window. See docs/WHY-KLATT.md.
# Speed presets (rate values; klatt wpm in comments). Named so a newcomer
# does not have to know what "rate 68" means.
PRESETS = {"easy": 15, "medium": 40, "fast": 68, "superfast": 95}   # ~250/330/410/490 wpm

DEFAULTS = {"voice": "English (America)+klatt", "rate": 30, "pitch": 0,
            "style": "verbatim", "pacer": "auto",
            "redact": True, "earcons": True, "code": "describe",
            "numbers": "skip",
            "win_bg": "#141417", "win_text": "#5c6068", "win_live": "#f2f4f8",
            "win_sentence": "#2b3040", "win_word": "#5a6fb5"}

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg

def save_config(**kw) -> dict:
    cfg = load_config(); cfg.update({k: v for k, v in kw.items() if k in DEFAULTS})
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg

# =============================================================== redaction ==
# TIER-REAL per CLAUDE.md: third-party auth, spends money, public surface.
# Non-destructive - the token is replaced by the word "redacted", so you hear
# that something was skipped rather than silently losing a sentence.
REDACT = [
    (re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{20,}'),                 'anthropic key'),
    (re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}'),           'api key'),
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}'), 'json web token'),
    (re.compile(r'\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}'),        'stripe key'),
    (re.compile(r'\bya29\.[A-Za-z0-9_\-]{20,}'),                  'google oauth token'),
    (re.compile(r'\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}'), 'sendgrid key'),
    (re.compile(r'\bnpm_[A-Za-z0-9]{36}'),                        'npm token'),
    (re.compile(r'\bpypi-[A-Za-z0-9_\-]{16,}'),                   'pypi token'),
    (re.compile(r'\bglpat-[A-Za-z0-9_\-]{16,}'),                  'gitlab token'),
    (re.compile(r'\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}'),       'github token'),
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{50,}'),               'github token'),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}'),              'slack token'),
    (re.compile(r'\bAIza[A-Za-z0-9_\-]{30,}'),                    'google key'),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'),                         'aws key'),
    (re.compile(r'\b\d{6,12}:[A-Za-z0-9_\-]{25,60}\b'),           'telegram token'),
    (re.compile(r'\b[Bb]earer\s+[A-Za-z0-9._\-]{20,}'),           'bearer token'),
    (re.compile(r'-----BEGIN[^-]{0,40}PRIVATE KEY-----.*?-----END[^-]{0,40}-----',
                re.S),                                            'private key'),
    (re.compile(r'\b[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s:@/]+@\S+'), 'credentialed url'),
    (re.compile(r'(?i)\b(\w*(?:token|secret|passw(?:or)?d|api_?key)\w*)\s*[=:]\s*'
                r'["\']?[^\s"\'\n]{8,}'),                          'secret assignment'),
    (re.compile(r'\b[A-Fa-f0-9]{40,}\b'),                         'long hex blob'),
    # Backstop for near-misses on every pattern above. Requires a 20+ char
    # UNBROKEN alphanumeric run carrying both a digit and a letter - hyphens
    # and underscores do not bridge it. Without that, the first cut redacted
    # 'BirdsFlyPoopSimulator-GDD-v1-1'; a redactor that bleeps your own project
    # names gets switched off, and a switched-off redactor protects nothing.
    (re.compile(r'\b(?=[A-Za-z0-9]{20,}\b)(?=[A-Za-z0-9]*\d)'
                r'(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}\b'),   'long token'),
]

def redact(text: str) -> tuple[str, int]:
    n = 0
    for pat, label in REDACT:
        text, k = pat.subn(f' {label} redacted ', text)
        n += k
    return text, n

# ================================================================ earcons ==
SR = 48000                      # A2DP runs 48k stereo; match it, no resampling
_TMP = tempfile.mkdtemp(prefix="speedreader-")

def _tone(path, freqs, ms=90, vol=0.26, lead_ms=60):
    n_lead, n = int(SR * lead_ms / 1000), int(SR * ms / 1000)
    fr = bytearray(b"\x00\x00\x00\x00" * n_lead)
    for i in range(n):
        t = i / SR
        env = min(1.0, i / (SR * 0.008)) * min(1.0, (n - i) / (SR * 0.020))
        s = sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
        v = int(max(-1, min(1, s * env * vol)) * 32767)
        fr += struct.pack("<hh", v, v)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(bytes(fr))
    return path

EARCON = {
    "heading": _tone(f"{_TMP}/heading.wav", [660, 990], 130),
    "bullet":  _tone(f"{_TMP}/bullet.wav",  [880],       65),
    "code":    _tone(f"{_TMP}/code.wav",    [180, 240], 150),
    "warn":    _tone(f"{_TMP}/warn.wav",    [520, 780], 190),
    "table":   _tone(f"{_TMP}/table.wav",   [440, 550], 110),
    "done":    _tone(f"{_TMP}/done.wav",    [520, 660], 120),
}

# ============================================================== extraction ==
LINK_RE    = re.compile(r'\[([^\]]+)\]\((?:[^)]*)\)')      # keep text, drop url
IMG_RE     = re.compile(r'!\[[^\]]*\]\([^)]*\)')
FENCE_RE   = re.compile(r'^\s*```(\w*)')
INLINE_RE  = re.compile(r'`([^`]+)`')
BOLD_RE    = re.compile(r'\*\*(.+?)\*\*')
EMOJI_RE   = re.compile('[\U0001F300-\U0001FAFF☀-➿️]')
WARN_RE    = re.compile(r'(?i)\b(never|do not|don\'t|must not|careful|warning|'
                        r'danger|destructive|irreversible|cannot|breaks?|fails?|'
                        r'wrong|trap|refus)')

def _clean(s: str) -> str:
    """Make one span speakable. Defect fixes from the measured sample live here."""
    s = IMG_RE.sub(' ', s)
    s = LINK_RE.sub(r'\1', s)                 # was: 'Line 98 of [code'
    s = INLINE_RE.sub(r'\1', s)               # was: bullet truncated at a backtick
    s = s.replace('`', '')                    # a lone tick (split token) is never speech
    s = re.sub(r'[*_~]{1,3}', '', s)
    s = EMOJI_RE.sub(' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -–—:;,')
    return s

def _first_clause(s: str) -> str:
    """First sentence, but never split inside inline code (the old bug)."""
    parts = re.split(r'(?<=[.!?])\s+', s, maxsplit=1)
    head = parts[0]
    return head if len(head.split()) >= 3 else s

# Compression levels. The dial, not a single guess.
#   verbatim  - every paragraph in full          (~100%)
#   skim      - lead clause + any bolds it missed (~53%)
#   structure - the author's own bolding, lead as fallback (~35%)
#   gist      - headings, warnings and code only  (~10%)
GIST_KINDS = {"heading", "warn", "code"}

# Spelling out a shell path aloud is unusable, so a fenced block becomes a
# one-line description by default. --code speak overrides that.
CODE_MODE = "describe"

# Number handling. espeak verbalises "10240" as "ten thousand two hundred
# forty" and "98594920" as tens of millions - useless for IDs, versions,
# timestamps, hashes, MAC-like strings. Modes:
#   normal  read every number as espeak would
#   skip    drop unimportant numbers (default) - keep currency, %, years, small
#   digits  read unimportant numbers digit by digit ("one zero two four zero")
NUM_MODE = "skip"
_CURRENCY_UNIT = re.compile(r'[$£€¥%]|(?:dollar|cent|euro|pound|percent)', re.I)
_YEAR         = re.compile(r'(?:19|20)\d{2}')
# Only 1-2 digit bare integers are kept as meaningful spoken counts ("3 files",
# "42 tests"). 3-4 digit bare numbers in this kind of text are overwhelmingly
# ports, HTTP statuses, sizes and model numbers - dull to hear - so they are
# skipped; 4-digit YEARS are rescued by _YEAR above. Tested with fullmatch.
_SMALL_INT    = re.compile(r'\d{1,2}')

def _filter_numbers(text):
    """Apply the number policy to a plain (non word-synced) span."""
    if NUM_MODE == "normal":
        return text
    out = []
    for w in text.split():
        r = _speak_number_token(w)
        if r is not None:
            out.append(r)
    return " ".join(out)

def _speak_number_token(w):
    """Return the spoken form of a whitespace token, or None to skip it.
    Only touches tokens that actually contain a digit."""
    if NUM_MODE == "normal" or not any(c.isdigit() for c in w):
        return w
    # currency, %, or an explicit unit anywhere in the token -> important, keep
    if _CURRENCY_UNIT.search(w):
        return w
    core = w.strip('.,;:!?()[]{}"\'\u2019\u201c\u201d')
    # a WHOLE-token year or small integer is meaningful; a small int that is
    # merely a piece of "1.0.5" or "98:59" is not, so test the whole core.
    if _YEAR.fullmatch(core) or _SMALL_INT.fullmatch(core):
        return w
    # Only skip a token that is PURELY a number / separator-id / hex hash. A
    # token with letters is a word that happens to carry a digit (GPT-4, mp3,
    # COVID-19, IPv6) - keep it, or we would delete real words.
    alnum = re.sub(r'[^0-9A-Za-z]', '', w)
    letters = sum(c.isalpha() for c in alnum)
    is_hex = len(alnum) >= 6 and re.fullmatch(r'[0-9a-fA-F]+', alnum) is not None
    if letters and not is_hex:
        return w
    if NUM_MODE == "digits":
        return re.sub(r'\d', lambda m: m.group() + " ", w)
    return None


def _spans(md: str, level: str):
    """Yield (kind, spoken_text, src_start, src_end).

    The offsets are what makes the pacer possible: the audio speaks a
    compressed span, and the overlay highlights the ORIGINAL region it came
    from, so the ear gets the index while the eye gets the full text.
    """
    in_fence, fence_lang, fence_lines, fence_first = False, "", 0, ""
    fence_start, fence_body = 0, []
    off = 0

    for raw in md.split("\n"):
        ls = off
        le = off + len(raw)
        off = le + 1                     # +1 for the newline we split on
        line = raw.rstrip()

        m = FENCE_RE.match(line)
        if m and not in_fence:
            in_fence, fence_lang, fence_lines, fence_first = True, m.group(1) or "", 0, ""
            fence_start, fence_body = ls, []
            continue
        if in_fence:
            if line.strip().startswith("```"):
                in_fence = False
                if CODE_MODE == "speak":
                    body = _clean(" ".join(fence_body))
                    if body:
                        yield ("code", body, fence_start, le)
                else:
                    lang  = fence_lang or "code"
                    first = _clean(fence_first)[:60]
                    desc  = f"{lang} block, {fence_lines} line{'s' if fence_lines != 1 else ''}"
                    if first:
                        desc += f", starts {first}"
                    yield ("code", desc, fence_start, le)
            else:
                fence_lines += 1
                fence_body.append(line.strip())
                if not fence_first and line.strip():
                    fence_first = line.strip()
            continue

        s = line.strip()
        if not s:
            continue
        if set(s) <= set("-=_ "):
            continue
        if s.startswith("|"):
            if level == "verbatim":
                cells = [c.strip() for c in s.strip("|").split("|")]
                # drop the |---|---| separator row: a cell that is ONLY
                # dashes/colons is layout, not content. The first cut tested
                # superset by mistake and silently dropped every real row.
                cells = [c for c in cells if c and not set(c) <= set("-: ")]
                if cells:
                    yield ("table", _clean(", ".join(cells)), ls, le)
            continue

        if s.startswith("#"):
            yield ("heading", _clean(s.lstrip("# ")), ls, le)
            continue

        if re.match(r'^[-*+]\s|^\d+[.)]\s', s):
            body  = re.sub(r'^([-*+]|\d+[.)])\s+', '', s)
            bolds = [b for b in (_clean(x) for x in BOLD_RE.findall(body)) if b]
            if level == "verbatim":
                txt = _clean(body)                    # every word, not the lead
            else:
                txt = bolds[0] if bolds else _clean(_first_clause(body))
            if txt:
                yield ("warn" if WARN_RE.search(txt) else "bullet", txt, ls, le)
            continue

        bolds  = [b for b in (_clean(x) for x in BOLD_RE.findall(s)) if b]
        joined = ", ".join(bolds)
        lead   = _clean(s if level == "verbatim" else _first_clause(s))
        # The author's own bolding IS a compression. Prefer it when it carries
        # enough alone, and fall back to the lead clause so a paragraph is
        # NEVER dropped just because its bolds were too short - that bug took
        # 183 words down to 2.
        if level in ("structure", "gist") and len(joined.split()) >= 3:
            yield ("warn" if WARN_RE.search(joined) else "bold", joined, ls, le)
        elif lead and len(lead.split()) >= 2:
            kind = "warn" if WARN_RE.search(lead) else ("bold" if bolds else "lead")
            yield (kind, lead, ls, le)
            if level == "skim" and bolds:
                extra = ", ".join(b for b in bolds if b.lower() not in lead.lower())
                if len(extra.split()) >= 2:
                    yield ("warn" if WARN_RE.search(extra) else "bold", extra, ls, le)

def extract(md: str, level: str = "structure"):
    for kind, text, a, b in _spans(md, level):
        if level == "gist" and kind not in GIST_KINDS:
            continue
        yield (kind, text, a, b)

# ================================================================= speaker ==
# Own player thread + queue. speech-dispatcher would reorder against paplay,
# so ordering is enforced here: one item at a time, strictly FIFO.
VOICE = {           # kind -> (rate delta, pitch delta, earcon or None)
    "table":   ( 10,   0, "table"),
    "heading": (  0,  30, "heading"),
    "bold":    ( 10,  10, None),
    "bullet":  ( 15,   0, "bullet"),
    "lead":    ( 10,   0, None),
    "code":    (  0, -40, "code"),
    "warn":    (-10, -25, "warn"),
    "table":   ( 10,   0, "table"),
}

class Speaker:
    def __init__(self, rate=20, quiet_earcons=False, dry=False,
                 voice=None, pitch=0, source=None, word_sync=False):
        self.q = queue.Queue()
        self.rate, self.quiet, self.dry = rate, quiet_earcons, dry
        self.voice, self.pitch0 = voice, pitch
        self.on_chunk = None      # set by the pacer: (kind, text, src_a, src_b)
        self.on_word  = None      # set by the pacer: (src_a, src_b) per word
        # Word sync speaks the SOURCE tokens of each span with an SSML <mark/>
        # before every word, so speech-dispatcher tells us the moment each one
        # is reached. Only meaningful for verbatim - a compressed span does not
        # contain the source's words, so there is nothing to mark.
        self.source, self.word_sync = source, word_sync
        self.paused = False
        self._pause_pending = False
        self.stop = threading.Event()
        self.spoken = 0
        self.client = None
        if not dry:
            import speechd
            self.speechd = speechd
            self.client = speechd.SSIPClient("speedreader")
            self.client.set_output_module("espeak-ng")
            self.client.set_punctuation(speechd.PunctuationMode.NONE)
            if self.voice:
                try:
                    self.client.set_synthesis_voice(self.voice)
                except Exception:
                    pass
            self.client.set_data_mode(speechd.DataMode.SSML)
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def push(self, kind, text, sa=0, sb=0): self.q.put((kind, text, sa, sb))
    def finish(self):                       self.q.put(None)

    def request_pause_toggle(self):
        """Called from a signal handler. Only sets a flag; the actual pause/
        resume runs on the speaker thread so the SSIP socket has one writer."""
        self._pause_pending = True

    @staticmethod
    def _tokens(source, a, b):
        """(spoken, src_a, src_b) for every word in source[a:b]. Each token is
        cleaned on its own so that `**bold**` speaks as `bold` while its
        offsets still point at the original characters."""
        out = []
        for m in re.finditer(r'\S+', source[a:b]):
            spoken = _clean(m.group())
            if not spoken:
                continue
            spoken = _speak_number_token(spoken)
            if spoken is None:          # an unimportant number, skipped
                continue
            out.append((spoken, a + m.start(), a + m.end()))
        return out

    @staticmethod
    def _ssml(tokens):
        from xml.sax.saxutils import escape
        return ("<speak>" + " ".join(f'<mark name="{i}"/>{escape(t)}'
                                     for i, (t, _, _) in enumerate(tokens)) + "</speak>")

    def _say(self, text, rate, pitch, tokens=None):
        done = threading.Event()
        CT = self.speechd.CallbackType
        def cb(cbtype, index_mark=None):
            if cbtype == CT.INDEX_MARK:
                if self.on_word and tokens:
                    try:
                        _, wa, wb = tokens[int(index_mark)]
                        if wa is not None:
                            self.on_word(wa, wb)
                    except Exception:
                        pass
            elif cbtype in (CT.END, CT.CANCEL):
                done.set()
        self.client.set_rate(max(-100, min(100, rate)))
        self.client.set_pitch(max(-100, min(100, pitch + self.pitch0)))
        from xml.sax.saxutils import escape
        if tokens:
            payload = self._ssml(tokens)
            events = (CT.INDEX_MARK, CT.END, CT.CANCEL)
        else:
            payload, events = f"<speak>{escape(text)}</speak>", (CT.END, CT.CANCEL)
        self.client.speak(payload, callback=cb, event_types=events)
        while not done.wait(0.05):
            if self._pause_pending:
                self._pause_pending = False
                self.paused = not self.paused
                try:
                    self.client.pause() if self.paused else self.client.resume()
                except Exception:
                    pass
                try:
                    if self.paused:
                        open(PAUSEFILE, "w").close()
                    elif os.path.exists(PAUSEFILE):
                        os.unlink(PAUSEFILE)
                except Exception:
                    pass
            if self.stop.is_set():
                self.client.cancel(); return

    def _run(self):
        while not self.stop.is_set():
            item = self.q.get()
            if item is None:
                if not self.quiet and not self.dry:
                    subprocess.run(["paplay", EARCON["done"]], check=False)
                return
            kind, text, sa, sb = item
            if self.on_chunk:
                try: self.on_chunk(kind, text, sa, sb)
                except Exception: pass
            dr, dp, ec = VOICE.get(kind, (0, 0, None))
            if ec and not self.quiet and not self.dry:
                subprocess.run(["paplay", EARCON[ec]], check=False)
            # Build word tokens for EVERY read, not just the pacer. The marks
            # are what pause() can stop at - without them speech-dispatcher
            # only pauses at the end of the utterance, so a plain read could
            # not be paused mid-sentence. Highlight offsets are attached only
            # when a pacer wants them.
            if self.word_sync and self.source is not None and kind != "code":
                tokens = self._tokens(self.source, sa, sb)      # (spoken, a, b)
                spoken_text = " ".join(t for t, _, _ in tokens)
            else:
                spoken_text = _filter_numbers(text)
                tokens = [(w, None, None) for w in spoken_text.split()]
            if self.dry:
                print(f"  [{kind:7}] {spoken_text}")
            else:
                self._say(spoken_text, self.rate + dr, dp, tokens)
            self.spoken += 1

    def halt(self):
        self.stop.set()
        if self.client:
            try: self.client.cancel()
            except Exception: pass
        try:
            if os.path.exists(PAUSEFILE): os.unlink(PAUSEFILE)
        except Exception: pass

# ================================================================= sources ==
def src_selection() -> str:
    return subprocess.run(["xclip", "-o", "-selection", "primary"],
                          capture_output=True, text=True).stdout

def src_clipboard() -> str:
    return subprocess.run(["xclip", "-o", "-selection", "clipboard"],
                          capture_output=True, text=True).stdout

def _newest_transcript() -> str | None:
    f = sorted(glob.glob(PROJGLOB), key=os.path.getmtime)
    return f[-1] if f else None

def src_claude(delta=False, n=1) -> str:
    """Newest assistant text. --delta speaks only what has not been read."""
    p = _newest_transcript()
    if not p:
        return ""
    msgs = []
    for line in open(p, encoding="utf-8", errors="replace"):
        try: o = json.loads(line)
        except Exception: continue
        if o.get("type") != "assistant":
            continue
        for b in o.get("message", {}).get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                msgs.append((o.get("uuid") or str(len(msgs)), b["text"]))
    if not msgs:
        return ""
    if delta:
        sf = os.path.join(STATEDIR, os.path.basename(p) + ".pos")
        seen = open(sf).read().strip() if os.path.exists(sf) else ""
        idx = next((i for i, (u, _) in enumerate(msgs) if u == seen), -1)
        fresh = msgs[idx + 1:]
        open(sf, "w").write(msgs[-1][0])
        if not fresh:
            return ""
        return "\n\n".join(t for _, t in fresh)
    return "\n\n".join(t for _, t in msgs[-n:])

def src_window(wid: str | None = None) -> str:
    """AT-SPI if accessibility is on, else OCR. wid targets a chosen window."""
    try:
        import pyatspi                                          # noqa
        gs = subprocess.run(["gsettings", "get",
                             "org.gnome.desktop.interface", "toolkit-accessibility"],
                            capture_output=True, text=True).stdout.strip()
        if gs == "true":
            txt = _atspi_focused(wid)
            if txt and txt.strip():
                return txt
    except Exception:
        pass
    return _ocr_focused(wid)

def _atspi_focused(wid: str | None = None) -> str:
    import pyatspi
    out = []
    def walk(node, d=0):
        if d > 6 or len(out) > 400: return
        try:
            if node.queryText():
                t = node.queryText().getText(0, -1)
                if t and t.strip(): out.append(t)
        except Exception: pass
        try:
            for i in range(node.childCount): walk(node.getChildAtIndex(i), d + 1)
        except Exception: pass
    for app in pyatspi.Registry.getDesktop(0):
        try:
            for w in app:
                if w.getState().contains(pyatspi.STATE_ACTIVE):
                    walk(w)
        except Exception: continue
    return "\n".join(out)

def _win_geom(wid: str):
    """Absolute geometry. xdotool reports a DIFFERENT origin for reparented
    windows (measured: it said 1967,72 for a window xwininfo proved was at
    1957,0), so xwininfo is the authority here."""
    out = subprocess.run(["xwininfo", "-id", wid],
                         capture_output=True, text=True).stdout
    g = {}
    for line in out.split("\n"):
        line = line.strip()
        for key, field in (("Absolute upper-left X:", "x"),
                           ("Absolute upper-left Y:", "y"),
                           ("Width:", "w"), ("Height:", "h")):
            if line.startswith(key):
                g[field] = int(line.split(":")[1].strip())
    return g if len(g) == 4 else None

def _ocr_focused(wid: str | None = None) -> str:
    if not wid:
        wid = subprocess.run(["xdotool", "getactivewindow"],
                             capture_output=True, text=True).stdout.strip()
    if not wid:
        return ""
    png = os.path.join(_TMP, "win.png")
    # ImageMagick's `import` is NOT installed here and a missing binary raises
    # FileNotFoundError, which crashed straight past the fallback that was
    # meant to catch it. ffmpeg x11grab is the proven path on this box.
    g = _win_geom(wid)
    if not g:
        return ""
    try:
        subprocess.run(["ffmpeg", "-y", "-f", "x11grab",
                        "-video_size", f"{g['w']}x{g['h']}",
                        "-i", f":0.0+{g['x']},{g['y']}",
                        "-frames:v", "1", png],
                       capture_output=True, timeout=15)
    except Exception:
        return ""
    if not os.path.exists(png):
        return ""
    try:
        return subprocess.run(["tesseract", png, "-", "--psm", "6"],
                              capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""

SOURCES = {
    "selection": lambda a: src_selection(),
    "clipboard": lambda a: src_clipboard(),
    "claude":    lambda a: src_claude(delta=a.delta, n=a.messages),
    "window":    lambda a: src_window(getattr(a, "window", None)),
    "stdin":     lambda a: sys.stdin.read(),
}

def pick_auto(args) -> tuple[str, str]:
    """What the notch button does with no argument: selection, else Claude."""
    s = src_selection()
    if s.strip() and len(s.split()) >= 3:
        return "selection", s
    c = src_claude(delta=args.delta, n=args.messages)
    if c.strip():
        return "claude", c
    return "window", src_window(getattr(args, "window", None))

# ==================================================================== main ==
PIDFILE = os.path.join(STATEDIR, "reading.pid")
PAUSEFILE = os.path.join(STATEDIR, "paused")

def _running_pid():
    try:
        pid = int(open(PIDFILE).read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None

def cmd_stop() -> int:
    """Stop whatever is reading. Any bar or hotkey can call this."""
    pid = _running_pid()
    if not pid:
        return 1
    try:
        os.killpg(os.getpgid(pid), 15)
    except Exception:
        try: os.kill(pid, 15)
        except Exception: pass
    try: os.unlink(PIDFILE)
    except Exception: pass
    return 0

def _button_held() -> bool:
    """A drag in progress. PRIMARY only updates on mouse-up, so without this a
    slow highlight loses the race to the window timer."""
    try:
        from Xlib import display as _xd
        return bool(_xd.Display().screen().root.query_pointer().mask & 0x100)
    except Exception:
        return False

def cmd_pick(timeout=25.0, settle=1.6) -> tuple[str, str] | None:
    """Arm, then wait for EITHER a fresh highlight OR a click on a window.
    Highlight always wins. Returns (source_name, text) or None on timeout."""
    def sel():
        try: return subprocess.run(["xclip", "-o", "-selection", "primary"],
                                   capture_output=True, text=True, timeout=1).stdout
        except Exception: return ""
    def win():
        try: return subprocess.run(["xdotool", "getactivewindow"],
                                   capture_output=True, text=True, timeout=1).stdout.strip()
        except Exception: return ""
    def wclass(wid):
        try:
            out = subprocess.run(["xprop", "-id", wid, "WM_CLASS"],
                                 capture_output=True, text=True, timeout=1).stdout
            return out.split("=", 1)[1].lower() if "=" in out else ""
        except Exception: return ""

    sel0, win0 = sel(), win()
    seen, seen_at = None, 0.0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        s = sel()
        if s.strip() and s != sel0 and len(s.split()) >= 2:
            return "selection", s
        if _button_held():
            seen, seen_at = None, 0.0
            continue
        w = win()
        if w and w != win0:
            if w != seen:
                seen, seen_at = w, time.monotonic()
            elif time.monotonic() - seen_at >= settle:
                # Pointing at the Claude desktop app? Its transcript is on
                # disk as clean markdown - 5 ms and exact instead of OCR.
                if any(c in wclass(w) for c in ("com.anthropic.claude", "claude-desktop")):
                    return "claude", src_claude(delta=True)
                return "window", src_window(w)
        else:
            seen, seen_at = None, 0.0
    return None

_LIVE: list = []

def _on_term(_sig, _frm):
    for sp in _LIVE:
        sp.halt()
    sys.exit(0)

def _on_pause(_sig, _frm):
    for sp in _LIVE:
        sp.request_pause_toggle()

def cmd_playpause() -> int:
    """Toggle pause on the running reader (SIGUSR1). Returns 1 if none runs."""
    pid = _running_pid()
    if not pid:
        return 1
    try:
        os.kill(pid, signal.SIGUSR1); return 0
    except Exception:
        return 1

def main():
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    signal.signal(signal.SIGUSR1, _on_pause)
    ap = argparse.ArgumentParser(description="SpeedReader - speak text, fast")
    ap.add_argument("source", nargs="?", default="auto",
                    choices=["auto", *SOURCES, "file"], help="where to read from")
    ap.add_argument("--file")
    ap.add_argument("--pick", action="store_true",
                    help="arm: then highlight text OR click a window")
    ap.add_argument("--stop", action="store_true", help="stop the current read")
    ap.add_argument("--toggle", action="store_true",
                    help="stop if reading, otherwise --pick (bind this to one button)")
    ap.add_argument("--settings", action="store_true", help="open the settings window")
    ap.add_argument("--playpause", action="store_true",
                    help="pause/resume the current read")
    ap.add_argument("--primary", action="store_true",
                    help="button LEFT: read aloud, or pause/resume if already reading")
    ap.add_argument("--secondary", action="store_true",
                    help="button RIGHT: read-along window, or stop if already reading")
    ap.add_argument("--window", help="X window id to read (from xdotool selectwindow)")
    _cfg = load_config()
    ap.add_argument("--style", default=_cfg["style"],
                    choices=["verbatim", "skim", "structure", "gist"])
    ap.add_argument("--rate", type=int, default=_cfg["rate"], help="-100..100 (espeak)")
    ap.add_argument("--preset", choices=list(PRESETS),
                    help="speed preset: easy | medium | fast | superfast")
    ap.add_argument("--voice", default=_cfg["voice"], help="spd-say -L name")
    ap.add_argument("--pitch", type=int, default=_cfg["pitch"])
    ap.add_argument("--numbers", default=_cfg["numbers"],
                    choices=["normal", "skip", "digits"],
                    help="unimportant numbers: read all / drop / read as digits")
    ap.add_argument("--code", default=_cfg["code"], choices=["describe", "speak"],
                    help="fenced blocks: one-line summary, or read them out")
    ap.add_argument("--pacer", default=_cfg["pacer"], choices=["auto", "on", "off"],
                    help="show the follow-along window (auto: only if long)")
    ap.add_argument("--delta", action="store_true", help="claude: only what is new")
    ap.add_argument("--messages", type=int, default=1)
    ap.add_argument("--no-redact", action="store_true", default=not _cfg["redact"])
    ap.add_argument("--no-earcons", action="store_true", default=not _cfg["earcons"])
    ap.add_argument("--dry", action="store_true", help="print spans, do not speak")
    a = ap.parse_args()

    global CODE_MODE, NUM_MODE
    CODE_MODE = a.code
    NUM_MODE = a.numbers
    if a.preset:
        a.rate = PRESETS[a.preset]

    if a.settings:
        here = os.path.dirname(os.path.abspath(__file__))
        os.execv(sys.executable, [sys.executable, os.path.join(here, "settings.py")])
    if a.stop:
        return cmd_stop()
    if a.playpause:
        return cmd_playpause()
    if a.primary:                      # left click
        if _running_pid():
            return cmd_playpause()     # reading -> pause/resume
        a.pick = True; a.pacer = "off" # idle -> read aloud
    if a.secondary:                    # right click
        if _running_pid():
            return cmd_stop()          # reading -> stop
        a.pick = True; a.pacer = "on"  # idle -> read-along window
    if a.toggle:
        if _running_pid():
            return cmd_stop()
        a.pick = True

    t0 = time.monotonic()
    if a.pick:
        picked = cmd_pick()
        if not picked:
            print("nothing picked", file=sys.stderr)
            return 1
        name, text = picked
    elif a.source == "file":
        name, text = "file", open(a.file, encoding="utf-8", errors="replace").read()
    elif a.source == "auto":
        name, text = pick_auto(a)
    else:
        name, text = a.source, SOURCES[a.source](a)

    if not text.strip():
        print(f"nothing to read (source: {name})", file=sys.stderr)
        return 1

    nred = 0
    if not a.no_redact:
        text, nred = redact(text)

    want_pacer = (a.pacer == "on" or
                  (a.pacer == "auto" and len(text.split()) >= 60)) and not a.dry
    sp = Speaker(rate=a.rate, quiet_earcons=a.no_earcons, dry=a.dry,
                 voice=a.voice, pitch=a.pitch, source=text,
                 word_sync=(want_pacer and a.style == "verbatim"))
    _LIVE.append(sp)
    # One reader at a time. A second start stops the first - that is what
    # makes a single bar button work as start/stop.
    if not a.dry:
        if _running_pid():
            cmd_stop()
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
    first = None

    def pump():
        nonlocal first
        for kind, span, sa, sb in extract(text, a.style):
            if first is None:
                first = time.monotonic() - t0
            sp.push(kind, span, sa, sb)
        sp.finish()

    # A window for a six-word highlight is noise, so "auto" only raises it when
    # there is actually something to follow along with.
    if want_pacer:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from pacer import Pacer
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            win = Pacer(text, on_close=sp.halt,
                        header=f"{a.voice}  ·  rate {a.rate}  ·  {a.style}")
            sp.on_chunk = win.schedule
            sp.on_word  = win.word
            threading.Thread(
                target=lambda: (pump(), sp.t.join(), win.finish()),
                daemon=True).start()
            win.show_all()
            Gtk.main()
        except Exception as e:
            print(f"pacer unavailable ({type(e).__name__}: {e}); audio only",
                  file=sys.stderr)
            want_pacer = False
    if not want_pacer:
        try:
            pump()
            while sp.t.is_alive():
                sp.t.join(0.2)
        except KeyboardInterrupt:
            sp.halt()
            print("\nstopped", file=sys.stderr)

    try:
        if _running_pid() == os.getpid():
            os.unlink(PIDFILE)
    except Exception:
        pass
    # Log the EFFECTIVE settings, not the intended ones - a silent override
    # of style/rate is exactly the failure this makes visible next time.
    print(f"source={name} style={a.style} rate={a.rate} voice={a.voice!r} "
          f"pacer={a.pacer} words={len(text.split())} spans={sp.spoken} "
          f"redacted={nred} ttfw={first*1000:.0f}ms" if first else "no spans",
          file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
