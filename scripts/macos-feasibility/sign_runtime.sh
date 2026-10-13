#!/bin/bash
# Developer ID signing of a staged runtime for the macOS feasibility spike (phase 1), then an optional
# notarization probe. Evidence harness only: the release pipeline signs in CI (phase 5).
#
#   sign_runtime.sh RUNTIME IDENTITY.p12 P12-PASSWORD-FILE [API-KEY.p8 KEY-ID ISSUER-ID]
#   (NOTARY_WAIT, default 15m, bounds the wait for Apple's verdict)
#
# Every Mach-O is signed inside-out with the hardened runtime and a secure timestamp. The interpreter gets the one
# exception (entitlements-python.plist); a copy signed without it, python3.12-strict, is the control for the
# library-validation check. The identity lives in a disposable keychain that is put in the user search list for
# the run (codesign needs that to build the chain to Apple Root CA). On exit the keychain is deleted, which also
# takes it off the list; the list is then compared with the one read at the start, path for path, and a difference
# is reported, never overwritten. The login keychain is never used.
set -euo pipefail

# Physical paths: on macOS /var is a link to /private/var, and the Mach-O list holds resolved paths.
RUNTIME=$(cd "$1" && pwd -P)
P12=$2
P12_PASSWORD_FILE=$3
HERE=$(cd "$(dirname "$0")" && pwd -P)
PYTHON="$RUNTIME/python/bin/python3.12"
STRICT="$RUNTIME/python/bin/python3.12-strict"
WORK=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/odin-sign.XXXXXX")" && pwd -P)
KEYCHAIN="$WORK/signing.keychain-db"

# The user's search list, one path per line, exactly as security prints it (quotes removed, nothing else).
search_list() {
  security list-keychains -d user | sed -e 's/^[[:space:]]*"//' -e 's/"[[:space:]]*$//'
}
BEFORE_TEXT=$(search_list)
BEFORE=()
while IFS= read -r keychain; do
  BEFORE+=("$keychain")
done <<< "$BEFORE_TEXT"

cleanup() {
  security delete-keychain "$KEYCHAIN" 2>/dev/null || true
  local after
  after=$(search_list)
  if [ "$after" = "$BEFORE_TEXT" ]; then
    echo "keychain search list: restored exactly"
  else
    echo "WARNING: the keychain search list differs from the start of the run; it was left as it is." >&2
    printf 'before:\n%s\nnow:\n%s\n' "$BEFORE_TEXT" "$after" >&2
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

KEYCHAIN_PASSWORD=$(/usr/bin/openssl rand -hex 24)
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 1800 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security list-keychains -d user -s "$KEYCHAIN" ${BEFORE[@]+"${BEFORE[@]}"}
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
  xcrun notarytool submit "$WORK/runtime.zip" --key "$4" --key-id "$5" --issuer "$6" --wait --timeout "${NOTARY_WAIT:-15m}" \
    --output-format json > "$WORK/notary.json" 2> "$WORK/notary.err" || true
  # A zero exit here is never acceptance: report what Apple said, or that it has not said yet.
  "$PYTHON" - "$WORK/notary.json" "$WORK/notary.err" <<'REPORT'
import json, re, sys
text, errors = (open(path).read().strip() for path in sys.argv[1:3])
try:
    reply = json.loads(text) if text else {}
except json.JSONDecodeError:
    reply = {}
found = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", text + errors)
submission = reply.get("id") or (found.group(0) if found else None)
status = reply.get("status")
if status == "Accepted":
    verdict = "accepted"
elif status == "Invalid":
    verdict = "rejected (Invalid): fetch the log with notarytool log"
elif submission:
    verdict = f"pending: {status or 'In Progress'} when the wait ended"
else:
    verdict = "submission failed: " + (errors or text)[-300:]
print(f"notarization: {verdict}" + (f" (submission {submission})" if submission else ""))
REPORT
fi
