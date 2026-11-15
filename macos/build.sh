#!/usr/bin/env bash
# Build OpenDesk and (by default) install it into /Applications so that
# macOS TCC grants for Accessibility / Screen Recording stick to a
# stable path across rebuilds.
#
# Usage:
#   ./build.sh             # release build → /Applications/OpenDesk.app
#   ./build.sh debug       # debug build  → /Applications/OpenDesk.app
#   ./build.sh open        # release build → /Applications + launch
#   ./build.sh local       # release build into ./build/OpenDesk.app only
#                          # (use when you don't want to touch /Applications)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="release"
OPEN=false
INSTALL_GLOBAL=true
case "${1:-}" in
  debug) CONFIG="debug" ;;
  open)  OPEN=true ;;
  local) INSTALL_GLOBAL=false ;;
  "")    : ;;
  *)     echo "usage: $0 [debug|open|local]"; exit 1 ;;
esac

echo "▸ Building OpenDesk ($CONFIG)…"
cd "$HERE"
swift build -c "$CONFIG"

BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
BIN="$BIN_DIR/OpenDesk"
if [[ ! -x "$BIN" ]]; then
  echo "✗ build produced no executable at $BIN" >&2
  exit 1
fi

LOCAL_APP="$HERE/build/OpenDesk.app"
echo "▸ Assembling $LOCAL_APP"
rm -rf "$LOCAL_APP"
mkdir -p "$LOCAL_APP/Contents/MacOS" "$LOCAL_APP/Contents/Resources"

cp "$BIN" "$LOCAL_APP/Contents/MacOS/OpenDesk"
cp "$HERE/AppBundle/Info.plist" "$LOCAL_APP/Contents/Info.plist"

# Legacy: bundle the Python bridge so the Tools playground keeps working.
# (The native MCP path no longer needs it, but the playground / audit
# trail still call out to opendesk-mcp via OpenDeskBridge.)
cp -R "$HERE/Sources/OpenDesk/Resources/bridge" "$LOCAL_APP/Contents/Resources/bridge"
cp -R "$HERE/Sources/OpenDesk/Resources/bridge" "$LOCAL_APP/Contents/MacOS/bridge"

# SPM-generated resource bundle (Bundle.module).
RES_BUNDLE="$BIN_DIR/OpenDesk_OpenDesk.bundle"
if [[ -d "$RES_BUNDLE" ]]; then
  cp -R "$RES_BUNDLE" "$LOCAL_APP/Contents/Resources/"
fi

# Ad-hoc sign so macOS lets us launch the bundle without quarantine pain.
codesign --force --deep --sign - "$LOCAL_APP" >/dev/null 2>&1 || true
echo "✓ Local bundle ready: $LOCAL_APP"

# ---------------------------------------------------------------------------
# Install into /Applications so TCC grants survive rebuilds.
# ---------------------------------------------------------------------------
if $INSTALL_GLOBAL; then
  TARGET="/Applications/OpenDesk.app"
  echo "▸ Installing to $TARGET"

  # Kill any running instance at the target path before overwriting.
  if pgrep -fl "$TARGET/Contents/MacOS/OpenDesk" >/dev/null 2>&1; then
    echo "  • Stopping running instance…"
    pkill -f "$TARGET/Contents/MacOS/OpenDesk" || true
    sleep 0.5
  fi

  # Use ditto so resource forks / extended attributes survive the copy.
  # ditto replaces the target atomically if the parent dir is writable.
  if [[ -w /Applications ]]; then
    rm -rf "$TARGET"
    ditto "$LOCAL_APP" "$TARGET"
    codesign --force --deep --sign - "$TARGET" >/dev/null 2>&1 || true
    echo "✓ Installed → $TARGET"
    APP_TO_OPEN="$TARGET"
  else
    echo "⚠ /Applications is not writable. Falling back to local bundle."
    APP_TO_OPEN="$LOCAL_APP"
  fi
else
  APP_TO_OPEN="$LOCAL_APP"
fi

if $OPEN; then
  open "$APP_TO_OPEN"
fi

echo ""
echo "Next:"
echo "  • One-time grant: System Settings → Privacy & Security → Accessibility"
echo "    → toggle ON for $APP_TO_OPEN"
echo "  • Same again for Screen Recording."
echo "  • Future rebuilds overwrite the same path, so the grant sticks."
