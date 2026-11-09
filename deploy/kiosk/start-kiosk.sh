#!/usr/bin/env bash
# Starts the mirror in Chrome kiosk mode and restarts it if it ever closes or crashes.
#
#   start-kiosk.sh            keep the kiosk running forever (what autostart uses)
#   start-kiosk.sh --once     run it once and return when Chrome exits
#   KIOSK_DRY_RUN=1 start-kiosk.sh --once     print the command instead of running it
#
# Settings come from ~/.config/elevariq-kiosk.env (see kiosk.env.example), or the file named by KIOSK_ENV.
set -u

CONFIG="${KIOSK_ENV:-$HOME/.config/elevariq-kiosk.env}"
# shellcheck disable=SC1090
[ -f "$CONFIG" ] && . "$CONFIG"

: "${KIOSK_URL:?Set KIOSK_URL (the address of the mirror, https://...) in $CONFIG}"
PROFILE="${KIOSK_PROFILE:-$HOME/.config/elevariq-chrome}"
CHROME="${CHROME_BIN:-$(command -v google-chrome-stable || command -v google-chrome || command -v chromium || command -v chromium-browser || true)}"

if [ -z "$CHROME" ] && [ -z "${KIOSK_DRY_RUN:-}" ]; then
  echo "Chrome or Chromium is not installed (set CHROME_BIN to its path)." >&2
  exit 1
fi

prepare_screen() {
  # Never let the screen blank, sleep or lock: it is a mirror.
  if command -v xset >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    xset s off
    xset s noblank
    xset -dpms
  fi
  # Rotate to portrait if asked (X11 only). Find the output name with `xrandr`.
  if [ -n "${KIOSK_OUTPUT:-}" ] && [ -n "${KIOSK_ROTATE:-}" ] && command -v xrandr >/dev/null 2>&1; then
    xrandr --output "$KIOSK_OUTPUT" --rotate "$KIOSK_ROTATE" || true
  fi
  # Hide the mouse pointer on a touch screen, if `unclutter` is installed.
  if command -v unclutter >/dev/null 2>&1 && ! pgrep -x unclutter >/dev/null 2>&1; then
    unclutter -idle 0.5 -root >/dev/null 2>&1 &
  fi
}

forget_crash() {
  # After a power cut Chrome would greet the next shopper with a "restore pages?" bubble. Say it exited cleanly.
  local prefs="$PROFILE/Default/Preferences"
  [ -f "$prefs" ] && sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"Crashed"/"exit_type":"Normal"/' "$prefs" || true
}

chrome_args() {
  printf '%s\n' \
    --kiosk \
    "--user-data-dir=$PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=Translate,TranslateUI \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --password-store=basic \
    --check-for-update-interval=2592000 \
    --autoplay-policy=no-user-gesture-required \
    "$KIOSK_URL"
}

run_once() {
  prepare_screen
  forget_crash
  mapfile -t args < <(chrome_args)
  if [ -n "${KIOSK_DRY_RUN:-}" ]; then
    echo "${CHROME:-chrome}" "${args[@]}"
    return 0
  fi
  "$CHROME" "${args[@]}"
}

if [ "${1:-}" = "--once" ]; then
  run_once
  exit $?
fi

while true; do
  run_once
  [ -n "${KIOSK_DRY_RUN:-}" ] && exit 0
  echo "Chrome exited; restarting in 3 seconds." >&2
  sleep 3
done
