#!/usr/bin/env bash
# Launch a real headed Google Chrome under Xvfb for the reply spike.
# Run from anywhere; it resolves the project root from this file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="${CHROME_PROFILE:-$ROOT/spike/chrome-profile}"
PORT="${CDP_PORT:-9222}"
WIDTH="${WINDOW_WIDTH:-1537}"
HEIGHT="${WINDOW_HEIGHT:-960}"

UA_MODE="${UA_MODE:-login}"
UA_ARGS=()
case "$UA_MODE" in
  login)
    UA="$(jq -r '.user_agent // empty' "$ROOT/.secrets/import-login.json")"
    if [ -z "$UA" ]; then
      echo "no user_agent in $ROOT/.secrets/import-login.json" >&2
      exit 1
    fi
    UA_ARGS=(--user-agent="$UA")
    ;;
  native)
    # Let Chrome 148 report its real UA, client hints and engine consistently.
    UA_ARGS=()
    ;;
  custom)
    UA="${CHROME_UA:-}"
    if [ -z "$UA" ]; then
      echo "UA_MODE=custom requires CHROME_UA" >&2
      exit 1
    fi
    UA_ARGS=(--user-agent="$UA")
    ;;
  *)
    echo "unknown UA_MODE=$UA_MODE (login|native|custom)" >&2
    exit 1
    ;;
esac

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfb is not installed. Run: sudo apt-get update && sudo apt-get install -y xvfb" >&2
  exit 1
fi

mkdir -p "$PROFILE"
chmod 700 "$PROFILE"

DISPLAY_NUM="${DISPLAY_NUM:-99}"
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" >/dev/null 2>&1; then
  Xvfb ":${DISPLAY_NUM}" -screen 0 "${WIDTH}x${HEIGHT}x24" >/tmp/dtk-xvfb.log 2>&1 &
  sleep 1
fi
export DISPLAY=":${DISPLAY_NUM}"

echo "starting Chrome on DISPLAY=${DISPLAY}, CDP port=${PORT}"
echo "profile=${PROFILE}"
echo "UA_MODE=${UA_MODE}"

exec google-chrome \
  --user-data-dir="$PROFILE" \
  --remote-debugging-port="$PORT" \
  --no-first-run \
  --no-default-browser-check \
  --disable-ipv6 \
  --autoplay-policy=user-gesture-required \
  --mute-audio \
  --enable-unsafe-swiftshader \
  --ignore-gpu-blocklist \
  --use-gl=angle \
  --use-angle=swiftshader \
  --enable-webgl \
  "${UA_ARGS[@]}" \
  --window-size="${WIDTH},${HEIGHT}" \
  about:blank
