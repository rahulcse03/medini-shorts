#!/usr/bin/env python3
"""
Devanagari names for panchang vocabulary.

Why this exists: the API returns tithi, yoga and karana as IAST-ish
transliterations ("Krishna Ekadashi", "Vyaghata", "Bava") in every language,
including /hi/. Nakshatra and paksha carry Devanagari, the rest do not. A Hindi
short that says "आज की तिथि है Krishna Ekadashi" reads as machine output, and
the TTS pronounces the Latin string as English.

This is a closed, fixed vocabulary from the classical calendar — 16 tithis,
27 nakshatras, 27 yogas, 11 karanas, 7 varas, 12 rashis, 9 grahas. It is a
lookup table, not a translation, so there is no interpretation risk.

Useful beyond the video pipeline: the same table would fix the /hi/ panchang
page, whose tithi/yoga/karana fields have the identical problem.

    from deva_names import localise
    localise("Krishna Ekadashi", "hi")   -> 'कृष्ण एकादशी'
    localise("Rohini (Pada 4)", "hi")    -> 'रोहिणी (पाद ४)'
"""

from __future__ import annotations

import re

# Devanagari script languages this table applies to.
DEVA_LANGS = {"hi", "mr", "sa", "ne"}

PAKSHA = {
    "Shukla": "शुक्ल",
    "Krishna": "कृष्ण",
    "Shukla Paksha": "शुक्ल पक्ष",
    "Krishna Paksha": "कृष्ण पक्ष",
}

TITHI = {
    "Pratipada": "प्रतिपदा",
    "Dwitiya": "द्वितीया",  "Dvitiya": "द्वितीया",
    "Tritiya": "तृतीया",
    "Chaturthi": "चतुर्थी",
    "Panchami": "पञ्चमी",
    "Shashthi": "षष्ठी",    "Shasthi": "षष्ठी",
    "Saptami": "सप्तमी",
    "Ashtami": "अष्टमी",
    "Navami": "नवमी",
    "Dashami": "दशमी",
    "Ekadashi": "एकादशी",
    "Dwadashi": "द्वादशी",  "Dvadashi": "द्वादशी",
    "Trayodashi": "त्रयोदशी",
    "Chaturdashi": "चतुर्दशी",
    "Purnima": "पूर्णिमा",
    "Amavasya": "अमावस्या",
}

NAKSHATRA = {
    "Ashwini": "अश्विनी",       "Ashvini": "अश्विनी",
    "Bharani": "भरणी",
    "Krittika": "कृत्तिका",
    "Rohini": "रोहिणी",
    "Mrigashira": "मृगशिरा",    "Mrigashirsha": "मृगशिरा",
    "Ardra": "आर्द्रा",
    "Punarvasu": "पुनर्वसु",
    "Pushya": "पुष्य",
    "Ashlesha": "आश्लेषा",
    "Magha": "मघा",
    "Purva Phalguni": "पूर्वा फाल्गुनी",
    "Uttara Phalguni": "उत्तरा फाल्गुनी",
    "Hasta": "हस्त",
    "Chitra": "चित्रा",
    "Swati": "स्वाति",          "Svati": "स्वाति",
    "Vishakha": "विशाखा",
    "Anuradha": "अनुराधा",
    "Jyeshtha": "ज्येष्ठा",
    "Mula": "मूल",              "Moola": "मूल",
    "Purva Ashadha": "पूर्वाषाढ़ा",
    "Uttara Ashadha": "उत्तराषाढ़ा",
    "Shravana": "श्रवण",
    "Dhanishta": "धनिष्ठा",     "Dhanishtha": "धनिष्ठा",
    "Shatabhisha": "शतभिषा",    "Shatataraka": "शतभिषा",
    "Purva Bhadrapada": "पूर्वा भाद्रपदा",
    "Uttara Bhadrapada": "उत्तरा भाद्रपदा",
    "Revati": "रेवती",
}

YOGA = {
    "Vishkambha": "विष्कम्भ",
    "Priti": "प्रीति",          "Preeti": "प्रीति",
    "Ayushman": "आयुष्मान्",
    "Saubhagya": "सौभाग्य",
    "Shobhana": "शोभन",
    "Atiganda": "अतिगण्ड",
    "Sukarma": "सुकर्मा",       "Sukarman": "सुकर्मा",
    "Dhriti": "धृति",
    "Shula": "शूल",
    "Ganda": "गण्ड",
    "Vriddhi": "वृद्धि",
    "Dhruva": "ध्रुव",
    "Vyaghata": "व्याघात",
    "Harshana": "हर्षण",
    "Vajra": "वज्र",
    "Siddhi": "सिद्धि",
    "Vyatipata": "व्यतीपात",
    "Variyan": "वरीयान्",
    "Parigha": "परिघ",
    "Shiva": "शिव",
    "Siddha": "सिद्ध",
    "Sadhya": "साध्य",
    "Shubha": "शुभ",
    "Shukla": "शुक्ल",
    "Brahma": "ब्रह्म",
    "Indra": "इन्द्र",
    "Vaidhriti": "वैधृति",
}

