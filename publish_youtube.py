#!/usr/bin/env python3
"""
Medini Jyotish — YouTube Shorts uploader.

Two modes:

  auth      One-time OAuth consent. Opens a browser, stores the refresh token.
              python3 publish_youtube.py auth

  upload    Upload a rendered short + its metadata sidecar.
              python3 publish_youtube.py upload out/panchang_2026-08-08_hi.mp4

Quota: videos.insert costs ~100 units (reduced from ~1600 in Dec 2025) against a
10,000/day default. The pre-flight duplicate check costs 2. One upload/day uses
about 1% of quota — the constraint is not real at this volume.

Install:
    pip install google-api-python-client google-auth google-auth-oauthlib
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# Three distinct capabilities, three scopes:
#   youtube.upload  — videos.insert. Does NOT permit modifying a video.
#   youtube         — videos.update (privacy flips, metadata edits) and reads.
#   youtube.readonly— kept so the duplicate-check still works if `youtube` is
#                     ever narrowed.
# Changing this list invalidates the stored token: delete .medini/yt_token.json
# and re-run `auth`, and add the scope in the Cloud consent screen too.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    # force-ssl is required to insert/list caption tracks (captions.insert).
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

def _config_dir() -> Path:
    """Where credentials live.

    Default is `.medini/` beside this script, so the whole setup is one
    portable folder. `.gitignore` excludes it both by directory and by
    filename — keeping secrets inside a repo only works if the ignore rules
    are airtight.

    Falls back to the legacy ~/.medini if the local one hasn't been created
    yet, so an existing install keeps working until the files are moved.
    """
    if os.environ.get("MEDINI_CONFIG"):
        return Path(os.environ["MEDINI_CONFIG"]).expanduser()
    local = Path(__file__).resolve().parent / ".medini"
    legacy = Path.home() / ".medini"
    if not (local / "client_secret.json").exists() and \
            (legacy / "client_secret.json").exists():
        print(f"  note: using legacy config at {legacy}\n"
              f"        move it with:  mv {legacy} {local}", file=sys.stderr)
        return legacy
    return local


CONFIG_DIR = _config_dir()
TOKEN_PATH = CONFIG_DIR / "yt_token.json"
SECRETS_PATH = CONFIG_DIR / "client_secret.json"
CHANNEL_PATH = CONFIG_DIR / "yt_channel.json"

# YouTube hard limits — exceeding any of these is a 400, not a truncation.
MAX_TITLE = 100
MAX_DESC = 5000
MAX_TAGS_CHARS = 500

RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 8


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def load_credentials(interactive: bool) -> Credentials:
    """Load stored credentials, refreshing or re-consenting as needed."""
    creds: Credentials | None = None

    # CI path: refresh token supplied via env, no browser available.
    if os.environ.get("YT_REFRESH_TOKEN"):
        creds = Credentials(
            token=None,
            refresh_token=os.environ["YT_REFRESH_TOKEN"],
            client_id=os.environ["YT_CLIENT_ID"],
            client_secret=os.environ["YT_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception as e:                                    # noqa: BLE001
            print(f"  refresh failed ({e}); re-consenting", file=sys.stderr)

    if not interactive:
        sys.exit("No valid credentials. Run:  python3 publish_youtube.py auth")

    if not SECRETS_PATH.exists():
        sys.exit(
            f"Missing {SECRETS_PATH}\n"
            "Download the OAuth client JSON from Google Cloud Console\n"
            "(APIs & Services -> Credentials -> OAuth client ID -> Desktop app)\n"
            f"and save it there."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_PATH), SCOPES)
    # access_type=offline + prompt=consent is what actually returns a refresh
    # token. Without prompt=consent Google omits it on repeat authorisations,
    # which is the classic "worked once, never again" failure.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent",
        authorization_prompt_message="Opening browser for YouTube consent…",
        success_message="Done. You can close this tab.")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
    return creds


def get_channel(yt) -> dict:
    """Identity of the channel these credentials actually control."""
    me = yt.channels().list(part="snippet,contentDetails", mine=True).execute()
    if not me.get("items"):
        sys.exit("Authorised, but this Google account has no YouTube channel.")
    ch = me["items"][0]
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "handle": (ch["snippet"].get("customUrl") or "").lower(),
        "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def norm_handle(s: str) -> str:
    return "@" + s.strip().lstrip("@").lower()


def assert_channel(actual: dict, expected: str | None):
    """Refuse to upload to a channel other than the intended one.

    With a Hindi and an English channel on the same Google account, a stale or
    mis-scoped token silently targets the wrong one — and YouTube cannot move a
    video between channels afterwards. Cheap check, unrecoverable failure.
    """
    if not expected:
        return
    want = norm_handle(expected)
    if want in (actual["handle"], norm_handle(actual["title"].replace(" ", ""))) \
            or expected == actual["id"]:
        return
    sys.exit(
        f"\n  CHANNEL MISMATCH — refusing to upload.\n"
        f"    expected : {want}\n"
        f"    authorised: {actual['handle'] or '(no handle)'}  "
        f"\"{actual['title']}\"\n\n"
        f"  Fix: rm {TOKEN_PATH} && python3 publish_youtube.py auth\n"
        f"  and pick the Google account / default channel for {want}.\n")


def cmd_auth(args):
    creds = load_credentials(interactive=True)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ch = get_channel(yt)

    if getattr(args, "channel", None):
        assert_channel(ch, args.channel)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CHANNEL_PATH.write_text(json.dumps(ch, indent=2))

    print(f"\n  Channel : {ch['title']}")
    print(f"  Handle  : {ch['handle'] or '(none set)'}")
    print(f"  ID      : {ch['id']}")
    print(f"  Token   : {TOKEN_PATH}")
    print("\n  >>> Confirm the channel above is the one you meant. <<<")
    print("\n  For GitHub Actions later, store these as repo secrets:")
    print(f"    YT_REFRESH_TOKEN = {creds.refresh_token}")
    print( "    YT_CLIENT_ID     = (from client_secret.json)")
    print( "    YT_CLIENT_SECRET = (from client_secret.json)")
    print("\n  Note: if the Cloud consent screen is still in 'Testing', this")
    print("  refresh token expires in 7 days. Publish the app before relying")
    print("  on a scheduled run.")


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------

def sidecar(video: Path) -> dict:
    """Read the metadata JSON the renderer wrote next to the mp4."""
    meta_path = video.with_suffix(".json")
    if not meta_path.exists():
        sys.exit(f"Missing metadata sidecar: {meta_path}")
    return json.loads(meta_path.read_text())


def validate(meta: dict) -> dict:
    title = meta["title"].strip()
    desc = meta["description"]
    tags = list(meta.get("tags") or [])

    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE - 1].rstrip() + "…"
    if len(desc) > MAX_DESC:
        desc = desc[:MAX_DESC]
    # Tags share a 500-char budget; drop from the tail rather than get a 400.
    while sum(len(t) + 1 for t in tags) > MAX_TAGS_CHARS and tags:
        tags.pop()

    if "<" in title or ">" in title:
        sys.exit("Title contains < or >, which YouTube rejects.")
    return {"title": title, "description": desc, "tags": tags}


def already_uploaded(yt, uploads: str, marker: str) -> str | None:
    """Cheap duplicate guard: scan the channel's recent uploads for the date.

    Costs 1 quota unit vs 100 for a wasted re-upload, and more importantly
    stops a re-run from putting two identical panchangs on the channel — the
    basis for the weekly workflow's twice-a-run, gap-filling safety net.

    The marker is the ISO date (YYYY-MM-DD). Titles are SEO-tuned and carry a
    *human* date ("6 September 2026"), so match against title AND description:
    every description embeds the canonical URL (…/panchang/YYYY-MM-DD), which
    carries the ISO date verbatim. Matching title-only silently never fires.
    """
    try:
        items = yt.playlistItems().list(
            part="snippet", playlistId=uploads, maxResults=50).execute()
        for it in items.get("items", []):
            sn = it["snippet"]
            hay = f"{sn.get('title', '')}\n{sn.get('description', '')}"
            if marker in hay:
                return sn["resourceId"]["videoId"]
    except HttpError as e:
        print(f"  duplicate check skipped ({e.status_code})", file=sys.stderr)
    return None


def resumable_upload(request) -> str:
    """Drive a resumable upload with exponential backoff on transient errors."""
    response, attempt = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"\r  uploading… {int(status.progress() * 100):3d}%",
                      end="", flush=True)
        except HttpError as e:
            if e.resp.status not in RETRIABLE_STATUS:
                raise
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            sleep = min(2 ** attempt, 60) + random.random()
            print(f"\n  {e.resp.status}, retry {attempt} in {sleep:.1f}s",
                  file=sys.stderr)
            time.sleep(sleep)
        except (ConnectionError, OSError) as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            sleep = min(2 ** attempt, 60) + random.random()
            print(f"\n  {type(e).__name__}, retry {attempt} in {sleep:.1f}s",
                  file=sys.stderr)
            time.sleep(sleep)
    print()
    return response["id"]


def cmd_upload(args):
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"Not found: {video}")

    meta = sidecar(video)
    clean = validate(meta)
    lang = args.lang or (video.stem.rsplit("_", 1)[-1] if "_" in video.stem else "hi")
    marker = args.marker or next(
        (p for p in video.stem.split("_") if p.count("-") == 2), video.stem)

    body = {
        "snippet": {
            "title": clean["title"],
            "description": clean["description"],
            "tags": clean["tags"],
            "categoryId": str(meta.get("categoryId", "22")),
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": {
            "privacyStatus": args.privacy,
            # Required. Omitting it can get the upload flagged rather than
            # rejected, which is harder to notice.
            "selfDeclaredMadeForKids": False,
            "license": "youtube",
            "embeddable": True,
        },
    }

    # Scheduled release: YouTube requires the video be private and flips it
    # public itself at publishAt. This nails an exact release time regardless of
    # when the upload actually ran.
    if args.at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = args.at

    print(f"  {video.name}  ({video.stat().st_size / 1e6:.1f} MB)")
    print(f"  title: {clean['title']}")
    if args.at:
        print(f"  privacy: private → public at {args.at}  lang: {lang}")
    else:
        print(f"  privacy: {args.privacy}  lang: {lang}")

    # Deliberately before auth: checking metadata shouldn't need credentials.
    if args.dry_run:
        print("\n  DRY RUN — request body:")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"\n  title {len(clean['title'])}/{MAX_TITLE} chars · "
              f"description {len(clean['description'])}/{MAX_DESC} · "
              f"tags {sum(len(t) + 1 for t in clean['tags'])}/{MAX_TAGS_CHARS}")
        return

    creds = load_credentials(interactive=False)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    ch = get_channel(yt)
    expected = args.channel or os.environ.get("YT_CHANNEL")
    if not expected and CHANNEL_PATH.exists():
        expected = json.loads(CHANNEL_PATH.read_text()).get("handle") or None
    assert_channel(ch, expected)
    print(f"  channel: {ch['title']}  {ch['handle']}")

    if not args.force:
        dup = already_uploaded(yt, ch["uploads"], marker)
        if dup:
            print(f"  already uploaded: https://youtu.be/{dup}  "
                  f"(use --force to override)")
            return

    media = MediaFileUpload(str(video), chunksize=1024 * 1024 * 4,
                            resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    video_id = resumable_upload(request)

    print(f"\n  https://youtu.be/{video_id}")
    print("  Shorts classification is automatic from the 9:16 ratio and "
          "sub-3-minute length; it may take a few minutes to show as a Short.")

    log = CONFIG_DIR / "uploads.jsonl"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "id": video_id,
                            "file": video.name, "title": clean["title"]}) + "\n")


def cmd_exists(args):
    """Is a short for MARKER (a date) already on the channel? Prints the video
    id and exits 0 if so; exits 3 if not. Lets the weekly workflow skip
    re-rendering days it already published, so the second, gap-filling run only
    does the work that actually failed. Exit 3 (not 1/2) keeps "absent" distinct
    from a usage or runtime error, so a real failure isn't read as "absent".
    """
    creds = load_credentials(interactive=False)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ch = get_channel(yt)
    expected = args.channel or os.environ.get("YT_CHANNEL")
    if not expected and CHANNEL_PATH.exists():
        expected = json.loads(CHANNEL_PATH.read_text()).get("handle") or None
    assert_channel(ch, expected)
    vid = already_uploaded(yt, ch["uploads"], args.marker)
    if vid:
        print(vid)
        return
    sys.exit(3)


# --------------------------------------------------------------------------

def latest_video(yt, uploads: str) -> tuple[str, str] | None:
    items = yt.playlistItems().list(
        part="snippet", playlistId=uploads, maxResults=1).execute().get("items")
    if not items:
        return None
    sn = items[0]["snippet"]
    return sn["resourceId"]["videoId"], sn["title"]


def cmd_update(args):
    """Change privacy and/or refresh metadata on an already-uploaded video.

    YouTube has no API to swap the video file of an existing upload — a bad
    render means delete and re-upload under a new URL. But everything around
    the file is mutable, so the review workflow is: upload unlisted, watch it,
    then flip it public from here rather than clicking through Studio.
    """
    creds = load_credentials(interactive=False)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    ch = get_channel(yt)
    expected = args.channel or os.environ.get("YT_CHANNEL")
    if not expected and CHANNEL_PATH.exists():
        expected = json.loads(CHANNEL_PATH.read_text()).get("handle") or None
    assert_channel(ch, expected)

    video_id = args.video_id
    if not video_id or video_id == "latest":
        found = latest_video(yt, ch["uploads"])
        if not found:
            sys.exit("No videos on the channel.")
        video_id, title = found
        print(f"  latest: {title}")

    cur = yt.videos().list(part="snippet,status", id=video_id).execute()
    if not cur.get("items"):
        sys.exit(f"No such video on this channel: {video_id}")
    item = cur["items"][0]
    snippet, status = item["snippet"], item["status"]

    # videos.update REPLACES each part it is given. Sending a partial snippet
    # silently wipes tags, category and description — so start from the
    # current values and overlay only what changes.
    if args.metadata_from:
        meta = validate(sidecar(Path(args.metadata_from)))
        snippet.update({"title": meta["title"],
                        "description": meta["description"],
                        "tags": meta["tags"]})
        print("  refreshing title/description/tags from sidecar")

    if args.at:
        # Scheduled release: YouTube requires the video be private, and flips
        # it public itself at publishAt.
        status["privacyStatus"] = "private"
        status["publishAt"] = args.at
        print(f"  scheduling public release at {args.at}")
    elif args.privacy:
        status["privacyStatus"] = args.privacy
        status.pop("publishAt", None)
        print(f"  privacy -> {args.privacy}")

    body = {"id": video_id, "snippet": snippet, "status": status}
    yt.videos().update(part="snippet,status", body=body).execute()
    print(f"  updated https://youtu.be/{video_id}")


def cmd_captions(args):
    """Upload a subtitle file (.srt/.vtt) as a caption track. Needs the
    youtube.force-ssl scope — re-run `auth` if you added it after first consent."""
    creds = load_credentials(interactive=False)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(args.file)
    yt.captions().insert(
        part="snippet",
        body={"snippet": {"videoId": args.video_id, "language": args.language,
                          "name": args.name, "isDraft": False}},
        media_body=media).execute()
    print(f"  captions ({args.language}) uploaded to https://youtu.be/{args.video_id}")


def main():
    ap = argparse.ArgumentParser(description="Upload a Medini Jyotish short.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    au = sub.add_parser("auth", help="one-time OAuth consent")
    au.add_argument("--channel", help="assert the handle, e.g. @MediniJyotishEn")
    au.set_defaults(fn=cmd_auth)

    up = sub.add_parser("upload", help="upload a rendered mp4")
    up.add_argument("video")
    up.add_argument("--channel",
                    help="required handle, e.g. @MediniJyotishEn "
                         "(default: whatever `auth` recorded)")
    up.add_argument("--privacy", default="public",
                    choices=["public", "unlisted", "private"])
    up.add_argument("--at", metavar="RFC3339",
                    help="schedule public release at this instant (implies "
                         "private until then), e.g. 2026-08-14T00:30:00Z "
                         "(=06:00 IST). Overrides --privacy.")
    up.add_argument("--lang", help="BCP-47 code (default: inferred from filename)")
    up.add_argument("--marker", help="duplicate-check string (default: the date)")
    up.add_argument("--force", action="store_true", help="skip duplicate check")
    up.add_argument("--dry-run", action="store_true",
                    help="print the request body, upload nothing")
    up.set_defaults(fn=cmd_upload)

    ex = sub.add_parser("exists",
                        help="check if a date is already on the channel "
                             "(prints id + exit 0 if present, exit 3 if absent)")
    ex.add_argument("marker", help="date string to look for, e.g. 2026-09-06")
    ex.add_argument("--channel", help="required handle, e.g. @MediniJyotishEn")
    ex.set_defaults(fn=cmd_exists)

    ud = sub.add_parser("update", help="change privacy/metadata on an existing video")
    ud.add_argument("video_id", nargs="?", default="latest",
                    help="video id, or 'latest' (default)")
    ud.add_argument("--privacy", choices=["public", "unlisted", "private"])
    ud.add_argument("--at", metavar="RFC3339",
                    help="schedule public release, e.g. 2026-08-10T00:30:00Z "
                         "(=06:00 IST). Implies privacy=private until then.")
    ud.add_argument("--metadata-from", metavar="MP4",
                    help="re-apply title/description/tags from an mp4's "
                         ".json sidecar")
    ud.add_argument("--channel", help="required handle, e.g. @MediniJyotishEn")
    ud.set_defaults(fn=cmd_update)

    cp = sub.add_parser("captions", help="upload a subtitle file (.srt/.vtt) to a video")
    cp.add_argument("video_id")
    cp.add_argument("file")
    cp.add_argument("--language", default="en")
    cp.add_argument("--name", default="English")
    cp.set_defaults(fn=cmd_captions)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
