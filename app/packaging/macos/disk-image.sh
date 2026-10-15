#!/bin/bash
# Attach a disk image read-only at a mount point, or detach it. macOS 27 deprecates hdiutil's attach
# and detach in favour of diskutil's (`diskutil image attach`, `diskutil eject`). A Mac without the
# image verb (an older macOS, or a hosted runner image) attaches with hdiutil instead.
set -euo pipefail
case "${1:-}" in
  attach)
    [ "$#" -eq 3 ] || { echo "usage: disk-image.sh attach IMAGE MOUNT" >&2; exit 2; }
    if diskutil image attach --help >/dev/null 2>&1; then
      diskutil image attach --readOnly --nobrowse --mountPoint "$3" "$2"
    else
      hdiutil attach -nobrowse -readonly -mountpoint "$3" "$2"
    fi
    ;;
  detach)
    [ "$#" -eq 2 ] || { echo "usage: disk-image.sh detach MOUNT" >&2; exit 2; }
    diskutil eject "$2"
    ;;
  *)
    echo "usage: disk-image.sh attach IMAGE MOUNT | detach MOUNT" >&2
    exit 2
    ;;
esac
