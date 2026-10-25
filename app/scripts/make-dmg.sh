#!/bin/sh
# Wrap release/mac-arm64/片刻.app in a drag-to-Applications dmg with macOS's
# own hdiutil (electron-builder's dmg step downloads tools from GitHub).
set -eu
cd "$(dirname "$0")/.."
APP="release/mac-arm64/片刻.app"
VERSION=$(node -p "require('./package.json').version")
OUT="release/片刻-$VERSION-arm64.dmg"
[ -d "$APP" ] || { echo "missing $APP: run electron-builder first" >&2; exit 1; }
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$OUT"
hdiutil create -quiet -volname "片刻" -srcfolder "$STAGE" -fs HFS+ -format UDZO "$OUT"
rm -rf "$STAGE"
echo "dmg: app/$OUT"
