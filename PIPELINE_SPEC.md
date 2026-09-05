# Medini Jyotish — Daily Shorts Pipeline

**Status:** v2 — YouTube English shipped, Instagram pending App Review
**Updated:** 2026-08-09
**Owner:** Rahul

> Start at `README.md` for current state and design rationale.
> `YOUTUBE_SETUP.md` has the operational commands.
> `META_SETUP_CHECKLIST.md` has the Instagram approval path.
>
> This document is the architecture and the parts not yet built.

**Shipped:** renderer, Devanagari name table, English speech respellings,
sunrise anchoring, tithi end-time solver, YouTube upload + in-place update,
channel guard, location labelling.
**Not built:** GitHub Actions cron (§5), Instagram publish (§7), Medini gochar
track (§8), Hindi/Telugu channels (§4).

---

## 1. Objective

Publish one panchang short per language per day to YouTube Shorts and Instagram
Reels, fully unattended, with zero incremental load on the production VM.
A second track — a Medini gochar short — runs on the same rails with deterministic
content only.

Success = the pipeline runs for 30 consecutive days without manual intervention,
and a failed day is loud rather than silent.

---

## 2. Core architectural decision: render off the VM

The e2-micro runs a **single uvicorn worker** against CPU-bound pyswisseph. Video
encoding is the most CPU-hungry thing in this whole product. Putting ffmpeg on
that box recreates the May 2026 CPU spike, except daily and at a fixed hour.

**Rendering happens in GitHub Actions.** The VM's only role is to serve the
panchang JSON it already serves, and to host the finished mp4 at a public URL
(which is a static file read, effectively free).

```
GitHub Actions runner (ubuntu-latest, 2 vCPU, free minutes)
  │
  ├─ GET medinijyotish.com/api/v1/panchang/today      ← 1 cached API hit
  ├─ render 5 × PNG (Pillow)                          ← ~2s
  ├─ TTS per scene (edge-tts)                         ← ~8s
  ├─ ffmpeg assemble                                  ← ~35s
  ├─ scp mp4 → VM /var/www/shorts/                    ← for the IG public URL
  ├─ YouTube videos.insert                            ← resumable upload
  └─ Instagram container → publish
```

Total VM impact per language per day: one 5-minute-cached API read, one static
file write. That is the whole point.

**Cache interaction:** `/api/v1/panchang/today` is cached 5 min. Fire the render
job at a fixed time and the first language pays the compute, the rest hit cache.
Do *not* parallelise the three language jobs across separate runners hitting the
API simultaneously — that is exactly the parallel-request pattern the single
worker cannot absorb. Run languages sequentially in one job, or stagger by 90s.

---

## 3. Stages

### 3.1 Data

Source: `GET /api/v1/panchang?date=…&lat=…&lon=…`. The exact payload shape is
documented in `README.md` — it is not guessable, and getting it wrong cost a
debugging round.

Two calls per render, sequential: one to learn today's sunrise, one to evaluate
**at sunrise + 2 min**. The API evaluates at whatever instant it is handed, and
a day's panchang is conventionally the values prevailing at local sunrise —
querying at run time announced Dwadashi on a day whose tithi was Ekadashi.
Add 2–4 more calls if the tithi end-time solve runs (`--no-tithi-end` skips it).

The renderer's `dig()` and `field()` helpers tolerate renames — dotted paths
first, then a recursive key search. `check()` then asserts all thirteen values
are non-empty and **aborts before encoding** if any are missing, naming them.
A silent `KeyError` at 5:30 AM is a missed post; a blank Rahu Kalam is worse
than a missed post.

**⚠️ Timezone bug to fix.** The SSR panchang page currently prints raw UTC while
labelling the section "displayed in your local timezone". For 2026-08-08 Delhi it
shows `Sunrise: 00:17 UTC` — correct as UTC, but a reader in Delhi expects
**05:47**. Rahu Kalam shows `03:37 – 05:16` where it should read `09:07 – 10:46`
IST.

