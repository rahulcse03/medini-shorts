# YouTube Setup — English first, manual daily run

One-time setup is ~20 minutes. After that the daily run is one command.

Starting in English removes the two fiddliest dependencies — the Devanagari
font and the raqm text shaper. Neither is needed until you add Hindi, so the
whole font section below is deferred to §7.

| File | Role |
|------|------|
| `panchang_short.py` | Renders the mp4 + metadata sidecar |
| `publish_youtube.py` | OAuth + resumable upload |
| `daily.sh` | Render → preview → confirm → upload |
| `deva_names.py` | Devanagari lookup table — not needed yet, see §7 |

---

## 1. Target channel

**Medini Jyotish English — `@MediniJyotishEn`**

This handle is pinned in `daily.sh` (the `CHANNEL` variable). Every upload
re-checks which channel the credentials actually control and **aborts on
mismatch**:

```
CHANNEL MISMATCH — refusing to upload.
  expected  : @medinijyotishen
  authorised: @medinijyotish  "Medini Jyotish"
```

That guard exists because your Google account now owns both a Hindi and an
English channel. If the default channel changes, or a token goes stale and gets
re-issued against the other one, the upload targets the wrong channel silently
— and **YouTube cannot move a video between channels after the fact.** Deleting
and re-uploading loses the URL and any early engagement.

When you add the Hindi channel, change `CHANNEL` in `daily.sh` or pass
`--channel @YourHindiHandle`.

---

## 2. Local dependencies — macOS (5 min)

Put the four scripts in one folder, then run these **from that folder**:

```bash
brew install ffmpeg

python3 -m venv .venv
source .venv/bin/activate
pip install pillow edge-tts google-api-python-client google-auth google-auth-oauthlib
```

Three notes, because each of these trips people up:

- `apt-get` is Linux. On macOS it's `brew` — ignore any `apt-get` line you see
  in Linux instructions.
- macOS has **`pip3`**, not `pip`. Inside an activated venv, plain `pip` works,
  which is one reason to use the venv.
- Homebrew's Python refuses global `pip install` with
  *"externally-managed-environment"*. The venv avoids that entirely. If you'd
  rather not use one, add `--break-system-packages` to the pip command.

`daily.sh` auto-detects `.venv/` in its folder, so after this you never need to
remember to activate it.

Verify:

```bash
ffmpeg -version | head -1
.venv/bin/python3 panchang_short.py --lang en --sample --out /tmp/test
open /tmp/test/panchang_2026-08-08_en.mp4
```

You should get a ~25s 1080×1920 video with narration. If the audio is silent,
edge-tts couldn't reach its endpoint — the renderer falls back to silence
rather than failing, so look for the `[tts] fallback` warning.

> Later steps show bare `python3 …`. If you didn't activate the venv in that
> shell, use `.venv/bin/python3 …` instead.

---

## 3. Google Cloud project (10 min)

1. console.cloud.google.com → new project, e.g. `medini-shorts`.
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**
3. **OAuth consent screen:**
   - User type: **External**
   - App name: `Medini Jyotish Publisher`, support email: your medinijyotish2027 address
   - Scopes: `.../auth/youtube.upload` and `.../auth/youtube.readonly`
   - **Publishing status → PUBLISH APP.** Do this now.

> ⚠️ **The one that bites.** While the consent screen sits in *Testing*, Google
> issues refresh tokens that **expire after 7 days**. Everything works, you
> forget about it, and the following week uploads fail with `invalid_grant`.
> Publishing an app that requests only these scopes does not require a
> verification review.

4. **Credentials → Create credentials → OAuth client ID → Desktop app.**
   Download the JSON.

```bash
mkdir -p ~/.medini
mv ~/Downloads/client_secret_*.json ~/.medini/client_secret.json
chmod 600 ~/.medini/client_secret.json
```

---

## 4. Authorise (2 min)

**Before you run this:** go to youtube.com, click your avatar → *Switch
account*, and select **Medini Jyotish English**. OAuth authorises whichever
channel is currently active for that Google account — this is the step that
decides it.

```bash
python3 publish_youtube.py auth --channel @MediniJyotishEn
```

With `--channel`, consent fails loudly if you picked the wrong one, instead of
storing a token that quietly points at the Hindi channel. The handle is then
saved to `~/.medini/yt_channel.json` and re-verified on every upload.

The command prints the channel it authorised and the refresh token for later
use as a GitHub secret — keep that out of the repo.

---

## 5. First video (5 min)

```bash
chmod +x daily.sh
./daily.sh
```

