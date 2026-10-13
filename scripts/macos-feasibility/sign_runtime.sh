#!/bin/bash
# Developer ID signing of a staged runtime for the macOS feasibility spike (phase 1), then an optional
# notarization probe. Evidence harness only: the release pipeline signs in CI (phase 5).
#
#   sign_runtime.sh RUNTIME IDENTITY.p12 P12-PASSWORD-FILE [API-KEY.p8 KEY-ID ISSUER-ID]
#
# Every Mach-O is signed inside-out with the hardened runtime and a secure timestamp. The interpreter gets the one
# exception (entitlements-python.plist); a copy signed without it, python3.12-strict, is the control for the
# library-validation check. The identity lives in a disposable keychain that is put in the user search list for
# the run (codesign needs that to build the chain to Apple Root CA) and removed on exit, restoring the list. The
# login keychain is never used.
set -euo pipefail

RUNTIME=$(cd "$1" && pwd)
P12=$2
P12_PASSWORD_FILE=$3
HERE=$(cd "$(dirname "$0")" && pwd)
PYTHON="$RUNTIME/python/bin/python3.12"
STRICT="$RUNTIME/python/bin/python3.12-strict"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/odin-sign.XXXXXX")
KEYCHAIN="$WORK/signing.keychain-db"
BEFORE=$(security list-keychains -d user | tr -d ' "' | tr '\n' ' ')

cleanup() {
  security delete-keychain "$KEYCHAIN" 2>/dev/null || true
  if [ "$(security list-keychains -d user | tr -d ' "' | tr '\n' ' ')" != "$BEFORE" ]; then
    # shellcheck disable=SC2086
    security list-keychains -d user -s $BEFORE
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

KEYCHAIN_PASSWORD=$(/usr/bin/openssl rand -hex 24)
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 1800 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
# shellcheck disable=SC2086
security list-keychains -d user -s "$KEYCHAIN" $BEFORE
security import "$P12" -k "$KEYCHAIN" -P "$(cat "$P12_PASSWORD_FILE")" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN" \
  | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p' | head -1)
if [ -z "$IDENTITY" ]; then
  echo "no valid Developer ID Application identity in $P12" >&2
  exit 1
fi
echo "signing as: $IDENTITY"

# List the Mach-O files (by content, deepest first) before anything is signed or copied.
"$PYTHON" "$HERE/stage_runtime.py" --list-macho "$RUNTIME" > "$WORK/macho.txt"
cp -p "$PYTHON" "$STRICT"
signed=0
while IFS= read -r file; do
  [ "$file" = "$PYTHON" ] && continue
  codesign --force --options runtime --timestamp --sign "$IDENTITY" "$file"
  signed=$((signed + 1))
done < "$WORK/macho.txt"
codesign --force --options runtime --timestamp --sign "$IDENTITY" "$STRICT"
codesign --force --options runtime --timestamp --entitlements "$HERE/entitlements-python.plist" \
  --sign "$IDENTITY" "$PYTHON"
echo "signed: $((signed + 2)) files ($(wc -l < "$WORK/macho.txt" | tr -d ' ') in the runtime, plus the control copy)"

failed=0
while IFS= read -r file; do
  if ! codesign --verify --strict "$file" 2>/dev/null; then
    echo "verification failed: $file" >&2
    failed=$((failed + 1))
  fi
done < <(cat "$WORK/macho.txt"; echo "$STRICT")
echo "verification failures: $failed"
codesign -d --entitlements - --xml "$PYTHON" 2>/dev/null | grep -o 'com\.apple\.security\.[a-z.-]*' \
  | sed 's/^/interpreter entitlement: /'
codesign -dvv "$PYTHON" 2>&1 | grep -E '^(Authority|TeamIdentifier|Timestamp)=' | sed 's/^/interpreter /'
[ "$failed" -eq 0 ]

if [ $# -ge 6 ]; then
  ditto -c -k --keepParent "$RUNTIME/python" "$WORK/runtime.zip"
  echo "notarization probe: $(du -h "$WORK/runtime.zip" | cut -f1) submitted"
  xcrun notarytool submit "$WORK/runtime.zip" --key "$4" --key-id "$5" --issuer "$6" --wait --timeout 15m \
    2>&1 | grep -E '^ *(id|status|message):|Timeout|Error' || true
fi
