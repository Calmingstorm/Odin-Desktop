#!/bin/bash
# Build odin-guardian for Apple silicon. Usage: build.sh OUTPUT
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
output="${1:?usage: build.sh OUTPUT}"
xcrun clang -std=c11 -O2 -Wall -Wextra -Werror -arch arm64 -mmacosx-version-min=13.0 \
  -o "$output" "$here/odin-guardian.c"
