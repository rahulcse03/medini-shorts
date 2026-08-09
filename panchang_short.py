#!/usr/bin/env python3
"""
Medini Jyotish — daily Panchang Shorts renderer.

Pipeline:  API JSON -> scene model -> 1080x1920 PNG frames -> TTS -> ffmpeg -> mp4

Design constraints:
  * Renders OFF the production VM (single-worker uvicorn / CPU-bound pyswisseph).
    Intended host: GitHub Actions runner or a local desktop.
  * Read-only against the public API. No backend changes required.
  * Deterministic content only: computed panchang values, no interpretation.

Usage:
    python3 panchang_short.py --lang en --out out/
    python3 panchang_short.py --lang hi --date 2026-08-08 --tz 5.5
    python3 panchang_short.py --lang en --no-tts          # silent, for layout QA
    python3 panchang_short.py --lang en --sample          # offline canned data

Requires: pillow (with raqm for Devanagari shaping), ffmpeg, edge-tts (optional).
    pip install pillow edge-tts
    apt-get install ffmpeg fonts-noto-core fonts-noto-ui-core
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

try:
    from deva_names import DEVA_LANGS, localise, respell
except ImportError:                                           # degrade, don't die
    DEVA_LANGS = set()

    def localise(v, lang="hi", digits=True):
        return v

    def respell(v, lang="en"):
        return v

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

API_BASE = os.environ.get("MEDINI_API", "https://medinijyotish.com")
W, H = 1080, 1920

# Safe area. IG Reels overlays ~14% top and ~22% bottom; YT Shorts is similar.
# Everything that must be readable lives between these.
SAFE_TOP, SAFE_BOTTOM = 300, 1480

PLACE = ""   # set from --place at build time; shown in every footer

# Parchment theme (matches the site palette)
BG = (245, 230, 200)          # #F5E6C8 parchment
BG_DEEP = (236, 216, 178)     # panel fill
MAROON = (107, 29, 29)        # #6B1D1D
SAFFRON = (212, 130, 10)      # #D4820A
INK = (46, 26, 15)            # #2E1A0F
MUTED = (139, 111, 78)        # #8B6F4E
RULE = (198, 170, 126)

FONT_CANDIDATES = {
    # Devanagari-capable, in preference order
    "deva": [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-{w}.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-{w}.ttf",
        "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
        "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
        "/usr/share/fonts/truetype/Sarai/Sarai.ttf",
    ],
    "latin": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-{w}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-{w}.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-{w}.ttf",
    ],
}

# edge-tts voices. Hindi neural voices are the reason to prefer edge-tts
# over espeak/piper for this project — the Sanskrit terms come out intelligible.
VOICES = {
    "hi": "hi-IN-MadhurNeural",
    "en": "en-IN-PrabhatNeural",
    "te": "te-IN-MohanNeural",
    "ta": "ta-IN-ValluvarNeural",
    "kn": "kn-IN-GaganNeural",
    "bn": "bn-IN-BashkarNeural",
    "mr": "mr-IN-ManoharNeural",
    "gu": "gu-IN-NiranjanNeural",
}

# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------

STR = {
    "en": {
        "title": "Today's Panchang",
        "tithi": "Tithi", "nakshatra": "Nakshatra", "yoga": "Yoga",
        "karana": "Karana", "vara": "Vara",
        "sunrise": "Sunrise", "sunset": "Sunset",
        "shubh": "Auspicious Window", "abhijit": "Abhijit Muhurat",
        "avoid": "Avoid These Periods",
        "rahu": "Rahu Kalam", "gulika": "Gulika Kalam", "yama": "Yamaghanda",
        "cta": "Free & ad-free",
        "cta_city": "In a different city?",
        "cta_city_sub": "Rahu Kalam shifts 30–45 min across India.\n"
                        "Get exact timings for your location:",
        "site": "medinijyotish.com",
        "src": "Swiss Ephemeris · Lahiri Ayanamsha",
        "avoid_hook": "Don't Start Anything",
        "until": "until {time}",
        "n_rahu_hook": "Don't begin anything important today from {rahu}.",
        "n_hook": "Panchang for {date}, {vara}. Today's tithi is {tithi_phrase}.",
        # "Sunrise" as one word gets mangled by the en-IN voice; "the sun
        # rises" is read correctly and sounds more natural anyway.
        "n_limbs": "The nakshatra is {nakshatra}. Yoga, {yoga}. Karana, {karana}. "
                   "The sun rises at {sunrise} and sets at {sunset}.",
        "n_shubh": "The most auspicious window today is Abhijit Muhurat, "
                   "{abhijit_start} to {abhijit_end}.",
        "n_avoid": "Avoid new beginnings during Rahu Kalam, {rahu}. "
                   "Gulika Kalam is {gulika}, and Yamaghanda is {yama}.",
        "n_cta": "These timings are for Delhi. Rahu Kalam shifts by up to "
                 "forty five minutes across India, so check your own city, "
                 "free and ad free, at Medini Jyotish dot com.",
    },
    "hi": {
        "title": "आज का पंचांग",
        "tithi": "तिथि", "nakshatra": "नक्षत्र", "yoga": "योग",
        "karana": "करण", "vara": "वार",
        "sunrise": "सूर्योदय", "sunset": "सूर्यास्त",
        "shubh": "शुभ मुहूर्त", "abhijit": "अभिजित मुहूर्त",
        "avoid": "इन समयों से बचें",
        "rahu": "राहु काल", "gulika": "गुलिक काल", "yama": "यमगण्ड",
        "cta": "निःशुल्क · विज्ञापन रहित",
        "cta_city": "आपका शहर अलग है?",
        "cta_city_sub": "राहु काल हर शहर में 30–45 मिनट बदलता है।\n"
                        "अपने स्थान का सटीक समय देखें:",
        "site": "medinijyotish.com",
        "src": "स्विस एफ़ेमेरिस · लाहिड़ी अयनांश",
        "avoid_hook": "कोई शुभ कार्य न करें",
        "until": "{time} तक",
        "n_rahu_hook": "आज {rahu} कोई नया या शुभ कार्य आरम्भ न करें।",
        "n_hook": "{date}, {vara} का पंचांग। आज की तिथि है {tithi_phrase}।",
        "n_limbs": "नक्षत्र {nakshatra}। योग {yoga}। करण {karana}। "
                   "सूर्योदय {sunrise} पर, और सूर्यास्त {sunset} पर।",
        "n_shubh": "आज का सर्वश्रेष्ठ शुभ मुहूर्त है अभिजित मुहूर्त, "
                   "{abhijit_start} से {abhijit_end} तक।",
        "n_avoid": "राहु काल {rahu} है, इसमें कोई नया कार्य आरम्भ न करें। "
                   "गुलिक काल {gulika}, और यमगण्ड {yama}।",
        "n_cta": "यह समय दिल्ली के अनुसार है। राहु काल हर शहर में पैंतालीस मिनट "
                 "तक बदल सकता है, इसलिए अपने शहर का पंचांग देखें, निःशुल्क, "
                 "मेदिनी ज्योतिष डॉट कॉम पर।",
    },
}

# --------------------------------------------------------------------------
# Data fetch + normalisation
# --------------------------------------------------------------------------

# Mirrors the real /api/v1/panchang/today payload exactly. Keep it that way —
# a sample that drifts from the API is worse than no sample, because it makes
# broken field mappings look like they work.
SAMPLE = {
    "datetime_utc": "2026-08-09T04:53:47.525136+00:00",
    "location": {"latitude": 28.6139, "longitude": 77.209},
    "ayanamsha_lahiri": 24.228727,
    "tithi": {"tithi_index": 25, "tithi_name": "Ekadashi", "tithi_number": 11,
              "paksha": "Krishna", "paksha_sa": "कृष्ण पक्ष",
              "remaining_degrees": 0.3978},
    "nakshatra": {"nakshatra_index": 4, "nakshatra": "Mrigashira",
                  "nakshatra_sa": "मृगशिरा", "nakshatra_lord": "mangal",
                  "pada": 4, "remaining_degrees": 2.6506},
    "yoga": {"yoga_index": 13, "yoga": "Harshana", "remaining_degrees": 10.2367},
    "karana": {"karana": "Balava", "remaining_degrees": 0.3978},
    "vara": {"vara": "Ravivara", "vara_sa": "रविवार", "vara_en": "Sunday",
             "vara_lord": "surya"},
    "sunrise_utc": "2026-08-09T00:18:19Z",
    "sunset_utc": "2026-08-09T13:34:44Z",
    "rahu_kalam": {"start_utc": "2026-08-09T11:55:11Z",
                   "end_utc": "2026-08-09T13:34:44Z"},
    "gulika_kalam": {"start_utc": "2026-08-09T10:15:38Z",
                     "end_utc": "2026-08-09T11:55:11Z"},
    "yamaghanda": {"start_utc": "2026-08-09T06:56:31Z",
                   "end_utc": "2026-08-09T08:36:04Z"},
    "abhijit_muhurat": {"start_utc": "2026-08-09T06:29:58Z",
                        "end_utc": "2026-08-09T07:23:04Z"},
}


def api_get(when: str | None, lat: float, lon: float) -> dict:
    if when:
        url = f"{API_BASE}/api/v1/panchang?date={when}&lat={lat}&lon={lon}"
    else:
        url = f"{API_BASE}/api/v1/panchang/today?lat={lat}&lon={lon}"
    req = urllib.request.Request(url, headers={"User-Agent": "medini-shorts/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(date: str | None, lat: float, lon: float, use_sample: bool,
          tz: float = 5.5, anchor: bool = True) -> dict:
    """Panchang for the day, evaluated at sunrise.

    The API evaluates at whatever instant you pass it, so querying at run time
    returns the tithi *right now*. But a day's panchang is conventionally the
    set of values prevailing at sunrise — tithis roll over mid-morning all the
    time, so an 11 AM render would announce a different tithi than the same
    day's panchang read at breakfast, and than every other almanac.

    Two calls: one to learn today's sunrise, one to evaluate at sunrise + 2 min.
    """
    if use_sample:
        return SAMPLE

    target = date or datetime.now(
        timezone(timedelta(hours=tz))).strftime("%Y-%m-%d")
    raw = api_get(f"{target}T06:00:00", lat, lon)
    if not anchor:
        return raw

    sr = field(raw, "sunrise_utc", "sunrise")
    if not sr:
        return raw
    try:
        at = datetime.fromisoformat(sr.replace("Z", "+00:00")) \
            + timedelta(minutes=2)
    except ValueError:
        return raw
    return api_get(at.strftime("%Y-%m-%dT%H:%M:%S"), lat, lon)


def dig(d, *keys, default=""):
    """Tolerant lookup: tries dotted paths, then a recursive key search.

    The panchang payload has been reshaped a few times across engine versions;
    this keeps the renderer from breaking on a field rename.
    """
    for k in keys:
        cur = d
        ok = True
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    # recursive fallback on the first key's leaf name
    leaf = keys[0].split(".")[-1]

    def walk(node):
        if isinstance(node, dict):
            if leaf in node and node[leaf] not in (None, ""):
                return node[leaf]
            for v in node.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(node, list):
            for v in node:
                r = walk(v)
                if r is not None:
                    return r
        return None

    return walk(d) if walk(d) is not None else default


def field(node, *keys, default="") -> str:
    """First non-empty key from a payload sub-object.

    The API nests each limb and names the value after the limb itself
    ("tithi": {"tithi_name": ...}, "yoga": {"yoga": ...}), so there is no single
    generic key like "name" to reach for.
    """
    if isinstance(node, dict):
        for k in keys:
            v = node.get(k)
            if v not in (None, ""):
                return str(v)
        return default
    return str(node) if node not in (None, "") else default


def as_name(v) -> str:
    if isinstance(v, dict):
        return field(v, "name", "value", "label")
    return str(v or "")


def to_local(ts, tz_hours: float) -> str:
    """ISO timestamp (or 'HH:MM') -> local HH:MM.

    NOTE: the API emits UTC. The SSR page currently *labels* these as UTC,
    which for a Delhi panchang means sunrise reads 00:17 instead of 05:47.
    Always convert here; never print a raw API time.
    """
    if not ts:
        return "--:--"
    s = str(ts)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", s.strip())
    if m:  # already a clock time, assume UTC per API convention
        base = datetime(2000, 1, 1, int(m.group(1)) % 24, int(m.group(2)),
                        tzinfo=timezone.utc)
    else:
        try:
            base = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return s
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
    local = base.astimezone(timezone(timedelta(hours=tz_hours)))
    return local.strftime("%H:%M")


def span(d, key, tz) -> str:
    node = dig(d, key, default={})
    if isinstance(node, dict):
        a = to_local(field(node, "start_utc", "start", "from"), tz)
        b = to_local(field(node, "end_utc", "end", "to"), tz)
        return f"{a} – {b}"
    return str(node)


# Mean Moon-Sun elongation rate, degrees/day. Used only as a first guess for
# the root-find below — never as the answer.
MEAN_ELONGATION = 12.19
TITHI_ARC = 12.0


def _tithi_state(raw: dict) -> tuple[int, float]:
    t = raw.get("tithi", {}) if isinstance(raw, dict) else {}
    return int(t.get("tithi_index", -1)), float(t.get("remaining_degrees", 0.0))


def tithi_end(base: datetime, raw0: dict, lat: float, lon: float,
              max_calls: int = 4) -> datetime | None:
    """Instant the sunrise tithi ends, solved against the live ephemeris.

    A tithi is 12° of Moon-Sun elongation, but the Moon's speed varies by ~10%
    over a month, so extrapolating `remaining_degrees` at a mean rate can be
    5-15 minutes out on a tithi ending 20 hours later. That is far too loose
    for a site that advertises sub-arcsecond positions.

    Instead treat it as a root-find. Let k = tithi indices crossed since base
    and phi = degrees remaining now; then

        h(t) = k*12 - phi(t)

    is negative before the boundary, zero at it, positive after, and monotonic.
    Secant iteration on h, evaluating phi via the API, converges to under a
    minute in 2-3 calls because each step re-measures rather than assumes.

    Returns None rather than a guess if it doesn't converge — an absent "upto"
    line is fine, a wrong one is not.
    """
    i0, r0 = _tithi_state(raw0)
    if i0 < 0 or r0 <= 0:
        return None

    def h_at(t: datetime) -> float | None:
        try:
            raw = api_get(t.strftime("%Y-%m-%dT%H:%M:%S"), lat, lon)
        except Exception:                                     # noqa: BLE001
            return None
        i, phi = _tithi_state(raw)
        if i < 0:
            return None
        k = (i - i0) % 30
        if k > 2:                     # wrapped backwards; outside our bracket
            k -= 30
        return k * TITHI_ARC - phi

    t_a, h_a = base, -r0
    t_b = base + timedelta(days=r0 / MEAN_ELONGATION)

    for _ in range(max_calls):
        h_b = h_at(t_b)
        if h_b is None:
            return None
        if abs(h_b) < 0.002:                  # ~0.2 min of elongation
            return t_b
        if h_b == h_a:
            return None
        t_next = t_b - h_b * (t_b - t_a) / (h_b - h_a)
        # Keep the bracket sane: the answer is always within a tithi of base.
        if not (base <= t_next <= base + timedelta(hours=30)):
            return None
        t_a, h_a, t_b = t_b, h_b, t_next
        if abs((t_b - t_a).total_seconds()) < 30:
            return t_b
    return t_b


def local_date(raw: dict, tz: float, hint: str | None) -> str:
    """Calendar date in the display timezone, not in UTC.

    The payload carries only `datetime_utc`. Between 18:30 and 24:00 IST that
    is still the previous UTC day, so taking the first 10 characters would
    label an evening render with yesterday's date.
    """
    if hint:
        return hint
    ts = field(raw, "datetime_utc", "date")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=tz))).strftime("%Y-%m-%d")
    except ValueError:
        return ts[:10]


@dataclass
class Panchang:
    date: str
    vara: str
    tithi: str
    nakshatra: str
    yoga: str
    karana: str
    sunrise: str
    sunset: str
    abhijit_start: str
    abhijit_end: str
    rahu: str
    gulika: str
    yama: str
    tithi_end: str = ""       # "10:47" local, or "" if not resolved
    tithi_phrase: str = ""    # "Krishna Ekadashi until 10:47"


def normalise(raw: dict, lang: str, tz: float, date_hint: str | None,
              end_dt: datetime | None = None) -> Panchang:
    deva = lang in DEVA_LANGS

    def sub(key) -> dict:
        v = dig(raw, key, default={})
        return v if isinstance(v, dict) else {}

    t_node, n_node = sub("tithi"), sub("nakshatra")
    y_node, k_node, v_node = sub("yoga"), sub("karana"), sub("vara")
    ab = sub("abhijit_muhurat") or sub("abhijit")

    # The API ships Devanagari for nakshatra, vara and paksha (*_sa) but not for
    # tithi_name, yoga or karana — those come back transliterated in every
    # language. Prefer the API's own text where it exists, fall back to the
    # lookup table where it doesn't.
    def L(v: str) -> str:
        return localise(v, lang, digits=False) if deva else v

    tithi_name = field(t_node, "tithi_name", "name", "tithi")
    paksha = field(t_node, "paksha").split()[0] if field(t_node, "paksha") else ""
    if deva:
        tithi = f"{localise(paksha, lang, digits=False)} " \
                f"{localise(tithi_name, lang, digits=False)}".strip()
    else:
        tithi = f"{paksha} {tithi_name}".strip()

    if deva:
        nakshatra = field(n_node, "nakshatra_sa") or L(field(n_node, "nakshatra", "name"))
        vara = field(v_node, "vara_sa") or L(field(v_node, "vara", "name"))
    else:
        nakshatra = field(n_node, "nakshatra", "name")
        # vara_en ("Sunday") reads better than vara ("Ravivara") in English.
        vara = field(v_node, "vara_en", "vara", "name")

    p = Panchang(
        date=local_date(raw, tz, date_hint),
        vara=vara,
        tithi=tithi,
        nakshatra=nakshatra,
        yoga=L(field(y_node, "yoga", "name")),
        karana=L(field(k_node, "karana", "name")),
        sunrise=to_local(field(raw, "sunrise_utc", "sunrise"), tz),
        sunset=to_local(field(raw, "sunset_utc", "sunset"), tz),
        abhijit_start=to_local(field(ab, "start_utc", "start"), tz),
        abhijit_end=to_local(field(ab, "end_utc", "end"), tz),
        rahu=span(raw, "rahu_kalam", tz),
        gulika=span(raw, "gulika_kalam", tz),
        yama=span(raw, "yamaghanda", tz),
    )

    if end_dt:
        p.tithi_end = to_local(end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), tz)
        until = "तक" if deva else "until"
        p.tithi_phrase = (f"{p.tithi} {p.tithi_end} {until}" if deva
                          else f"{p.tithi} until {p.tithi_end}")
    else:
        p.tithi_phrase = p.tithi
    return p


def check(p: Panchang):
    """Refuse to render a panchang with holes in it.

    People act on these timings. A short with a blank Rahu Kalam, or one
    narrating "today's tithi is .", is worse than no post that day — so this
    fails the run rather than producing something publishable-looking.
    """
    required = {
        "date": p.date, "vara": p.vara, "tithi": p.tithi,
        "nakshatra": p.nakshatra, "yoga": p.yoga, "karana": p.karana,
        "sunrise": p.sunrise, "sunset": p.sunset,
        "abhijit_start": p.abhijit_start, "abhijit_end": p.abhijit_end,
        "rahu": p.rahu, "gulika": p.gulika, "yama": p.yama,
    }
    missing = [k for k, v in required.items() if not v or v == "--:--"
               or v.strip() == "–" or v.strip() == "--:-- – --:--"]
    if missing:
        sys.exit(
            "\n  ABORT — the API payload is missing: " + ", ".join(missing) +
            "\n  The field mapping in normalise() no longer matches the API."
            "\n  Inspect it with:  python3 panchang_short.py --dump-json\n")


# --------------------------------------------------------------------------
# Typography
# --------------------------------------------------------------------------

_font_cache: dict = {}


def font(size: int, weight: str = "Regular", script: str = "latin"):
    key = (size, weight, script)
    if key in _font_cache:
        return _font_cache[key]
    for tmpl in FONT_CANDIDATES[script] + FONT_CANDIDATES["latin"]:
        p = tmpl.format(w=weight)
        if Path(p).exists():
            _font_cache[key] = ImageFont.truetype(p, size)
            return _font_cache[key]
    _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def script_for(lang: str) -> str:
    return "deva" if lang in ("hi", "mr", "ne", "sa") else "latin"


def centered(draw, y, text, f, fill, line_gap=14):
    """Draw centred text. Handles embedded newlines; returns the bottom y."""
    if not text:
        return y
    for line in str(text).split("\n"):
        if not line:
            y += f.size + line_gap
            continue
        box = draw.textbbox((0, 0), line, font=f)
        draw.text(((W - (box[2] - box[0])) / 2 - box[0], y), line, font=f,
                  fill=fill)
        y += (box[3] - box[1]) + line_gap
    return y - line_gap


# --------------------------------------------------------------------------
# Scene rendering
# --------------------------------------------------------------------------

def canvas() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # subtle parchment vignette
    for i in range(140):
        a = int(14 * (1 - i / 140))
        d.rectangle([i, i, W - i, H - i], outline=(BG[0] - a, BG[1] - a, BG[2] - a))
    # top + bottom ornament rules inside the safe area
    d.line([(180, SAFE_TOP - 70), (W - 180, SAFE_TOP - 70)], fill=RULE, width=3)
    d.line([(180, SAFE_BOTTOM + 60), (W - 180, SAFE_BOTTOM + 60)], fill=RULE, width=3)
    return img


def diamond(d, cx, cy, r, fill):
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)


def ornament(d, cy, scale=1.0):
    """Vector ornament — deliberately not a glyph, so it survives any font set."""
    r = int(11 * scale)
    for dx, rr in ((-int(46 * scale), r - 3), (0, r + 3), (int(46 * scale), r - 3)):
        diamond(d, W / 2 + dx, cy, rr, SAFFRON)


def brandmark(d, sc, place: str = ""):
    """Footer on every frame.

    The place is not decoration. Rahu Kalam and friends are eighths of the
    LOCAL daylight span, so a Delhi video's windows are simply wrong for
    Chennai or Dubai — by half an hour or more. Stating the city is the
    difference between a precise claim and a misleading one.
    """
    ornament(d, SAFE_TOP - 130)
    label = f"medinijyotish.com · {place}" if place else "medinijyotish.com"
    d.text((W / 2, SAFE_BOTTOM + 130), label, font=font(32, script=sc),
           fill=MUTED, anchor="mm")


def start_y(content_h: int) -> int:
    """Vertically centre a content block inside the safe area."""
    return int(SAFE_TOP + max((SAFE_BOTTOM - SAFE_TOP - content_h) / 2, 0))


def panel(d, y0, y1, pad=110):
    d.rounded_rectangle([pad, y0, W - pad, y1], radius=28, fill=BG_DEEP, outline=RULE,
                        width=3)


def scene_rahu_hook(p: Panchang, t: dict, sc: str) -> Image.Image:
    """Opening frame. Leads with Rahu Kalam, not a title card.

    Shorts is swipe-or-stay in the first ~2 seconds, and the scarcest useful
    thing here is "when should I not start something today". A date stamp
    earns nothing; a specific time window the viewer doesn't know yet does.
    """
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(600)
    y = centered(d, y, t["avoid_hook"], font(64, "Bold", sc), MAROON) + 90
    panel(d, y, y + 300)
    yy = y + 55
    yy = centered(d, yy, t["rahu"], font(46, script=sc), SAFFRON) + 70
    centered(d, yy, p.rahu, font(88, "Bold", sc), INK)
    centered(d, y + 350, f"{p.date}  ·  {p.vara}", font(40, script=sc), MUTED)
    return img


def scene_hook(p: Panchang, t: dict, sc: str) -> Image.Image:
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(634)
    y = centered(d, y, t["title"], font(78, "Bold", sc), MAROON) + 70
    y = centered(d, y, f"{p.date}  ·  {p.vara}", font(46, script=sc), MUTED) + 110
    panel(d, y, y + (390 if p.tithi_end else 330))
    yy = y + 60
    yy = centered(d, yy, t["tithi"].upper() if sc == "latin" else t["tithi"],
                  font(40, script=sc), SAFFRON) + 55
    yy = centered(d, yy, p.tithi, font(84, "Bold", sc), INK) + 50
    if p.tithi_end:
        centered(d, yy, t["until"].format(time=p.tithi_end),
                 font(44, script=sc), MUTED)
    return img


def scene_limbs(p: Panchang, t: dict, sc: str) -> Image.Image:
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(930)
    y = centered(d, y, t["title"], font(60, "Bold", sc), MAROON) + 90
    rows = [(t["nakshatra"], p.nakshatra), (t["yoga"], p.yoga),
            (t["karana"], p.karana), (t["sunrise"], p.sunrise),
            (t["sunset"], p.sunset)]
    row_h = 150
    panel(d, y, y + row_h * len(rows) + 30)
    yy = y + 40
    for i, (k, v) in enumerate(rows):
        d.text((175, yy + 40), k, font=font(44, script=sc), fill=MUTED)
        d.text((W - 175, yy + 34), v or "—", font=font(56, "Bold", sc), fill=INK,
               anchor="ra")
        if i < len(rows) - 1:
            d.line([(175, yy + row_h - 12), (W - 175, yy + row_h - 12)], fill=RULE,
                   width=2)
        yy += row_h
    return img


def scene_shubh(p: Panchang, t: dict, sc: str) -> Image.Image:
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(640)
    y = centered(d, y, t["shubh"], font(70, "Bold", sc), MAROON) + 100
    panel(d, y, y + 380)
    yy = y + 70
    yy = centered(d, yy, t["abhijit"], font(48, script=sc), SAFFRON) + 80
    centered(d, yy, f"{p.abhijit_start} – {p.abhijit_end}", font(92, "Bold", sc), INK)
    centered(d, y + 430, t["src"], font(32, script=sc), MUTED)
    return img


def scene_avoid(p: Panchang, t: dict, sc: str) -> Image.Image:
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(756)
    y = centered(d, y, t["avoid"], font(66, "Bold", sc), MAROON) + 90
    rows = [(t["rahu"], p.rahu), (t["gulika"], p.gulika), (t["yama"], p.yama)]
    row_h = 190
    panel(d, y, y + row_h * len(rows) + 30)
    yy = y + 50
    for i, (k, v) in enumerate(rows):
        centered(d, yy, k, font(44, script=sc), SAFFRON)
        centered(d, yy + 66, v, font(66, "Bold", sc), INK)
        if i < len(rows) - 1:
            d.line([(200, yy + row_h - 20), (W - 200, yy + row_h - 20)], fill=RULE,
                   width=2)
        yy += row_h
    return img


def scene_cta(p: Panchang, t: dict, sc: str) -> Image.Image:
    """Closing card. Carries the location caveat as the reason to click.

    Delhi timings labelled "India" are ~30-45 min out for Chennai, so the
    caveat is owed to the viewer regardless — making it the call to action
    turns an honesty requirement into the funnel to the site.
    """
    img = canvas(); d = ImageDraw.Draw(img); brandmark(d, sc, PLACE)
    y = start_y(700)
    ornament(d, y + 20, scale=2.0)
    y += 120
    y = centered(d, y, t["cta_city"], font(50, "Bold", sc), MAROON) + 75
    y = centered(d, y, t["cta_city_sub"], font(38, script=sc), INK) + 95
    y = centered(d, y, t["site"], font(74, "Bold", sc), MAROON) + 85
    y = centered(d, y, t["cta"], font(38, script=sc), MUTED) + 70
    centered(d, y, t["src"], font(32, script=sc), MUTED)
    return img


SCENES = [
    ("rahu", scene_rahu_hook, "n_rahu_hook"),
    ("hook", scene_hook, "n_hook"),
    ("limbs", scene_limbs, "n_limbs"),
    ("shubh", scene_shubh, "n_shubh"),
    ("avoid", scene_avoid, "n_avoid"),
    ("cta", scene_cta, "n_cta"),
]


# --------------------------------------------------------------------------
# Speech shaping
# --------------------------------------------------------------------------

# The frames show 24-hour times because they're compact and unambiguous, but
# TTS reads "05:48" as "oh five forty eight" and "17:25" as "seventeen twenty
# five" — neither is how anyone says a time out loud. Speech gets its own
# rendering of the same values.

# Upper bound -> period word. Read as "hour < bound". Note the first entry is
# रात, not सुबह: 00:00-03:59 is night, and morning only starts at 4.
HI_PERIOD = [(4, "रात"), (12, "सुबह"), (16, "दोपहर"), (20, "शाम"), (24, "रात")]


def speak_time(hhmm: str, lang: str) -> str:
    if not hhmm or ":" not in hhmm:
        return hhmm
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return hhmm

    if lang in DEVA_LANGS:
        period = next(p for lim, p in HI_PERIOD if h < lim)
        h12 = h % 12 or 12
        return f"{period} {h12} बजकर {m} मिनट" if m else f"{period} {h12} बजे"

    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def speak_span(span: str, lang: str) -> str:
    """'17:25 – 19:04' -> '5:25 PM to 7:04 PM'"""
    parts = [s.strip() for s in re.split(r"[–-]", span) if s.strip()]
    if len(parts) != 2:
        return span
    joiner = "से" if lang in DEVA_LANGS else "to"
    a, b = speak_time(parts[0], lang), speak_time(parts[1], lang)
    return f"{a} {joiner} {b}" if lang not in DEVA_LANGS else f"{a} से {b} तक"


def spoken(p: Panchang, lang: str) -> dict:
    """Speech-friendly copy of the panchang values for narration only."""
    d = dict(p.__dict__)
    # "twenty twenty six dash zero eight dash zero nine" is not a date.
    d["date"] = human_date(p.date, lang)
    for k in ("sunrise", "sunset", "abhijit_start", "abhijit_end", "tithi_end"):
        d[k] = speak_time(d.get(k, ""), lang)
    for k in ("rahu", "gulika", "yama"):
        d[k] = speak_span(d.get(k, ""), lang)
    if p.tithi_end:
        until = "तक" if lang in DEVA_LANGS else "until"
        d["tithi_phrase"] = (f"{p.tithi} {d['tithi_end']} {until}"
                             if lang in DEVA_LANGS
                             else f"{p.tithi} until {d['tithi_end']}")
    else:
        d["tithi_phrase"] = p.tithi
    return d


# --------------------------------------------------------------------------
# Audio + assembly
# --------------------------------------------------------------------------

def tts(text: str, lang: str, out: Path, voice: str | None = None) -> bool:
    voice = voice or VOICES.get(lang, VOICES["en"])
    try:
        subprocess.run(
            [sys.executable, "-m", "edge_tts", "--voice", voice,
             "--text", text, "--write-media", str(out)],
            check=True, capture_output=True, timeout=120)
        return out.exists() and out.stat().st_size > 1024
    except Exception as e:                                    # noqa: BLE001
        print(f"  [tts] fallback to silence ({type(e).__name__})", file=sys.stderr)
        return False


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def silence(seconds: float, out: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.2f}",
         "-c:a", "libmp3lame", "-q:a", "5", str(out)],
        check=True, capture_output=True)


def segment(png: Path, mp3: Path, out: Path, dur: float, zoom: bool):
    """One still + its narration -> one mp4 segment.

    Slow zoom is worth the encode cost: static frames tank retention on Reels.
    """
    frames = max(int(dur * 30), 30)
    vf = (f"zoompan=z='min(zoom+0.00035,1.09)':d={frames}:s={W}x{H}:fps=30,"
          f"format=yuv420p" if zoom else f"format=yuv420p")
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(mp3),
         "-vf", vf, "-t", f"{dur:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
         "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
         "-movflags", "+faststart", "-shortest", str(out)],
        check=True, capture_output=True)


def concat(segments: list[Path], out: Path, workdir: Path):
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", "-movflags", "+faststart", str(out)],
        check=True, capture_output=True)


# --------------------------------------------------------------------------
# Captions / metadata for the upload step
# --------------------------------------------------------------------------

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई",
             "अगस्त", "सितम्बर", "अक्टूबर", "नवम्बर", "दिसम्बर"]


def human_date(iso: str, lang: str) -> str:
    """'2026-08-09' -> '9 August 2026'.

    Nobody searches an ISO date. Query logs for this category look like
    "panchang 9 august 2026" or "aaj ka panchang", so the title should match
    the phrasing people actually type.
    """
    try:
        y, m, d = (int(x) for x in iso.split("-"))
    except (ValueError, AttributeError):
        return iso
    months = MONTHS_HI if lang == "hi" else MONTHS_EN
    return f"{d} {months[m - 1]} {y}"


def metadata(p: Panchang, lang: str, place: str = "") -> dict:
    hd = human_date(p.date, lang)
    where = place or "Delhi, India"
    if lang == "hi":
        title = f"आज का पंचांग {hd} — {p.tithi}, राहु काल व शुभ मुहूर्त"
        lead = (f"{hd} ({p.vara}) का पंचांग — तिथि {p.tithi}, "
                f"राहु काल {p.rahu}।")
        body = (f"तिथि: {p.tithi_phrase or p.tithi}\nनक्षत्र: {p.nakshatra}\nयोग: {p.yoga}\n"
                f"करण: {p.karana}\nसूर्योदय: {p.sunrise} · सूर्यास्त: {p.sunset}\n"
                f"अभिजित मुहूर्त: {p.abhijit_start}–{p.abhijit_end}\n"
                f"राहु काल: {p.rahu}\nगुलिक काल: {p.gulika}\nयमगण्ड: {p.yama}\n\n"
                f"\n📍 समय {where} के अनुसार (IST)। राहु काल, गुलिक काल और "
                f"अभिजित मुहूर्त स्थानीय सूर्योदय-सूर्यास्त पर आधारित हैं, "
                f"इसलिए हर शहर में अलग होते हैं — अपने शहर का सटीक पंचांग "
                f"वेबसाइट पर देखें।\n"
                f"तिथि, नक्षत्र और योग सभी स्थानों पर समान रहते हैं।\n\n"
                f"पूरा पंचांग: https://medinijyotish.com/hi/panchang/{p.date}\n"
                f"सूर्योदय के समय की गणना · स्विस एफ़ेमेरिस · लाहिड़ी अयनांश।")
        hashtags = ["#पंचांग", "#राहुकाल", "#शुभमुहूर्त"]
        tags = ["पंचांग", "आज का पंचांग", "राहु काल", "शुभ मुहूर्त", "तिथि",
                "नक्षत्र", "aaj ka panchang", "panchang today", "rahu kaal",
                "hindu panchang", "vedic astrology", "medini jyotish"]
    else:
        title = f"Panchang {hd} — {p.tithi}, Rahu Kalam & Shubh Muhurat"
        lead = (f"Panchang for {hd} ({p.vara}) — {p.tithi}, "
                f"Rahu Kalam {p.rahu}.")
        body = (f"Tithi: {p.tithi_phrase or p.tithi}\nNakshatra: {p.nakshatra}\nYoga: {p.yoga}\n"
                f"Karana: {p.karana}\nSunrise: {p.sunrise} · Sunset: {p.sunset}\n"
                f"Abhijit Muhurat: {p.abhijit_start}–{p.abhijit_end}\n"
                f"Rahu Kalam: {p.rahu}\nGulika Kalam: {p.gulika}\n"
                f"Yamaghanda: {p.yama}\n\n"
                f"\n📍 Timings for {where} (IST). Rahu Kalam, Gulika Kalam and "
                f"Abhijit Muhurat are divisions of the LOCAL daylight span, so "
                f"they differ by 30-45 minutes across India and entirely "
                f"outside it — check your own city on the site.\n"
                f"Tithi, nakshatra and yoga are the same everywhere.\n\n"
                f"Full panchang: https://medinijyotish.com/panchang/{p.date}\n"
                f"Evaluated at sunrise · Swiss Ephemeris · Lahiri ayanamsha.")
        hashtags = ["#panchang", "#rahukalam", "#muhurat"]
        tags = ["panchang", "panchang today", "daily panchang", "rahu kalam",
                "rahu kaal today", "shubh muhurat", "abhijit muhurat", "tithi",
                "nakshatra", "hindu calendar", "vedic astrology",
                "aaj ka panchang", "medini jyotish"]

    # YouTube surfaces the first three hashtags above the title, so they go at
    # the top. Kept to three deliberately — more than 15 gets all of them
    # ignored, and stuffing is a demotion signal rather than a boost.
    desc = f"{' '.join(hashtags)}\n\n{lead}\n\n{body}"

    return {
        "title": title[:100],
        "description": desc,
        "tags": tags,
        "instagram_caption": f"{lead}\n\n{body.split(chr(10) + chr(10))[0]}\n\n"
                             + " ".join("#" + t.replace(" ", "") for t in tags[:12]),
        "categoryId": "22",
        "privacyStatus": "public",
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build(args) -> Path:
    lang = args.lang
    t = STR.get(lang, STR["en"])
    sc = script_for(lang)

    if sc == "deva":
        have = any(Path(c.format(w="Regular")).exists()
                   for c in FONT_CANDIDATES["deva"])
        if not have:
            print("WARNING: no Devanagari font found — Hindi text will render as "
                  "boxes. Install: apt-get install fonts-noto-core fonts-noto-ui-core",
                  file=sys.stderr)
        if not features.check("raqm"):
            print("WARNING: Pillow built without raqm. Devanagari matras and "
                  "conjuncts will be misplaced. Install libraqm.", file=sys.stderr)

    raw = fetch(args.date, args.lat, args.lon, args.sample, args.tz,
                anchor=not args.now)
    if args.dump_json:
        print(json.dumps(raw, ensure_ascii=False, indent=2))
        sys.exit(0)

    end_dt = None
    if not args.no_tithi_end and not args.sample:
        sr = field(raw, "datetime_utc", "sunrise_utc")
        try:
            base = datetime.fromisoformat(sr.replace("Z", "+00:00"))
            end_dt = tithi_end(base, raw, args.lat, args.lon)
        except (ValueError, AttributeError):
            end_dt = None
        if end_dt is None:
            print("  note: tithi end time unresolved — omitting the 'until' line",
                  file=sys.stderr)

    p = normalise(raw, lang, args.tz, args.date, end_dt)
    check(p)
    at = "current instant" if args.now else f"sunrise {p.sunrise}"
    print(f"  {p.date} {p.vara} · {p.tithi} · {p.nakshatra} · {p.yoga} · {p.karana}")
    print(f"  evaluated at: {at}   (sunset {p.sunset}, rahu {p.rahu})")

    global PLACE
    PLACE = args.place

    say = spoken(p, lang)
    if args.say_only:
        for name, _, nkey in SCENES:
            print(f"  [{name}] {respell(t[nkey].format(**say), lang)}")
        sys.exit(0)

    outdir = Path(args.out); outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="panchang_"))
    segs: list[Path] = []

    try:
        for name, fn, nkey in SCENES:
            png = work / f"{name}.png"
            fn(p, t, sc).save(png)
            if args.keep_frames:
                shutil.copy(png, outdir / f"{p.date}_{lang}_{name}.png")

            # Respelling is applied to the spoken line only — the frames keep
            # the correct transliteration.
            line = respell(t[nkey].format(**say), lang)
            mp3 = work / f"{name}.mp3"
            if args.no_tts or not tts(line, lang, mp3, args.voice):
                silence(args.fallback_seconds, mp3)
            dur = max(duration(mp3) + 0.55, 2.0)   # tail padding so speech isn't clipped

            seg = work / f"{name}.mp4"
            segment(png, mp3, seg, dur, zoom=not args.no_zoom)
            segs.append(seg)
            print(f"  scene {name:<6} {dur:5.2f}s")

        mp4 = outdir / f"panchang_{p.date}_{lang}.mp4"
        concat(segs, mp4, work)

        meta = metadata(p, lang, args.place)
        (outdir / f"panchang_{p.date}_{lang}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2))
        return mp4
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Render the daily Panchang short.")
    ap.add_argument("--lang", default="en", choices=sorted(STR))
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--lat", type=float, default=28.6139)
    ap.add_argument("--lon", type=float, default=77.2090)
    ap.add_argument("--place", default="India · Delhi coordinates",
                    help="city label shown on every frame. MUST match --lat/--lon: "
                         "Rahu Kalam and the other kalams are local-daylight "
                         "divisions and differ by 30-45 min across India.")
    ap.add_argument("--tz", type=float, default=5.5,
                    help="Hours from UTC for display times (default IST)")
    ap.add_argument("--out", default="out")
    ap.add_argument("--sample", action="store_true", help="offline canned data")
    ap.add_argument("--dump-json", action="store_true",
                    help="print the raw API payload and exit")
    ap.add_argument("--no-tithi-end", action="store_true",
                    help="skip the tithi end-time solve (saves 2-4 API calls)")
    ap.add_argument("--now", action="store_true",
                    help="evaluate at the current instant instead of at "
                         "sunrise (non-standard; the tithi will differ)")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--voice", help="override the edge-tts voice, e.g. "
                                    "en-IN-NeerjaNeural, en-GB-RyanNeural")
    ap.add_argument("--say-only", action="store_true",
                    help="print the narration lines and exit (no render)")
    ap.add_argument("--no-zoom", action="store_true", help="skip zoompan (faster)")
    ap.add_argument("--fallback-seconds", type=float, default=4.0)
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")

    mp4 = build(args)
    print(f"\n  -> {mp4}  ({mp4.stat().st_size / 1e6:.1f} MB, {duration(mp4):.1f}s)")


if __name__ == "__main__":
    main()
