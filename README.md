# Medini Jyotish — Daily Shorts Pipeline

**Read this first.** It is written to be self-contained: enough context to pick
up the project cold, without re-deriving anything or re-reading the code.

Renders a daily Panchang video from the medinijyotish.com API and publishes it
to YouTube Shorts. Instagram Reels is built into the plan but blocked on Meta
App Review.

---

## Status — 9 August 2026

| | |
|---|---|
| **YouTube (English)** | ✅ Live — `@MediniJyotishEn`, publishing manually |
| **YouTube (Hindi)** | ⬜ Built and tested, not launched. Needs Devanagari font + raqm |
| **Instagram Reels** | ⬜ Blocked on Meta App Review (not yet started — 2–4 week wait) |
| **Automation** | ⬜ Manual `./daily.sh`. Actions cron ready in PIPELINE_SPEC §5 |
| **Medini gochar track** | ⬜ Designed, not built. See PIPELINE_SPEC §8 |

Machine: macOS, Python venv at `.venv/`, ffmpeg via Homebrew.

---

## Documents

| File | Purpose |
|------|---------|
| `README.md` | This file — state, decisions, gotchas |
| `YOUTUBE_SETUP.md` | Cloud Console, OAuth, daily commands, troubleshooting |
| `PIPELINE_SPEC.md` | Architecture, scheduling, Instagram, Medini track, roadmap |
| `META_SETUP_CHECKLIST.md` | Instagram Business + Meta App Review, step by step |

## Code

| File | Purpose |
|------|---------|
| `panchang_short.py` | Renders the mp4 + a `.json` metadata sidecar |
| `deva_names.py` | Devanagari lookup table + English speech respellings |
| `publish_youtube.py` | OAuth, upload, and in-place metadata/privacy updates |
| `daily.sh` | Render → preview → confirm → upload |
| `.medini/` | Credentials. Gitignored two ways. Never commit |
| `out/` | Generated mp4s and sidecars. Gitignored |

---

## Daily use

```bash
cd ~/medini-shorts
./daily.sh                      # render, preview, confirm, upload PUBLIC
./daily.sh --privacy unlisted   # hold back for review
./daily.sh --render-only        # make the file, don't upload
./daily.sh --force              # re-upload even if today's date exists
./daily.sh --lang hi            # Hindi (needs font + raqm, see YOUTUBE_SETUP §7)
```

Useful while debugging:

```bash
python3 panchang_short.py --lang en --say-only     # narration text, no render
python3 panchang_short.py --dump-json              # raw API payload
python3 panchang_short.py --lang en --sample --no-tts   # offline, fast
python3 deva_names.py                              # 17 self-tests
python3 publish_youtube.py update --privacy public # flip latest video
```

Post before people need the information. Rahu Kalam is useless at 9 PM —
target 06:00–07:00 IST.

---

## The API contract (verified against live data)

`GET /api/v1/panchang?date=<ISO>&lat=&lon=` — the shape is **not** obvious and
the field names cost a debugging round once already:

```jsonc
{
  "datetime_utc": "2026-08-09T04:53:47+00:00",  // the instant evaluated
  "tithi":     { "tithi_name": "Ekadashi", "paksha": "Krishna",
                 "paksha_sa": "कृष्ण पक्ष", "tithi_index": 25,
                 "remaining_degrees": 0.3978 },
  "nakshatra": { "nakshatra": "Mrigashira", "nakshatra_sa": "मृगशिरा",
                 "pada": 4 },
  "yoga":      { "yoga": "Harshana" },
  "karana":    { "karana": "Balava" },
  "vara":      { "vara": "Ravivara", "vara_sa": "रविवार",
                 "vara_en": "Sunday" },
  "sunrise_utc": "...", "sunset_utc": "...",
  "rahu_kalam":  { "start_utc": "...", "end_utc": "..." },
  "gulika_kalam": {...}, "yamaghanda": {...}, "abhijit_muhurat": {...}
}
```

Three things to know:

1. **All times are UTC.** Nothing in the payload is local.
2. **Devanagari exists only for nakshatra, vara and paksha** (`*_sa`). Tithi
   name, yoga and karana come back transliterated in *every* language,
   including `/hi/`. `deva_names.py` fills the gap.
3. **The API evaluates at whatever instant you pass it** — not at sunrise.

`SAMPLE` in `panchang_short.py` is a byte-for-byte copy of a real payload.
**Keep it that way.** It previously contained invented field names, so every
`--sample` test passed while the live path was broken.

---

## Design decisions worth not re-litigating