Renders today's English short, opens it, and asks before uploading. Uploads are
**public** by default, so the confirmation prompt is the only gate — use
`./daily.sh --privacy unlisted` if you want to review one first.

Watch the whole thing before confirming:

- [ ] Times are IST — sunrise should read ~05:47, not 00:17. UTC values mean
      the `--tz` conversion didn't apply.
- [ ] Tithi matches medinijyotish.com/panchang/today.
- [ ] Narration is audible and the Sanskrit terms are intelligible.
- [ ] Nothing important sits in the top 14% or bottom 22% — Instagram's overlay
      zone. You'll reuse this exact file for Reels later.

---

## 6. Daily use

```bash
./daily.sh                      # render, preview, confirm, upload public
./daily.sh --privacy unlisted   # hold back for review
./daily.sh -y                   # no prompt (for when you trust it)
./daily.sh --render-only        # just make the file
./daily.sh --date 2026-08-09    # a specific date
./daily.sh --force              # re-upload even if today's date exists
```

Fixing things after the fact:

```bash
python3 publish_youtube.py update --privacy public          # latest video
python3 publish_youtube.py update --at 2026-08-10T00:30:00Z # release 06:00 IST
python3 publish_youtube.py update --metadata-from panchang_2026-08-09_en.mp4
```

Note the asymmetry: **title, description, tags and privacy are editable in
place**, but the video file is not. A bad render means delete and re-upload
under a new URL — which is the argument for `--privacy unlisted` on any day
you've changed the renderer.

Post before people need the information — Rahu Kalam is useless at 9 PM. Target
06:00–07:00 IST.

After seven clean days, move to the GitHub Actions cron in `PIPELINE_SPEC.md`
§5. Carry over three secrets:

```
YT_CLIENT_ID       from client_secret.json
YT_CLIENT_SECRET   from client_secret.json
YT_REFRESH_TOKEN   printed by `publish_youtube.py auth`
```

`publish_youtube.py` already reads those from the environment when present, so
going from local to CI needs no code change.

---

## 7. Adding Hindi later

Everything for Hindi is already built and tested — `./daily.sh --lang hi`
produces fully Devanagari output. It just needs two extra dependencies:

```bash
brew install --cask font-noto-sans-devanagari
brew install libraqm
```

Then verify the shaper, because without it Devanagari matras land on the wrong
characters — wrong enough to look sloppy, subtle enough to ship unnoticed:

```bash
python3 -c "from PIL import features; print('raqm:', features.check('raqm'))"
python3 deva_names.py     # 10 checks on the name table
```

If raqm is `False`, install libraqm then
`pip install --force-reinstall --no-binary :all: pillow`.

The renderer warns at startup if either is missing, so you can't silently
publish broken Hindi.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `invalid_grant` after ~7 days | Consent screen still in *Testing* | Publish the app, re-run `auth` |
| `insufficientPermissions` | Missing `youtube.readonly` scope | Delete `~/.medini/yt_token.json`, re-run `auth` |
| `CHANNEL MISMATCH` | Token points at the other channel | Switch active channel at youtube.com, then `rm ~/.medini/yt_token.json && python3 publish_youtube.py auth --channel @MediniJyotishEn` |
| Silent video | edge-tts unreachable | Falls back to silence by design; check for the `[tts] fallback` warning |
| `quotaExceeded` | Something is looping | `videos.insert` is ~100 units of 10,000/day; check for a retry loop |
| Not tagged as a Short | Ratio or duration | Must be 9:16 and ≤3 min — renderer outputs 1080×1920 / ~25s. Reclassification can take minutes |
| Title rejected | `<` or `>` in the title | Blocked pre-flight by the script |
| Duplicate upload | Re-ran the same day | Guard catches it by date; `--force` overrides |

---

## Two site bugs, unrelated to YouTube

Both surfaced while building this, both are quick fixes, both are visible to
every visitor right now:

1. **The panchang pages print UTC while labelling it local time.** Today's page
   shows Rahu Kalam `03:37 – 05:16` where a Delhi reader needs
   `09:07 – 10:46 IST`, and sunrise as `00:17` instead of `05:47`. The videos
   are correct because the renderer converts explicitly — the site is not.

2. **`/hi/` shows tithi, yoga and karana in Latin transliteration** —
   "Krishna Ekadashi", "Vyaghata", "Bava" on an otherwise Devanagari page.
   `deva_names.py` drops into the SSR templates to fix it. It's a lookup table
   over closed classical vocabulary, so there's no interpretation or sourcing
   risk in reusing it server-side.