KARANA = {
    "Bava": "बव",
    "Balava": "बालव",
    "Kaulava": "कौलव",
    "Taitila": "तैतिल",
    "Gara": "गर",               "Garaja": "गर",
    "Vanija": "वणिज",
    "Vishti": "विष्टि",         "Bhadra": "भद्रा",
    "Shakuni": "शकुनि",
    "Chatushpada": "चतुष्पाद",
    "Naga": "नाग",
    "Kimstughna": "किंस्तुघ्न",
}

VARA = {
    "Ravivara": "रविवार",    "Sunday": "रविवार",
    "Somavara": "सोमवार",    "Monday": "सोमवार",
    "Mangalavara": "मंगलवार", "Tuesday": "मंगलवार",
    "Budhavara": "बुधवार",   "Wednesday": "बुधवार",
    "Guruvara": "गुरुवार",   "Thursday": "गुरुवार",
    "Brihaspativara": "गुरुवार",
    "Shukravara": "शुक्रवार", "Friday": "शुक्रवार",
    "Shanivara": "शनिवार",   "Saturday": "शनिवार",
}

RASHI = {
    "Mesha": "मेष", "Vrishabha": "वृषभ", "Mithuna": "मिथुन", "Karka": "कर्क",
    "Simha": "सिंह", "Kanya": "कन्या", "Tula": "तुला", "Vrishchika": "वृश्चिक",
    "Vrischika": "वृश्चिक", "Dhanu": "धनु", "Makara": "मकर", "Kumbha": "कुम्भ",
    "Meena": "मीन",
}

GRAHA = {
    "Surya": "सूर्य", "Sun": "सूर्य",
    "Chandra": "चन्द्र", "Moon": "चन्द्र",
    "Mangala": "मंगल", "Mangal": "मंगल", "Mars": "मंगल",
    "Budha": "बुध", "Mercury": "बुध",
    "Guru": "गुरु", "Brihaspati": "गुरु", "Jupiter": "गुरु",
    "Shukra": "शुक्र", "Venus": "शुक्र",
    "Shani": "शनि", "Saturn": "शनि",
    "Rahu": "राहु", "Ketu": "केतु",
}

# Longest-phrase-first so "Purva Phalguni" wins over "Purva" + "Phalguni".
_TABLE: dict[str, str] = {}
for _t in (NAKSHATRA, TITHI, YOGA, KARANA, VARA, PAKSHA, RASHI, GRAHA):
    _TABLE.update(_t)
_PHRASES = sorted(_TABLE, key=len, reverse=True)

_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def to_deva_digits(s: str) -> str:
    return s.translate(_DIGITS)


def localise(value: str, lang: str = "hi", digits: bool = True) -> str:
    """Map a panchang value to Devanagari, leaving unknown tokens untouched.

    Unknown input passes through rather than raising: a stray Latin word on
    screen is survivable, a crash at 5:30 AM is not.
    """
    if not value or lang not in DEVA_LANGS:
        return value

    out = value
    for phrase in _PHRASES:
        if phrase in out:
            out = re.sub(rf"\b{re.escape(phrase)}\b", _TABLE[phrase], out)

    out = out.replace("Pada", "पाद").replace("Paksha", "पक्ष")
    if digits:
        out = to_deva_digits(out)

    # Collapse a duplicated bilingual value like "Rohini रोहिणी" -> "रोहिणी"
    parts = out.split()
    seen, deduped = set(), []
    for p in parts:
        if p not in seen:
            deduped.append(p)
            seen.add(p)
    return " ".join(deduped).strip()


# ---------------------------------------------------------------------------
# Speech respellings for Latin-script voices
# ---------------------------------------------------------------------------
#
# edge-tts en-IN reads Latin text with English spelling rules, so IAST-style
# transliterations come out wrong: "Karana" becomes "kaa-RAA-naa" when करण has
# two short a's, and "Balava" becomes "bal-va" when बालव has a long first ā.
#
# These respellings are pronunciation hints for the narration ONLY. On-screen
# text keeps the correct transliteration — nobody should read "Baalav" on a
# card that claims classical accuracy.
#
# Rule of thumb used below: double vowels for Sanskrit long vowels (ā -> aa,
# ī -> ee), and drop the trailing inherent "a" that Hindi elides but English
# readers voice ("Harshana" -> "Harshan").

