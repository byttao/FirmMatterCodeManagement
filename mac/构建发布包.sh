#!/bin/bash
set -euo pipefail
CODE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(dirname "$CODE")"
OUT="$ROOT/发布包"
VERSION="$(tr -d '\r\n' < "$CODE/VERSION")"
NODE_BIN="$(command -v node || true)"
if [ -z "$NODE_BIN" ] && [ -x "$HOME/.real/.bin/node/bin/node" ]; then
  NODE_BIN="$HOME/.real/.bin/node/bin/node"
fi
[ -n "$NODE_BIN" ] || { echo "构建前端需要 Node.js 18+" >&2; exit 1; }
export PATH="$(dirname "$NODE_BIN"):$PATH"
[ -d "$CODE/frontend/node_modules" ] || (cd "$CODE/frontend" && npm ci)
(cd "$CODE/frontend" && npm run build)
mkdir -p "$OUT"
STAGE="$(mktemp -d "$OUT/.mac-build.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
PACKAGE="$STAGE/FirmMatterCodeManagement-mac-$VERSION"
mkdir -p "$PACKAGE/backend" "$PACKAGE/static"
cp "$CODE"/backend/*.py "$CODE/backend/requirements.txt" "$PACKAGE/backend/"
cp -R "$CODE/frontend/dist/." "$PACKAGE/static/"
cp "$CODE/VERSION" "$CODE/LICENSE" "$CODE/THIRD_PARTY_NOTICES.md" "$PACKAGE/"
cp "$CODE/mac/服务.sh" "$CODE/mac/启动.command" "$CODE/mac/停止.command" "$CODE/mac/README-Mac.txt" "$CODE/mac/server.default.json" "$PACKAGE/"
chmod +x "$PACKAGE/服务.sh" "$PACKAGE/启动.command" "$PACKAGE/停止.command"
find "$PACKAGE" -name .DS_Store -delete
ZIP="$OUT/FirmMatterCodeManagement-mac-$VERSION.zip"
rm -f "$ZIP"
(cd "$STAGE" && COPYFILE_DISABLE=1 ditto -c -k --norsrc --keepParent "$(basename "$PACKAGE")" "$ZIP")
echo "已生成：$ZIP"
