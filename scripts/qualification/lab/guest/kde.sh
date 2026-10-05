#!/bin/bash
# Provision only inside the disposable Ubuntu VM. No host Incus operations.
set -euo pipefail

emit_capture() {
cat <<'CAPTURE'
#!/bin/bash
set -euo pipefail
fail() { printf 'KDE capture refused: %s\n' "$*" >&2; exit 1; }
[[ $# == 1 ]] || fail 'usage: capture OUTPUT.png'
[[ $(id -un) == odq ]] || fail 'run as odq, not root'
[[ ${XDG_SESSION_TYPE:-} == wayland ]] || fail 'requires a real Wayland session'
[[ ${XDG_CURRENT_DESKTOP:-} == *KDE* ]] || fail 'requires the Plasma session'
[[ -n ${WAYLAND_DISPLAY:-} && -n ${DBUS_SESSION_BUS_ADDRESS:-} ]] || fail 'session environment missing; do not synthesize a new D-Bus session'
pgrep -u "$(id -u)" -x kwin_wayland >/dev/null || fail 'KWin Wayland not running for odq'
output=$1
[[ ! -e $output && ! -L $output ]] || fail 'output already exists; use a fresh evidence path'
mkdir -p -- "$(dirname -- "$output")"
tmpdir=$(mktemp -d -- "$(dirname -- "$output")/.odq-kde-capture.XXXXXX")
trap 'rm -rf -- "$tmpdir"' EXIT
# Spectacle is KWin's authorized desktop screenshot client, not a generic
# Wayland capture API. A permission prompt/denial or unsupported compositor
# is a failed smoke proof; never fall back to X11 or framebuffer capture.
if ! QT_QPA_PLATFORM=wayland timeout 30s spectacle --background --nonotify --fullscreen --output "$tmpdir/capture.png"; then
    fail 'Spectacle/KWin capture failed or timed out; inspect the guest console for a permission prompt'
fi
python3 - "$tmpdir/capture.png" <<'PY'
import struct, sys
from pathlib import Path
p = Path(sys.argv[1])
data = p.read_bytes() if p.is_file() else b''
if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
    sys.exit('Spectacle did not produce a PNG; Wayland capture is not proven')
w, h = struct.unpack('>II', data[16:24])
if not (0 < w <= 32768 and 0 < h <= 32768):
    sys.exit('Spectacle produced invalid dimensions')
PY
mv --no-clobber -T -- "$tmpdir/capture.png" "$output"
[[ ! -e $tmpdir/capture.png ]] || fail 'output appeared during capture; original evidence preserved'
CAPTURE
}

# Pure helper export for executable, fake-command tests. No guest mutations.
if [[ ${1:-} == --print-capture && $# == 1 ]]; then
    emit_capture
    exit 0
fi
[[ $# == 0 ]] || { echo 'usage: kde.sh [--print-capture]' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'provisioning requires guest root' >&2; exit 1; }
systemd-detect-virt --vm >/dev/null || { echo 'refusing non-VM provisioning' >&2; exit 1; }
[[ $(hostname) == odq-kde ]] || { echo 'refusing a VM other than odq-kde' >&2; exit 1; }
# shellcheck disable=SC1091
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 && $(dpkg --print-architecture) == amd64 ]] || {
    echo 'requires Ubuntu 24.04 amd64 guest' >&2; exit 1;
}
[[ -f /root/odq/common.sh ]] || { echo 'guest common.sh missing' >&2; exit 1; }
# Suppress Debian maintainer-script service starts until configuration is done.
# Preserve any image-provided policy rather than destroying it on retries.
policy_backup=$(mktemp -d)
policy_existed=false
if [[ -e /usr/sbin/policy-rc.d || -L /usr/sbin/policy-rc.d ]]; then
    cp -a /usr/sbin/policy-rc.d "$policy_backup/original"
    policy_existed=true
fi
restore_policy() {
    rm -f /usr/sbin/policy-rc.d
    if $policy_existed; then cp -a "$policy_backup/original" /usr/sbin/policy-rc.d; fi
    rm -rf "$policy_backup"
}
trap restore_policy EXIT
rm -f /usr/sbin/policy-rc.d
printf '#!/bin/sh\nexit 101\n' >/usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d
# shellcheck disable=SC1091
. /root/odq/common.sh
odq_common

export DEBIAN_FRONTEND=noninteractive
printf 'shared shared/default-x-display-manager select sddm\n' | debconf-set-selections
apt-get update
apt-get install -y kde-plasma-desktop plasma-workspace-wayland kwin-wayland sddm \
    kde-spectacle xdg-desktop-portal-kde libgl1-mesa-dri mesa-utils \
    qtwayland5 fonts-dejavu-core speech-dispatcher espeak-ng at-spi2-core
test -f /usr/share/wayland-sessions/plasmawayland.desktop
install -d /etc/sddm.conf.d /usr/local/lib/odq
# SDDM's greeter may be X11; the selected user session is explicitly Wayland.
cat >/etc/sddm.conf.d/90-odq.conf <<'SDDM'
[Autologin]
User=odq
Session=plasmawayland.desktop
Relogin=false
SDDM
printf '/usr/bin/sddm\n' >/etc/X11/default-display-manager

install -d -o odq -g odq /home/odq/.config/plasma-workspace/env
cat >/home/odq/.config/plasma-workspace/env/odq-software.sh <<'ENV'
#!/bin/sh
# Mesa llvmpipe in the guest. No host physical GPU is required or permitted.
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export QT_ACCESSIBILITY=1
export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
ENV
chmod 0755 /home/odq/.config/plasma-workspace/env/odq-software.sh
chown odq:odq /home/odq/.config/plasma-workspace/env/odq-software.sh
emit_capture >/usr/local/lib/odq/capture
chmod 0755 /usr/local/lib/odq/capture
# Only the parent common recipe owns Orca/autostart/smoke orchestration.
# Enable for the next lab-controlled reboot; do not restart any display here.
systemctl enable sddm.service --force
systemctl set-default graphical.target
odq_finalize
