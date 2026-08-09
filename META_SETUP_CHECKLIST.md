# Meta / Instagram Setup Checklist

**Start this first.** App Review takes 2–4 weeks and everything else in the
pipeline is faster than that. The code can wait; the clock cannot.

Total hands-on time: ~90 minutes across steps 1–8, then a wait.

---

## Phase 1 — Accounts (day 1, ~30 min)

### 1. Convert the Instagram account to **Business**

Instagram app → Settings → Account type and tools → Switch to professional
account → **Business** (not Creator).

> **Creator accounts cannot publish via the API.** This is the single most
> common thing people get wrong and it is not obvious from the UI. If you are
> already on Creator, switch to Business.

Category: "Astrologer" or "Religious Organization" — anything reasonable.

### 2. Create a Facebook Page

facebook.com/pages/create — name it **Medini Jyotish**. It does not need
content or followers; it exists because the Graph API permission model is
anchored to Pages.

### 3. Link the Page to the Instagram account

Instagram app → Settings → Business tools and controls → **Connect a Facebook
Page**. Verify from the Facebook side too: Page → Settings → Linked accounts →
Instagram should show connected.

- [ ] IG account type = Business
- [ ] Facebook Page exists
- [ ] Link confirmed from *both* directions

---

## Phase 2 — Meta app (day 1, ~30 min)

### 4. Create the app

developers.facebook.com/apps → Create app → use case **"Other"** → type
**Business**.

App name: `Medini Jyotish Publisher`. Contact email: your
medinijyotish2027 address (keep it separate from personal).

### 5. Add the Instagram product

App dashboard → Add product → **Instagram** → set up → choose the
**Instagram API with Facebook Login** (Business login) flow.

### 6. Request permissions

Under Instagram → Permissions, add:

| Permission | Purpose |
|-----------|---------|
| `instagram_business_basic` | Read account identity |
| `instagram_business_content_publish` | Create + publish Reels |

> These replaced `instagram_basic` and `instagram_content_publish`, which were
> deprecated on **27 January 2025**. Any tutorial referencing the old scope names
> is stale — check the date before following one.

### 7. Get your IG User ID and a token

Use Graph API Explorer (Tools → Graph API Explorer):
- Select your app, generate a user token with both permissions
- `GET /me/accounts` → find your Page → note `id`
- `GET /{page-id}?fields=instagram_business_account` → note the IG User ID

Then exchange for a **long-lived token** (60 days):

```
GET https://graph.facebook.com/v21.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={app-id}
  &client_secret={app-secret}
  &fb_exchange_token={short-lived-token}
```

> Long-lived tokens expire in **60 days** and refresh only if used within that
> window. A daily-posting job refreshes it naturally — but put a calendar
> reminder at day 50 anyway, because if the job breaks for two months the token
> dies silently and the fix looks like a mystery.

- [ ] App created
- [ ] Instagram product added
- [ ] Both permissions requested
- [ ] IG User ID recorded
- [ ] Long-lived token stored as a GitHub secret (`IG_ACCESS_TOKEN`)

---

## Phase 3 — Test before review (day 1–3)

**You do not need App Review to start testing.** In *Development* mode, the app
can act on accounts that hold a role on it. Add your own IG Business account as
an app admin/tester and the publish flow works end to end.

Verify the full loop with a throwaway video:

```bash
# 1. create container
curl -X POST "https://graph.facebook.com/v21.0/{IG_USER_ID}/media" \
  -d "media_type=REELS" \
  -d "video_url=https://medinijyotish.com/shorts/test.mp4" \
  -d "caption=test" \
  -d "access_token={TOKEN}"
# → {"id":"1789..."}

# 2. poll until FINISHED  (30-90s typical)
curl "https://graph.facebook.com/v21.0/{CREATION_ID}?fields=status_code&access_token={TOKEN}"

# 3. publish
curl -X POST "https://graph.facebook.com/v21.0/{IG_USER_ID}/media_publish" \
  -d "creation_id={CREATION_ID}" -d "access_token={TOKEN}"
```

Gotchas that will bite here:

- `video_url` must be **publicly reachable HTTPS**, no auth, no redirect chain.
  Meta fetches it server-side — test with `curl -I` from outside your network.
- Publishing before `status_code` is `FINISHED` fails **silently**. Always poll.
- Containers expire after 24h.
- Reels specs: MP4/MOV, H.264 + AAC, 9:16, 3s–15min. The renderer already
  outputs H.264/yuv420p + AAC 128k at 1080×1920.

- [ ] Test reel published from Development mode
- [ ] nginx serves `/shorts/` publicly over HTTPS

---

## Phase 4 — App Review (submit day 3, wait 2–4 weeks)

### 8. Prepare the submission

App dashboard → App Review → Permissions and features → request Advanced Access
for `instagram_business_content_publish`.

**The screencast is where submissions fail.** It must show the *complete* user
journey, not just the end result:

1. Landing on your app/site
2. Clicking the login/connect button
3. The Facebook login dialog
4. **The permission consent screen, with the requested permissions visible**
5. The app actually publishing a reel
6. The published reel visible on the Instagram profile

Record it in one unbroken take. Reviewers reject cuts that skip the consent
screen.

**Written justification** — say plainly what you are: a personal, single-account
automation that publishes daily Vedic panchang videos to your own Instagram
Business account from data computed by your own service. Do not overstate scope.
Reviewers reject vague "social media management platform" claims from apps with
one user.

Also required:
- Privacy policy URL — you already have `/privacy`. Confirm it mentions data
  handling for the Meta integration.
- Business verification may be requested (business documents / ID). Have them ready.

- [ ] Screencast recorded showing consent screen
- [ ] Use case written, scoped honestly to one account
- [ ] Privacy policy URL confirmed live
- [ ] Submitted — note the date: ____________

---

## Phase 5 — Facebook Page reels (optional, later)

The same app and Page can post reels to Facebook via
`POST /{page-id}/video_reels`, needing `pages_manage_posts` +
`pages_read_engagement`. Marginal extra work once Instagram is approved, and
Facebook still has real reach in this audience demographic. Add it after
Instagram is stable — not before.

---

## Common rejection reasons

| Reason | Fix |
|--------|-----|
| Screencast skips the consent screen | Re-record the whole flow unbroken |
| Use case doesn't match the app's actual scope | Describe it as the single-account tool it is |
| Privacy policy missing or 404 | Verify the URL loads from outside your network |
| Creator account instead of Business | Switch account type, resubmit |
| Requesting permissions not shown in use | Request only the two you actually call |

---

## Parallel track — YouTube

YouTube has no equivalent review wait, so it is not on the critical path. But
one thing there *does* expire:

> OAuth apps left in **Testing** publishing status issue refresh tokens that
> expire after **7 days**. Push the Cloud Console consent screen to
> **Published** before you rely on the cron, or the job dies quietly a week in.

- [ ] YouTube channel created (Hindi first)
- [ ] Cloud project + Data API v3 enabled
- [ ] OAuth consent screen set to **Published**
- [ ] Refresh token stored as `YT_REFRESH_TOKEN`
