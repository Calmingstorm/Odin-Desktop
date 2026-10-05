#!/usr/bin/env bash
# Uploaded over stdin to an Incus VM. Never run provisioning on the host.
set -euo pipefail

cinnamon_emit_capture() {
    cat <<'CAPTURE'
#!/bin/bash
set -euo pipefail
[[ $(id -un) == odq && ${XDG_SESSION_TYPE:-} == x11 && -n ${DISPLAY:-} ]] || {
    echo 'Capture requires odq in the Cinnamon X11 guest session' >&2; exit 78;
}
case "${XDG_CURRENT_DESKTOP:-}" in
    *Cinnamon*|*cinnamon*) ;;
    *) echo 'Capture requires Cinnamon' >&2; exit 78 ;;
esac
[[ $# == 1 && $1 == /* && $1 == *.png ]] || {
    echo 'Usage: capture /absolute/new-image.png' >&2; exit 64;
}
target=$1
[[ -d $(dirname "$target") && ! -e $target && ! -L $target ]] || {
    echo 'Capture output must be a new file in an existing guest directory' >&2; exit 64;
}
work=$(mktemp -d "$(dirname "$target")/.cinnamon-capture.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
image=$work/image.png
# scrot reads the guest X root window, not the host SPICE viewer or another display.
timeout 25s scrot "$image"
python3 - "$image" <<'PY'
import sys
from PIL import Image
with Image.open(sys.argv[1]) as image:
    if image.format != 'PNG' or image.width < 1 or image.height < 1:
        raise ValueError('Capture did not produce a nonempty PNG')
    image.load()
PY
# Hard-link creation refuses an output created concurrently, unlike mv overwrite.
ln -- "$image" "$target"
printf 'Cinnamon guest screenshot captured: %s\n' "$target"
CAPTURE
}

cinnamon_guard() {
    [[ $(id -u) == 0 ]] || { echo 'Provisioning requires root inside the guest' >&2; return 1; }
    local virtualization
    virtualization=$(systemd-detect-virt --vm) || {
        echo 'Refusing provisioning outside a VM' >&2; return 1;
    }
    [[ $virtualization == kvm || $virtualization == qemu ]] || {
        echo 'Requires an isolated QEMU/KVM guest' >&2; return 1;
    }
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ $ID == ubuntu && $VERSION_ID == 24.04 && $(dpkg --print-architecture) == amd64 ]] || {
        echo 'Requires the pinned Ubuntu 24.04 amd64 guest' >&2; return 1;
    }
}

# Optional output root is only for offline generated-config tests; main never accepts one.
cinnamon_write_config() {
    local root=${1:-}
    mkdir -p "$root/etc/lightdm/lightdm.conf.d" "$root/etc/X11/Xsession.d" \
        "$root/usr/local/lib/odq" "$root/home/odq" \
        "$root/etc/dconf/profile" "$root/etc/dconf/db/odq.d"
    cat > "$root/etc/lightdm/lightdm.conf.d/99-odq.conf" <<'CONF'
[Seat:*]
greeter-session=lightdm-gtk-greeter
user-session=cinnamon
autologin-session=cinnamon
autologin-user=odq
autologin-user-timeout=0
allow-guest=false
greeter-allow-guest=false
greeter-show-remote-login=false
xserver-allow-tcp=false
xserver-command=X -nolisten tcp
[XDMCPServer]
enabled=false
[VNCServer]
enabled=false
CONF
    cat > "$root/etc/X11/Xsession.d/80odq-software-rendering" <<'CONF'
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
CONF
    printf '/usr/sbin/lightdm\n' > "$root/etc/X11/default-display-manager"
    cat > "$root/etc/dconf/profile/user" <<'CONF'
user-db:user
system-db:odq
CONF
    cat > "$root/etc/dconf/db/odq.d/00-cinnamon" <<'CONF'
[org/cinnamon/desktop/interface]
toolkit-accessibility=true
[org/cinnamon/desktop/screensaver]
lock-enabled=false
[org/cinnamon/desktop/session]
idle-delay=uint32 0
CONF
    cat > "$root/home/odq/.dmrc" <<'CONF'
[Desktop]
Session=cinnamon
CONF
    cinnamon_emit_capture > "$root/usr/local/lib/odq/capture"
    chmod 0755 "$root/usr/local/lib/odq/capture"
}

cinnamon_with_service_policy() (
    policy=$1/usr/sbin/policy-rc.d
    backup=
    shift
    if [[ -e $policy || -L $policy ]]; then
        backup=$(mktemp "${policy%/*}/odq-policy-rc.d.XXXXXXXX")
        mv -- "$policy" "$backup"
    fi
    trap 'rm -f -- "$policy"; if [[ -n $backup ]]; then mv -- "$backup" "$policy"; fi' EXIT
    printf '#!/bin/sh\nexit 101\n' > "$policy"
    chmod 0755 "$policy"
    "$@"
)

cinnamon_install_packages() {
    printf 'lightdm shared/default-x-display-manager select lightdm\n' | debconf-set-selections
    apt-get update
    apt-get install -y --no-install-recommends \
        cinnamon-core lightdm lightdm-gtk-greeter xserver-xorg-video-all \
        libgl1-mesa-dri scrot x11-utils dconf-cli dbus-user-session
}

cinnamon_main() {
    case "${1:-provision}" in
        --print-capture) cinnamon_emit_capture; return 0 ;;
        provision) [[ $# -le 1 ]] || return 64 ;;
        *) echo 'Usage: bash cinnamon.sh [provision|--print-capture]' >&2; return 64 ;;
    esac
    cinnamon_guard
    # shellcheck disable=SC1091
    source /root/odq/common.sh
    odq_common
    export DEBIAN_FRONTEND=noninteractive
    # Do not let package postinst launch an incompletely configured display manager.
    cinnamon_with_service_policy '' cinnamon_install_packages
    test -f /usr/share/xsessions/cinnamon.desktop
    cinnamon_write_config ''
    # Locked hash blocks password login. LightDM autologin PAM uses pam_permit.
    passwd -l odq
    chown odq:odq /home/odq/.dmrc
    dconf update
    ln -sfn /usr/lib/systemd/system/lightdm.service /etc/systemd/system/display-manager.service
    systemctl daemon-reload
    systemctl set-default graphical.target
    install -d -m 0700 -o odq -g odq /home/odq/qualification
    dpkg-query -W > /home/odq/qualification/packages.tsv
    chown odq:odq /home/odq/qualification/packages.tsv
    odq_finalize
    echo 'Cinnamon provisioned. Reboot the VM; use the common guest smoke runner.'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then cinnamon_main "$@"; fi