The renderer converts explicitly (`--tz 5.5`) and never prints a raw API time, so
the videos are correct regardless. But this should be fixed on the site too — a
panchang page showing UTC sunrise undermines the accuracy positioning that the
whole platform rests on, and it is the kind of error a competitor screenshots.

### 3.2 Scenes

Six scenes, ~40s with narration. Ordered for retention, not for completeness:

| # | Scene | Content | Why |
|---|-------|---------|-----|
| 1 | Rahu hook | **"Don't Start Anything" + Rahu Kalam window** | Shorts is swipe-or-stay in 2s. A specific window the viewer doesn't know beats a date stamp |
| 2 | Tithi | Date, vara, tithi, "until HH:MM" | The most-searched value, with the rollover an almanac would print |
| 3 | Limbs | Nakshatra, yoga, karana, sunrise, sunset | The substance |
| 4 | Shubh | Abhijit Muhurat | Actionable — "when can I start something" |
| 5 | Avoid | Rahu Kalam, Gulika, Yamaghanda | Repeating Rahu Kalam aids recall |
| 6 | CTA | Location caveat → domain | See "location" below |

**Location labelling.** Rahu Kalam, Gulika, Yamaghanda and Abhijit are eighths
of the *local* daylight span, so Delhi's differ from Chennai's by 30–45 min.
Every frame footers `medinijyotish.com · India · Delhi coordinates`, and the
CTA card makes the caveat the call to action — an honesty requirement doing
double duty as the funnel. Tithi/nakshatra/yoga are identical everywhere at a
given instant, so the description says so explicitly.

Other cities are `--lat/--lon/--place`, but **don't publish city variants to
one channel** — near-identical videos read as repetitive and clutter the
subscriber feed. Per-city belongs on the site, not in Shorts.

**Safe area:** content lives between y=300 and y=1480 of 1080×1920. Instagram
overlays the caption and action rail over roughly the bottom 22% and the top 14%;
YouTube Shorts is similar. Anything outside that band will be covered on one
platform or the other.

**Motion:** slow zoompan (1.00 → 1.09 over the scene). Static frames measurably
lose retention on Reels. Costs ~15s of encode; worth it.

### 3.3 Narration

**Choice: edge-tts.** Rationale:

| Option | Verdict |
|--------|---------|
| **edge-tts** | Free, no API key, neural Hindi/Telugu/Tamil voices that pronounce Sanskrit terms intelligibly. Unofficial endpoint — accept the availability risk, keep a fallback. **Chosen.** |
| Google Cloud TTS | Best quality, but needs billing + key rotation, and you just rebuilt that billing account. Keep as the fallback if edge-tts breaks. |
| Piper | Fully local and offline-safe, but the Hindi voice mangles Sanskrit compounds. |
| espeak-ng | Robotic. Fine for CI smoke tests, not for publishing. |

Scene duration is **driven by narration length + 0.55s tail padding**, not fixed.
Fixed durations either clip the last word or leave dead air, and both read as
low-effort.

If TTS fails, the renderer substitutes silence and still produces a valid mp4.
That is deliberate: a silent short is recoverable, a crashed job at 5:30 AM is a
gap in the upload streak.

**Screen text and spoken text are generated separately.** The `en-IN` voice
applies English spelling rules to Latin script, so raw values are mispronounced:
"Karana" → "kaa-RAA-naa", "sunrise" → "suunreesee", "05:48" → "oh five forty
eight". Two layers fix this, both narration-only:

- `spoken()` in `panchang_short.py` — 24-hour times become "5:48 AM" / "5:25 PM
  to 7:04 PM"; ISO dates become "9 August 2026". Hindi gets
  "शाम 5 बजकर 25 मिनट" with the correct period word.
- `respell()` in `deva_names.py` — 74 phonetic respellings ("Balava" →
  "Baalav", "Abhijit Muhurat" → "Abhijeet Muhoort"). No-op for Devanagari,
  since the Hindi voice reads देवनागरी natively.

Frames keep the correct transliteration throughout. Printing "Baalav" on a card
that claims classical accuracy would be self-defeating. Preview with
`--say-only`; audition voices with `--voice`.

### 3.4 Fonts

Devanagari needs both:

