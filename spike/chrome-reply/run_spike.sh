#!/usr/bin/env bash
# One-shot spike runner: starts Xvfb+Chrome, waits for CDP, runs the fetch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE="${CHROME_PROFILE:-$ROOT/spike/chrome-profile}"
PORT="${CDP_PORT:-9222}"
LOG="/tmp/dtk-chrome-spike.log"

"$ROOT/spike/chrome-reply/launch_chrome.sh" >"$LOG" 2>&1 &
CHROME_PID=$!

cleanup() {
  kill "$CHROME_PID" 2>/dev/null || true
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "Chrome CDP did not start on port ${PORT}. Log:" >&2
  tail -60 "$LOG" >&2 || true
  exit 1
fi

"$ROOT/spike/.venv/bin/python" "$ROOT/spike/chrome-reply/fetch_replies.py" "$@"