**Evaluate at sunrise, not at run time.** A day's panchang is conventionally
the values prevailing at local sunrise. Querying at run time returns the tithi
*right now* — an 11 AM render announced Dwadashi when the day's tithi was
Ekadashi. The renderer makes two calls: one to learn sunrise, one to evaluate
at sunrise + 2 min. `--now` disables this and is labelled non-standard.

**Tithi end time is root-found, not extrapolated.** A tithi is 12° of Moon–Sun
elongation, but lunar speed varies ~10% monthly, so extrapolating
`remaining_degrees` at a mean rate lands 5–15 min out (measured: 10.6 min).
`tithi_end()` secant-iterates against the API instead — sub-minute, 2–4 calls,
and returns `None` rather than a guess if it doesn't converge.

**Render off the production VM.** The e2-micro runs a single uvicorn worker
against CPU-bound pyswisseph. ffmpeg on that box recreates the May 2026 CPU
spike, daily and at a fixed hour. Renders belong on a laptop or an Actions
runner; the VM only serves JSON and (later) hosts the mp4 for Instagram to
fetch.

**Screen text and spoken text are separate.** Frames show correct
transliterations ("Balava", 24-hour times); narration gets respellings and
12-hour times ("Baalav", "5:25 PM"). The `en-IN` voice applies English spelling
rules to Latin text, so "Karana" became "kaa-RAA-naa" and "05:48" became "oh
five forty-eight". Nobody should ever *see* "Baalav" on a card claiming
classical accuracy.

**Lead with Rahu Kalam.** Shorts is swipe-or-stay in ~2 seconds. A date-stamp
title card earns nothing; a specific window the viewer doesn't know yet does.

**Label the location.** Rahu Kalam, Gulika, Yamaghanda and Abhijit are
divisions of the *local* daylight span — Delhi's are 30–45 min off Chennai's.
Every frame carries `India · Delhi coordinates`, and the closing card turns the
caveat into the reason to visit the site. Tithi/nakshatra/yoga are the same
everywhere at a given instant.

**English first is a pilot, not a demand signal.** Chosen because English needs
no Devanagari font and no raqm, so only the pipeline itself can break. Hindi is
the larger audience by far and is where this actually pays off — don't read
low English numbers as the format failing.

**Deterministic content only.** Computed values, no interpretation. The
platform's differentiation is computational accuracy and source provenance; a
daily unfalsifiable forecast puts it on bhrigusadhu's turf where it has no
edge. Same rule governs the planned Medini track.

---

## Gotchas that cost time

| Symptom | Cause |
|---|---|
| Boxes instead of Hindi | No Devanagari font — `brew install --cask font-noto-sans-devanagari` |
| Matras on wrong characters | Pillow built without raqm — check `features.check('raqm')` |
| `invalid_grant` after ~7 days | OAuth consent screen left in *Testing*. Must be **Published** |
| `insufficientPermissions` on update | `youtube.upload` is insert-only; needs the `youtube` scope too |
| `redirect_uri_mismatch` | OAuth client created as *Web application*; must be **Desktop app** |
| `CHANNEL MISMATCH` | Wrong channel active at youtube.com during consent |
| Wrong tithi | Rendered with `--now`, or the sunrise anchor failed |
| Empty fields / blank card | API field rename — `check()` aborts; inspect with `--dump-json` |
| venv "not found" after moving | Virtualenvs hardcode their path. Delete and recreate |

**You cannot replace a YouTube video file.** Metadata and privacy are editable
in place via `publish_youtube.py update`; the video itself is not. A bad render
means delete + re-upload under a new URL. Hence `--privacy unlisted` on any day
the renderer changed.

---

## Open items

**Site bugs found while building this** (both live, both visible to every
visitor):

1. Panchang pages print **UTC** while labelling it local time — today's page
   shows Rahu Kalam `03:37 – 05:16` where Delhi needs `09:07 – 10:46 IST`.
   The videos are correct; the site is not.
2. `/hi/` shows tithi, yoga and karana in **Latin transliteration** on an
   otherwise Devanagari page. `deva_names.py` is a drop-in fix for the SSR
   templates — a lookup table over closed classical vocabulary, no
   interpretation risk.

**Backend improvement:** add `tithi_end_utc` (and `nakshatra_end_utc`) to the
API. `panchang_engine.py` can root-find these directly against Swiss Ephemeris
in one pass, which removes 2–4 calls per render and lets the panchang pages
show "Ekadashi upto 10:47" like a printed almanac.

**Roadmap:** Meta App Review now (longest wait) → a week of manual runs →
Actions cron → Hindi at day 30 → Telugu at day 60 (fix the `/te/` nginx timeout
first) → Medini gochar track once panchang is stable.
