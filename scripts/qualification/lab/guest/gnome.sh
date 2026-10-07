#!/bin/bash
# Uploaded to /root/odq/gnome.sh and executed by Incus inside the disposable VM.
# Functions are sourceable for isolated recipe tests; sourcing never provisions.
set -euo pipefail

gnome_guard() {
    [[ ${EUID} == 0 ]] || { echo 'GNOME provisioning requires guest root' >&2; return 1; }
    local virtualization
    virtualization=$(systemd-detect-virt --vm) || {
        echo 'GNOME recipe refuses non-VM execution' >&2; return 1;
    }
    [[ $virtualization == kvm || $virtualization == qemu ]] || {
        echo 'GNOME recipe requires an isolated QEMU/KVM VM' >&2; return 1;
    }
    [[ $(hostname) == odq-gnome ]] || {
        echo 'GNOME recipe requires the named odq-gnome qualification guest' >&2; return 1;
    }
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ $ID == ubuntu && $VERSION_ID == 24.04 && $(dpkg --print-architecture) == amd64 ]] || {
        echo 'GNOME recipe requires Ubuntu 24.04 amd64' >&2; return 1;
    }
}

# Optional output root is solely for offline fixture generation. It is never
# accepted by main, which always configures the guarded guest's real root.
gnome_write_config() {
    local root=${1:-} path
    for path in etc/gdm3 var/lib/AccountsService/users etc/dconf/profile \
        etc/dconf/db/odq.d/locks etc/systemd/system/gdm.service.d etc/environment.d \
        usr/local/lib/odq usr/share/wayland-sessions home/odq; do
        mkdir -p "$root/$path"
    done
    cat > "$root/etc/gdm3/custom.conf" <<'CONF'
[daemon]
WaylandEnable=true
DefaultSession=odq-gnome.desktop
AutomaticLoginEnable=true
AutomaticLogin=odq
InitialSetupEnable=false

[security]
DisallowTCP=true

[xdmcp]
Enable=false
CONF
    # A unique session name without an xsessions counterpart avoids saved
    # Ubuntu/Xorg sessions winning session resolution during automatic login.
    # GDM hardware/runtime policy can still reject Wayland: smoke must inspect
    # loginctl Type, not assume these preferences succeeded. Do not mask udev
    # rules or edit /run/gdm/custom.conf to conceal such a failure.
    cat > "$root/usr/share/wayland-sessions/odq-gnome.desktop" <<'CONF'
[Desktop Entry]
Name=Odin Qualification GNOME Wayland
Comment=Unextended GNOME on the virtual software-rendered display
Exec=/usr/local/lib/odq/gnome-session
TryExec=/usr/bin/gnome-session
Type=Application
DesktopNames=GNOME
X-GDM-SessionRegisters=true
CONF
    cat > "$root/usr/local/lib/odq/gnome-session" <<'CONF'
#!/bin/sh
# Mutter explicitly selects the virtual DRM device for native Wayland EGL.
# LIBGL_ALWAYS_SOFTWARE conflicts with that device API; select llvmpipe via
# Gallium without forcing EGL software rendering on the selected device.
unset LIBGL_ALWAYS_SOFTWARE
export GALLIUM_DRIVER=llvmpipe
export GNOME_SHELL_SESSION_MODE=gnome
exec /usr/bin/gnome-session --session=gnome
CONF
    chmod 0755 "$root/usr/local/lib/odq/gnome-session"
    cat > "$root/var/lib/AccountsService/users/odq" <<'CONF'
[User]
Session=odq-gnome
XSession=odq-gnome
SessionType=wayland
SystemAccount=false
CONF
    cat > "$root/home/odq/.dmrc" <<'CONF'
[Desktop]
Session=odq-gnome
CONF
    cat > "$root/etc/systemd/system/gdm.service.d/odq-software.conf" <<'CONF'
[Service]
UnsetEnvironment=LIBGL_ALWAYS_SOFTWARE
Environment=GALLIUM_DRIVER=llvmpipe
CONF
    # GNOME Shell may be activated by the systemd user manager rather than as
    # a direct child of the session wrapper. Cover that activation path too.
    cat > "$root/etc/environment.d/60-odq-software.conf" <<'CONF'
GALLIUM_DRIVER=llvmpipe
CONF
    cat > "$root/etc/dconf/profile/user" <<'CONF'
user-db:user
system-db:odq
CONF
    cat > "$root/etc/dconf/db/odq.d/00-gnome" <<'CONF'
[org/gnome/shell]
enabled-extensions=@as []
disable-user-extensions=true
welcome-dialog-last-shown-version='46'

[org/gnome/desktop/a11y/applications]
screen-reader-enabled=true

[org/gnome/desktop/interface]
toolkit-accessibility=true

[org/gnome/desktop/session]
idle-delay=uint32 0

[org/gnome/desktop/screensaver]
lock-enabled=false
CONF
    cat > "$root/etc/dconf/db/odq.d/locks/gnome" <<'CONF'
/org/gnome/shell/enabled-extensions
/org/gnome/shell/disable-user-extensions
CONF
    gnome_write_capture "$root/usr/local/lib/odq/capture"
}

