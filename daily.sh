#!/usr/bin/env bash
#
# Medini Jyotish — render + upload today's panchang short.
#
#   ./daily.sh                    render English, preview, ask, upload PUBLIC
#   ./daily.sh --privacy unlisted  hold it back for review
#   ./daily.sh --yes              no confirmation prompt
#   ./daily.sh --lang hi          different language
#   ./daily.sh --date 2026-08-09  a specific date
#   ./daily.sh --render-only      make the video, don't upload
#
# Uploads PUBLIC by default. The confirmation prompt is the only thing between
# a bad render and your subscribers, so think before pressing y — or use
# --privacy unlisted for a dry run.

set -euo pipefail

LANG_CODE="en"
DATE_ARG=""
PRIVACY="public"
# Upload aborts if the authorised credentials point anywhere else. Change this
# when you add the Hindi channel.
CHANNEL="@MediniJyotishEn"
CONFIRM=1
UPLOAD=1
FORCE=""            # --force: re-upload even if today's date is already there
# Renders land in ./out/ so generated mp4s never mix with the source files.
OUT="${MEDINI_OUT:-out}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)        LANG_CODE="$2"; shift 2 ;;
    --channel)     CHANNEL="$2"; shift 2 ;;
    --date)        DATE_ARG="--date $2"; shift 2 ;;
    --privacy)     PRIVACY="$2"; shift 2 ;;
    --yes|-y)      CONFIRM=0; shift ;;
    --force)       FORCE="--force"; shift ;;
    --render-only) UPLOAD=0; shift ;;
    -h|--help)     sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")"
mkdir -p "$OUT"

# Use the local venv if there is one, so you don't have to remember to activate.
if [[ -x ".venv/bin/python3" ]]; then
  PY=".venv/bin/python3"
else
  PY="python3"
fi

echo "==> Rendering ($LANG_CODE)"
"$PY" panchang_short.py --lang "$LANG_CODE" --out "$OUT" $DATE_ARG

DATE="${DATE_ARG#--date }"
[[ -z "$DATE" ]] && DATE="$(date +%F)"
VIDEO="$OUT/panchang_${DATE}_${LANG_CODE}.mp4"

if [[ ! -f "$VIDEO" ]]; then
  # renderer names the file from the API's date, which can differ from the
  # local date around midnight — fall back to the newest mp4
  VIDEO="$(ls -t "$OUT"/panchang_*_"${LANG_CODE}".mp4 | head -1)"
fi

echo "==> $VIDEO"

if [[ $UPLOAD -eq 0 ]]; then
  echo "Render only. Done."
  exit 0
fi

# Open it so you actually watch it before it goes public. During the first
# week this is the entire point of running manually.
if [[ $CONFIRM -eq 1 ]]; then
  case "$(uname -s)" in
    Darwin) open "$VIDEO" ;;
    Linux)  xdg-open "$VIDEO" >/dev/null 2>&1 || true ;;
  esac
  echo
  echo "Check: times in IST (sunrise ~05:48, not 00:17)? Tithi matches the site?"
  if [[ "$PRIVACY" == "public" ]]; then
    echo "This goes PUBLIC immediately."
  fi
  read -r -p "Upload as $PRIVACY? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

echo "==> Uploading to $CHANNEL"
"$PY" publish_youtube.py upload "$VIDEO" \
  --privacy "$PRIVACY" --lang "$LANG_CODE" --channel "$CHANNEL" $FORCE