1. A Devanagari font — `brew install --cask font-noto-sans-devanagari` on
   macOS, `apt-get install fonts-noto-core fonts-noto-ui-core` on the runner
2. **Pillow built with raqm** — without it, matras and conjuncts render in the
   wrong positions. This is subtle enough to ship broken. The renderer warns on
   both at startup; treat the warning as a build failure in CI.

---

## 4. Language rollout

Don't launch three channels cold on day one — a channel with 30 videos and 4
subscribers looks abandoned. Sequence:

1. **English first, alone, for 30 days.** Chosen to keep the first launch
   simple: English needs no Devanagari font and no raqm shaper, so the only
   things that can break are the pipeline itself and the upload path. Debug
   those in isolation.
2. **Hindi at day 30.** The larger audience by far, and the language this
   audience actually searches in — so this is the one that matters
   commercially. It is fully built and tested (`--lang hi`), gated only on
   installing the font and shaper. Do not let it slip; English is the pilot,
   Hindi is the product.
3. **Telugu at day 60.** You already have `/te/` — fix the nginx timeout on that
   route before pointing video traffic at it.

Note the tradeoff being accepted: English-first is easier to launch but is
*not* where the panchang audience is. Treat the first 30 days as a shakedown of
the machinery rather than a read on demand — low English numbers should not be
interpreted as the format failing.

Same mp4 goes to YouTube Shorts and Instagram Reels. Do not cross-post the
watermarked version — render once, upload the clean file to both.

---

## 5. Scheduling

GitHub Actions cron is **UTC** *and* best-effort: scheduled runs routinely fire
hours late and occasionally skip a day, so a same-morning render kept missing
its window. We instead render a **whole week in one run** and let YouTube's
`publishAt` release each short at 06:00 IST on its own day — a weekly batch has
days of slack, so cron jitter no longer matters. Panchang is a pure
astronomical calculation, so a future date renders as correctly as today
(each date is anchored to its own sunrise; see §3).