gnome_write_capture() {
    cat > "$1" <<'CAPTURE'
#!/bin/bash
# Called as odq by the common smoke runner with the ACTUAL session environment.
# GNOME Shell restricts Screenshot D-Bus callers under Wayland. The packaged
# gnome-screenshot has a recognized application identity; generic gdbus may be
# denied. No unsafe-mode, extension, XWayland image, or identity-spoof fallback.
set -euo pipefail
[[ $# == 1 && $1 == /* && $1 == *.png ]] || {
    echo 'Usage: capture /absolute/new-image.png' >&2; exit 64;
}
[[ ${XDG_SESSION_TYPE:-} == wayland ]] || {
    echo 'GNOME capture requires the verified Wayland session' >&2; exit 78;
}
[[ -n ${DBUS_SESSION_BUS_ADDRESS:-} && -n ${XDG_RUNTIME_DIR:-} ]] || {
    echo 'Missing live session bus/runtime environment' >&2; exit 78;
}
target=$1
[[ -d $(dirname "$target") && ! -e $target && ! -L $target ]] || {
    echo 'Capture output must be a new file in an existing guest directory' >&2; exit 64;
}
work=$(mktemp -d "$(dirname "$target")/.gnome-capture.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
image=$work/image.png
valid_png() {
    python3 - "$image" <<'PY'
import sys
from PIL import Image
try:
    with Image.open(sys.argv[1]) as image:
        if image.format != 'PNG':
            raise ValueError('not PNG')
        image.load()
        if image.width < 1 or image.height < 1:
            raise ValueError('empty image')
except Exception as exc:
    print(f'No valid guest PNG: {exc}', file=sys.stderr)
    sys.exit(1)
PY
}
if timeout 25s gnome-screenshot --file="$image" && valid_png; then
    mv -- "$image" "$target"
    printf 'GNOME screenshot captured: %s\n' "$target"
    exit 0
fi
rm -f -- "$image"
if timeout 25s gdbus call --session --dest org.gnome.Shell.Screenshot \
    --object-path /org/gnome/Shell/Screenshot \
    --method org.gnome.Shell.Screenshot.Screenshot false false "$image" && valid_png; then
    mv -- "$image" "$target"
    printf 'GNOME Shell screenshot captured: %s\n' "$target"
    exit 0
fi
echo 'BLOCKED: GNOME Wayland screenshot denied or invalid; interactive portal approval may be required. No screenshot proof produced.' >&2
exit 78
CAPTURE
    chmod 0755 "$1"
}

# Subshell gives the EXIT trap its own durable variables and no effect on the
# caller. Optional root is for fixture tests only, never a main CLI argument.
gnome_with_service_policy() (
    policy=$1/usr/sbin/policy-rc.d
    backup=
    shift
    # Preserve the existing policy, including a symlink, on success or failure.
    if [[ -e $policy || -L $policy ]]; then
        backup=$(mktemp "${policy%/*}/odq-policy-rc.d.XXXXXXXX")
        mv -- "$policy" "$backup"
    fi
    trap 'rm -f -- "$policy"; if [[ -n $backup ]]; then mv -- "$backup" "$policy"; fi' EXIT
    printf '#!/bin/sh\nexit 101\n' > "$policy"
    chmod 0755 "$policy"
    "$@"
)

gnome_install_packages() {
    apt-get update
    apt-get install -y --no-install-recommends gdm3 gnome-session gnome-shell gjs \
        gnome-settings-daemon gnome-control-center gnome-terminal nautilus \
        gnome-screenshot gsettings-desktop-schemas dbus-user-session dconf-cli \
        libgl1-mesa-dri mesa-utils fonts-dejavu-core xdg-desktop-portal-gnome
    # The default server image does not ship these. Purge if a recipe rerun or
    # package dependency introduced them: this lab explicitly qualifies NO tray.
    local package
    for package in gnome-shell-extension-appindicator gnome-shell-extension-ubuntu-dock \
        gnome-shell-extensions; do
        if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed'; then
            apt-get purge -y "$package"
        fi
    done
}

gnome_main() {
    [[ $# == 0 ]] || { echo 'gnome.sh takes no arguments' >&2; return 64; }
    gnome_guard
    # shellcheck disable=SC1091
    source /root/odq/common.sh
    odq_common
    export DEBIAN_FRONTEND=noninteractive
    gnome_with_service_policy '' gnome_install_packages
    gnome_write_config ''
    chown odq:odq /home/odq/.dmrc
    dconf update
    printf '/usr/sbin/gdm3\n' > /etc/X11/default-display-manager
    # Ubuntu display-manager units can be static. Select the unit explicitly,
    # without relying on enable working for every packaged alias.
    ln -sfn /usr/lib/systemd/system/gdm.service /etc/systemd/system/display-manager.service
    systemctl daemon-reload
    systemctl set-default graphical.target
    odq_finalize
    # Orchestrator starts/reboots the guest after this completes, then checks
    # active Wayland login, GNOME, Orca and screenshot. Install is not smoke.
    echo 'GNOME guest configured; reboot and run common smoke. Runtime proof pending.'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    gnome_main "$@"
fi
