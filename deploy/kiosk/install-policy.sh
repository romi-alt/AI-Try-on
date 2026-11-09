#!/usr/bin/env bash
# Installs the Chrome policy that lets the mirror use the camera without a permission prompt, and turns off
# everything a shopper should not meet (sign-in, translate, passwords, downloads, developer tools, extensions).
#
#   sudo KIOSK_URL=https://mirror.example.com/ ./install-policy.sh
#   POLICY_DIR=/tmp/policies KIOSK_URL=https://mirror.example.com/ ./install-policy.sh     (try it without root)
set -euo pipefail

: "${KIOSK_URL:?Set KIOSK_URL, e.g. KIOSK_URL=https://mirror.example.com/}"
case "$KIOSK_URL" in
  https://*) ;;
  *) echo "KIOSK_URL must start with https:// (the camera only works on https)." >&2; exit 1 ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
# The origin is scheme + host (+ port): the camera permission is granted per origin, not per page.
ORIGIN="$(python3 -c 'import sys; from urllib.parse import urlparse; u = urlparse(sys.argv[1]); print(f"{u.scheme}://{u.netloc}")' "$KIOSK_URL")"

if [ -z "${POLICY_DIR:-}" ]; then
  if command -v google-chrome-stable >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1; then
    POLICY_DIR=/etc/opt/chrome/policies/managed
  elif command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1; then
    POLICY_DIR=/etc/chromium/policies/managed
  else
    echo "Neither Google Chrome nor Chromium is installed. Install one first, or set POLICY_DIR." >&2
    exit 1
  fi
fi

mkdir -p "$POLICY_DIR"
OUT="$POLICY_DIR/elevariq-kiosk.json"
sed -e "s|__KIOSK_ORIGIN__|$ORIGIN|g" -e "s|__KIOSK_URL__|$KIOSK_URL|g" "$HERE/chrome-policy.json" > "$OUT"
python3 -m json.tool "$OUT" >/dev/null   # refuse to leave a broken policy behind
chmod 644 "$OUT"
echo "Installed $OUT (camera allowed for $ORIGIN)."
echo "Check it in Chrome at chrome://policy (press Reload policies), then restart the browser."