Cron `30 19 * * 6` = Sat 19:30 UTC = **Sun 01:00 IST** (cron's day-of-week is
UTC, so Sunday-IST lands on Saturday's UTC date). Post before the audience
needs the information, not after — Rahu Kalam is only useful seen beforehand.

```yaml
# .github/workflows/daily-short.yml  (filename kept for run-history continuity)
name: weekly-panchang-shorts
on:
  schedule:
    - cron: '30 19 * * 6'      # Sat 19:30 UTC = Sun 01:00 IST; renders Sun→Sat
  workflow_dispatch:
    inputs:
      date:  { description: 'week start YYYY-MM-DD (blank = today IST)', required: false }
      days:  { description: 'how many days to render', default: '7' }
      langs: { description: 'space-separated', default: 'en' }

jobs:
  render:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: System deps
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y ffmpeg fonts-noto-core fonts-noto-ui-core libraqm0
      - run: pip install pillow edge-tts google-api-python-client google-auth requests
      - name: Render
        run: |
          for L in ${{ github.event.inputs.langs || 'hi' }}; do
            python3 panchang_short.py --lang "$L" --out out/ \
              ${{ github.event.inputs.date && format('--date {0}', github.event.inputs.date) || '' }}
            sleep 90        # stagger: never hit the single worker in parallel
          done
      - name: Publish
        env:
          YT_CLIENT_ID:      ${{ secrets.YT_CLIENT_ID }}
          YT_CLIENT_SECRET:  ${{ secrets.YT_CLIENT_SECRET }}
          YT_REFRESH_TOKEN:  ${{ secrets.YT_REFRESH_TOKEN }}
          IG_USER_ID:        ${{ secrets.IG_USER_ID }}
          IG_ACCESS_TOKEN:   ${{ secrets.IG_ACCESS_TOKEN }}
          VM_SSH_KEY:        ${{ secrets.VM_SSH_KEY }}
        run: |
          for F in out/*.mp4; do
            python3 publish_youtube.py upload "$F" \
              --privacy public --channel @MediniJyotishEn
          done
          # Instagram publish goes here once App Review clears
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: shorts, path: out/, retention-days: 7 }
```

Cost: ~3 min/day for one language. Free tier is 2,000 min/month on private repos
and unlimited on public. Not a constraint.

---

## 6. YouTube upload

- **Endpoint:** `videos.insert`, resumable upload.
- **Quota:** default 10,000 units/day. `videos.insert` dropped from ~1,600 to
  ~100 units in the December 2025 revision, so the practical ceiling went from
  ~6 uploads/day to ~100. Three languages = ~300 units. Non-issue.
  The expensive call is now `search.list` (100 units) — don't put search in a loop.
- **Scopes:** `youtube.upload` **and** `youtube` **and** `youtube.readonly`.
  `youtube.upload` is insert-only — it cannot modify an existing video, so
  privacy flips and metadata edits 403 without the `youtube` scope. Learned
  the hard way; the scope must also be added in the Cloud consent screen, not
  just in the code.
- **Auth:** one-time OAuth consent per channel → store the **refresh token** as a
  repo secret. Refresh tokens for apps in *Testing* publishing status expire in
  7 days — push the Cloud Console app to *Published* (or add yourself as a test
  user and accept re-consent, which you will forget to do). The OAuth client
  must be of type **Desktop app**; a Web application client fails with
  `redirect_uri_mismatch`.
- **Channel guard:** every upload re-reads which channel the credentials
  actually control and aborts on mismatch. One Google account owning both a
  Hindi and an English channel makes mis-targeting easy, and **YouTube cannot
  move a video between channels afterwards.**
- **Editable after the fact:** title, description, tags and privacy, via
  `publish_youtube.py update` (`videos.update`, ~50 units). Note it *replaces*
  each part it is sent, so the command reads current values and overlays only
  the changes. `--at` schedules a public release (private + `publishAt`).
- **Not editable:** the video file itself. Bad render = delete and re-upload
  under a new URL.
- **Shorts classification** is automatic from aspect ratio (9:16) and duration
  (≤3 min). No `#Shorts` tag needed, though it does no harm.
- **Category:** 22 (People & Blogs). 24 (Entertainment) also works; avoid 25 (News).

**Compliance note:** YouTube treats astrology as sensitive for monetisation, not
for hosting. Content is fine. Don't expect AdSense revenue to be the business
model here — the channel's job is to feed medinijyotish.com.

---

## 7. Instagram upload

This is the long pole. Not the code — the approval.

**Requirements:**
- Instagram **Business** account (Creator accounts cannot publish via API)
- Linked Facebook Page
- Meta app with `instagram_business_basic` + `instagram_business_content_publish`
  (these replaced `instagram_basic` / `instagram_content_publish`, deprecated
  January 2025)
- The video must be at a **public HTTPS URL** — Meta pulls it, you do not push
  bytes. Host at `medinijyotish.com/shorts/<date>-<lang>.mp4`. Static nginx
  serve, negligible load.

**Two-step container model:**

```
POST /{ig-user-id}/media
     media_type=REELS & video_url=… & caption=…      → creation_id
GET  /{creation_id}?fields=status_code               → poll until FINISHED
POST /{ig-user-id}/media_publish?creation_id=…       → published
```

Poll every 5s, cap at 60 attempts. Containers commonly take 30–90s to process
and expire after 24h. Publishing a container still in `IN_PROGRESS` silently
fails — always poll to `FINISHED`.

**Rate limit:** 100 API-published posts per rolling 24h across all media types.
Three languages/day uses 3% of it.

**Timeline shortcut:** while your Meta app is in *Development* mode, it can act
on accounts that have a role on the app (admin/developer/tester) without App
Review. Your own IG Business account qualifies. So you can build, test, and
plausibly run the whole thing before review completes — start the review in
parallel, don't block on it. Verify this against current Meta docs before
depending on it.

Budget **2–4 weeks** for App Review. Start it this week.

---

## 8. Medini short (second track)

Per the decision: **deterministic gochar + sourced citation. No forecast.**

Source: `GET /api/v1/graha/positions?format=summary` plus
`/api/v1/medini/predictions`.

Format:
1. Hook — "Today's gochar" + the single most notable placement
2. Positions — 3–4 grahas with rashi + nakshatra
3. The classical rule — quoted, **with chapter and verse on screen**
4. Attribution — Brihat Samhita / BPHS, explicitly named
5. CTA

**Why no forecast:** the platform's entire differentiation is source provenance
and computational accuracy. A daily interpretive prediction is unfalsifiable
content that any WordPress blog can produce — it puts you on bhrigusadhu's turf
where you have no advantage, and it dilutes the one signal you have that they
don't. Showing "here is the transit, here is the classical rule, here is where
the rule comes from" is content nobody else in this space can make.

**Sourcing discipline carries over:** the same distinction from the site applies
in video. Mundane rules → Brihat Samhita. Natal/dasha → Brihat Parashara Hora
Shastra or Brihat Jataka. SBC → Narapatijayacharya. Sanghatta Chakra → modern
(K.N. Rao / M.S. Mehta lineage), and label it as modern. An on-screen citation
that conflates these is worse than no citation, because it is checkable.

Ship this **after** the panchang track has run clean for two weeks.

---

## 9. Failure modes

| Failure | Behaviour | Mitigation |
|---------|-----------|------------|
| API down / 5xx | No video | Retry ×3 with backoff; on final failure open a GitHub issue via API so it's visible |
| Field renamed | Blank value on screen | ✅ `dig()`/`field()` fallback + `check()` aborts pre-encode, naming the missing fields |
| Tithi rolled over before render | Wrong tithi announced | ✅ Anchored to sunrise + 2 min, not run time |
| Tithi end solve doesn't converge | — | ✅ Returns `None`; the "until" line is omitted rather than guessed |
| Wrong channel targeted | Unrecoverable | ✅ Channel guard aborts before upload |
| edge-tts endpoint dead | Silent video | Falls back to silence, still publishes; alert to switch to Google TTS |
| Missing Devanagari font | Tofu boxes | Startup warning → make it a hard CI failure |
| No raqm | Misplaced matras | Startup warning; visually inspect the first Hindi render |
| YouTube token expired | Upload 401 | Publish app to *Published* status; alert on 401 |
| IG container never FINISHED | No post | Poll cap + alert; container expires in 24h anyway |
| Duplicate post (re-run) | Two videos | Idempotency: before inserting, scan recent uploads for the ISO date in the title *or description* (the title carries a human date; the canonical URL in the description carries the ISO date). This is what makes the weekly workflow's twice-a-run gap-fill safe. |

**Guardrail:** never auto-publish a video whose panchang values failed the
non-empty assertion. A wrong Rahu Kalam is worse than a missed day — people act
on these timings.

---

## 10. Cost

| Item | Cost |
|------|------|
| GitHub Actions | ₹0 (free tier) |
| edge-tts | ₹0 |
| YouTube Data API | ₹0 |
| Instagram Graph API | ₹0 |
| VM (static mp4 hosting) | ₹0 marginal |
| Storage — ~2 MB/video × 3 lang × 365 | ~2 GB/yr; prune at 30 days |

Effectively zero. The cost is your attention during the first two weeks.

---

## 11. Build order

1. ~~Renderer~~ — done, verified against live 2026-08-09 data
2. ~~YouTube channel (English) + OAuth~~ — done, `@MediniJyotishEn` publishing
3. ~~`publish_youtube.py`~~ — done, including in-place `update`
4. **Start Meta App Review** ← longest clock, nothing depends on it, start now
5. Fix the UTC/IST display bug on the SSR panchang pages
6. Fix the Latin transliterations on `/hi/` (reuse `deva_names.py`)
7. Run `./daily.sh` manually for a week — catch tithi rollovers, month
   boundaries, pronunciation misses
8. Add `tithi_end_utc` to the API; drop the client-side solver
9. Add nginx location for `/shorts/`; add the IG publish path
10. Enable the Actions cron; watch it for a week
11. Hindi at day 30, Telugu at day 60
12. Medini gochar track once panchang is stable

Steps 4–6 are independent of everything else. Step 4 unblocks the longest wait;
5 and 6 are live bugs every visitor can see.