SPEECH_EN = {
    # structural terms
    "Panchang": "Punchaang",
    "Karana": "Karan",
    "Nakshatra": "Nakshatra",
    "Muhurat": "Muhoort",
    "Abhijit": "Abhijeet",
    "Rahu Kalam": "Raahu Kaalam",
    "Gulika Kalam": "Gulik Kaalam",
    "Yamaghanda": "Yama-gund",
    "Tithi": "Tithee",

    # karanas
    "Balava": "Baalav", "Kaulava": "Kowlav", "Taitila": "Taitil",
    "Vanija": "Vanij", "Chatushpada": "Chatushpaad", "Naga": "Naag",
    "Kimstughna": "Kinstughn", "Bava": "Bav", "Gara": "Gar",

    # tithis
    "Pratipada": "Prati-pada", "Dwitiya": "Dwiteeya", "Tritiya": "Triteeya",
    "Chaturthi": "Chaturthee", "Panchami": "Panchamee", "Shashthi": "Shashthee",
    "Saptami": "Saptamee", "Ashtami": "Ashtamee", "Navami": "Navamee",
    "Dashami": "Dashamee", "Ekadashi": "Ekaadashee", "Dwadashi": "Dwaadashee",
    "Trayodashi": "Trayodashee", "Chaturdashi": "Chaturdashee",
    "Purnima": "Poornima", "Amavasya": "Amaavasya",

    # yogas that mislead an English reader
    "Vishkambha": "Vishkambh", "Priti": "Preeti", "Ayushman": "Aayushmaan",
    "Saubhagya": "Saubhaagya", "Shobhana": "Shobhan", "Atiganda": "Atigand",
    "Dhriti": "Dhriti", "Shula": "Shool", "Ganda": "Gand", "Dhruva": "Dhruv",
    "Vyaghata": "Vyaaghaat", "Harshana": "Harshan", "Vyatipata": "Vyateepaat",
    "Variyan": "Vareeyaan", "Parigha": "Parigh", "Sadhya": "Saadhya",
    "Brahma": "Brahm", "Vaidhriti": "Vaidhriti",

    # nakshatras most often mangled
    "Mrigashira": "Mrigasheera", "Ashwini": "Ashwinee", "Bharani": "Bharanee",
    "Krittika": "Krittika", "Rohini": "Rohinee", "Ardra": "Aardra",
    "Punarvasu": "Punarvasu", "Ashlesha": "Aashlesha", "Magha": "Maghaa",
    "Phalguni": "Phaalgunee", "Chitra": "Chitraa", "Swati": "Swaatee",
    "Vishakha": "Vishaakha", "Anuradha": "Anuraadha", "Jyeshtha": "Jyeshtha",
    "Mula": "Moola", "Ashadha": "Aashaadha", "Shravana": "Shravan",
    "Dhanishta": "Dhanishtha", "Shatabhisha": "Shata-bhisha",
    "Bhadrapada": "Bhaadra-pada", "Revati": "Revatee",
}

_SPEECH_PHRASES = sorted(SPEECH_EN, key=len, reverse=True)


def respell(text: str, lang: str = "en") -> str:
    """Rewrite Sanskrit terms phonetically for a Latin-script TTS voice.

    No-op for Devanagari languages — the Hindi voice reads देवनागरी natively
    and respelling would only corrupt it.
    """
    if not text or lang in DEVA_LANGS:
        return text
    out = text
    for phrase in _SPEECH_PHRASES:
        if phrase in out:
            out = re.sub(rf"\b{re.escape(phrase)}\b", SPEECH_EN[phrase], out)
    return out


def coverage() -> dict[str, int]:
    return {"tithi": len(TITHI), "nakshatra": len(NAKSHATRA), "yoga": len(YOGA),
            "karana": len(KARANA), "vara": len(VARA), "rashi": len(RASHI),
            "graha": len(GRAHA), "total_keys": len(_TABLE),
            "speech_respellings": len(SPEECH_EN)}


if __name__ == "__main__":
    checks = [
        ("Krishna Ekadashi", "कृष्ण एकादशी"),
        ("Shukla Purnima", "शुक्ल पूर्णिमा"),
        ("Rohini (Pada 4)", "रोहिणी (पाद ४)"),
        ("Vyaghata", "व्याघात"),
        ("Bava", "बव"),
        ("Shanivara", "शनिवार"),
        ("Purva Phalguni", "पूर्वा फाल्गुनी"),
        ("Uttara Ashadha", "उत्तराषाढ़ा"),
        ("Rohini रोहिणी", "रोहिणी"),
        ("Unknown Thing", "Unknown Thing"),
    ]
    bad = 0
    for src, want in checks:
        got = localise(src, "hi")
        ok = got == want
        bad += not ok
        print(f"  {'ok ' if ok else 'FAIL'}  {src!r:26} -> {got!r}"
              + ("" if ok else f"   want {want!r}"))

    print()
    speech = [
        ("Karana, Balava.", "Karan, Baalav.", "en"),
        ("Yoga, Harshana.", "Yoga, Harshan.", "en"),
        ("Rahu Kalam is 5 PM", "Raahu Kaalam is 5 PM", "en"),
        ("Abhijit Muhurat", "Abhijeet Muhoort", "en"),
        ("nakshatra is Mrigashira", "nakshatra is Mrigasheera", "en"),
        ("Krishna Ekadashi", "Krishna Ekaadashee", "en"),
        ("करण बालव", "करण बालव", "hi"),          # Devanagari must pass through
    ]
    for src, want, lg in speech:
        got = respell(src, lg)
        ok = got == want
        bad += not ok
        print(f"  {'ok ' if ok else 'FAIL'}  [{lg}] {src!r:26} -> {got!r}"
              + ("" if ok else f"   want {want!r}"))

    print(f"\n  {coverage()}")
    raise SystemExit(1 if bad else 0)
