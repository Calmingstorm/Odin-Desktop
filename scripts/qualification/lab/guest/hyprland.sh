#!/bin/bash
# Guest-only provisioning. Source this file to generate offline fixtures.
set -euo pipefail

odq_hyprland_files() {
    local root=${1:?destination root required}
    install -d "$root/etc/sddm.conf.d" "$root/usr/share/wayland-sessions" \
        "$root/usr/local/lib/odq" "$root/home/odq/.config/hypr"
    cat > "$root/etc/sddm.conf.d/90-odq.conf" <<'EOF'
[Autologin]
User=odq
Session=odq-hyprland.desktop
Relogin=false
EOF
    cat > "$root/usr/share/wayland-sessions/odq-hyprland.desktop" <<'EOF'
[Desktop Entry]
Name=Odin qualification Hyprland (software renderer)
Type=Application
Exec=/usr/local/lib/odq/hyprland-session
DesktopNames=Hyprland
EOF
    cat > "$root/usr/local/lib/odq/hyprland-session" <<'EOF'
#!/bin/bash
set -euo pipefail
test "$(id -un)" = odq || exit 77
: "${XDG_RUNTIME_DIR:?SDDM PAM must create the user runtime directory}"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=Hyprland XDG_SESSION_DESKTOP=Hyprland
export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe
# 0.53 uses Aquamarine, not wlroots. Do not cargo-cult old WLR_* switches.
export AQ_NO_MODIFIERS=1 HYPRLAND_EGL_NO_MODIFIERS=1
export GTK_MODULES=gail:atk-bridge GTK_A11Y=atspi QT_ACCESSIBILITY=1 NO_AT_BRIDGE=0
export QT_QPA_PLATFORM=wayland GDK_BACKEND=wayland
exec dbus-run-session -- Hyprland --config /home/odq/.config/hypr/hyprland.conf
EOF
    cat > "$root/home/odq/.config/hypr/hyprland.conf" <<'EOF'
# Incus emulated output only. No host GPU or headless substitute.
monitor = , preferred, auto, 1
exec-once = /usr/local/lib/odq/hyprland-ready
exec-once = foot --title odq-native-wayland
xwayland {
    enabled = false
}
cursor {
    no_hardware_cursors = true
}
animations {
    enabled = false
}
decoration {
    blur {
        enabled = false
    }
}
misc {
    disable_hyprland_logo = true
    disable_splash_rendering = true
}
bind = SUPER, Q, killactive
bind = SUPER, RETURN, exec, foot
EOF
    cat > "$root/usr/local/lib/odq/hyprland-ready" <<'EOF'
#!/bin/bash
set -euo pipefail
# Called inside Hyprland: activation receives the compositor's actual environment.
# This nested dbus-run-session bus has no systemd user manager. Update only
# its activation environment, never the main PAM user's manager/bus environment.
dbus-update-activation-environment \
    WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE HYPRLAND_INSTANCE_SIGNATURE
gsettings set org.gnome.desktop.interface toolkit-accessibility true
gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
    --method org.a11y.Bus.GetAddress
# Preserve the nested session bus for the parent smoke runner. No guessed bus.
python3 - <<'PY'
import json, os
from pathlib import Path
keys = ('WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
        'HYPRLAND_INSTANCE_SIGNATURE', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP')
path = Path(os.environ['XDG_RUNTIME_DIR']) / 'odq-hyprland-session.json'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump({key: os.environ[key] for key in keys}, stream)
PY
exec orca --replace
EOF
    cat > "$root/usr/local/lib/odq/capture" <<'EOF'
#!/usr/bin/python3
"""Capture the actual native Hyprland session as odq, without an X11 fallback."""
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import subprocess
import sys
import tempfile


def capture(destination):
    uid = os.getuid()
    if pwd.getpwuid(uid).pw_name != 'odq':
        raise RuntimeError('capture must run as odq')
    runtime = Path('/run/user') / str(uid)
    record = runtime / 'odq-hyprland-session.json'
    info = record.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise RuntimeError('untrusted compositor environment record')
    session = json.loads(record.read_text())
    required = {'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
                'HYPRLAND_INSTANCE_SIGNATURE', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP'}
    if set(session) != required or not all(isinstance(v, str) and v for v in session.values()):
        raise RuntimeError('incomplete compositor environment')
    if (session['XDG_SESSION_TYPE'] != 'wayland' or
            session['XDG_CURRENT_DESKTOP'] != 'Hyprland' or
            session['XDG_RUNTIME_DIR'] != str(runtime)):
        raise RuntimeError('not the native odq Wayland session')
    display = Path(session['WAYLAND_DISPLAY'])
    if display.is_absolute() or display.name != str(display):
        raise RuntimeError('Wayland display must be a local socket basename')
    sock = (runtime / display).lstat()
    if not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != uid:
        raise RuntimeError('no owned live Wayland socket')
    with socket.socket(socket.AF_UNIX) as probe:
        probe.settimeout(3)
        probe.connect(str(runtime / display))
    env = os.environ.copy()
    env.pop('DISPLAY', None)
    env.update(session)
    monitors = json.loads(subprocess.check_output(['hyprctl', '-j', 'monitors'], env=env,
                                                 timeout=15, text=True))
    if not isinstance(monitors, list) or not any(
            m.get('width', 0) > 0 and m.get('height', 0) > 0 and
            not m.get('disabled', False) and not m.get('name', '').startswith('HEADLESS')
            for m in monitors):
        raise RuntimeError('no active emulated display; headless is not lab proof')
    address = subprocess.check_output(
        ['gdbus', 'call', '--session', '--dest', 'org.a11y.Bus', '--object-path',
         '/org/a11y/bus', '--method', 'org.a11y.Bus.GetAddress'], env=env,
        timeout=15, text=True)
    if 'unix:' not in address:
        raise RuntimeError('accessibility bus did not return a local address')
    subprocess.run(['pgrep', '-u', str(uid), '-f', '(^|/)orca( |$)'], check=True,
                   stdout=subprocess.DEVNULL, timeout=10)
    output = Path(destination).absolute()
    fd, temporary = tempfile.mkstemp(prefix='.odq-grim-', suffix='.png', dir=output.parent)
    os.close(fd)
    try:
        subprocess.run(['grim', '-t', 'png', temporary], env=env, check=True, timeout=30)
        # Decode the fresh image rather than declaring success from an old PNG.
        import gi
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import GdkPixbuf
        image = GdkPixbuf.Pixbuf.new_from_file(temporary)
        if image.get_width() < 1 or image.get_height() < 1:
            raise RuntimeError('empty screenshot')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({'screenshot': str(output), 'session_type': 'wayland',
                      'desktop': 'Hyprland', 'accessibility_bus': 'responding',
                      'orca': 'process-present', 'monitors': monitors,
                      'renderer_qualification': 'requires EGL renderer log review'}))


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise RuntimeError('usage: capture OUTPUT.png')
        capture(sys.argv[1])
    except Exception as error:
        print('Hyprland capture unavailable: ' + str(error), file=sys.stderr)
        sys.exit(78)
EOF
    chmod 0755 "$root/usr/local/lib/odq/"{hyprland-session,hyprland-ready,capture}
}

odq_hyprland_install() {
    [[ $(id -u) == 0 ]] || { echo 'Guest root required' >&2; return 77; }
    case $(systemd-detect-virt --vm) in
        kvm|qemu) ;;
        *) echo 'Refusing non-QEMU/KVM guest provisioning' >&2; return 77 ;;
    esac
    odq_hyprland_platform /etc/os-release
    [[ $(hostname) == odq-hyprland ]] || {
        echo 'Refusing guest without odq-hyprland hostname' >&2; return 77;
    }
    # shellcheck source=/dev/null
    source /root/odq/common.sh
    odq_common
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    # Refuse silently changing compositor version if this build disappears.
    # SDDM only recommends pam_systemd; without it PAM need not create the
    # logind session/runtime directory required by the native launcher.
    # espeak-ng alone does not install Speech Dispatcher's espeak output module.
    # Ready needs gsettings/gdbus (libglib2.0-bin), not just their schemas.
    # Explicitly supply the launcher's D-Bus tools and capture's pgrep too.
    apt-get install -y --no-install-recommends hyprland=0.53.3+ds-4 \
        sddm libpam-systemd grim foot dbus-x11 dbus-daemon libglib2.0-bin procps \
        libgl1-mesa-dri mesa-utils \
        orca at-spi2-core speech-dispatcher speech-dispatcher-espeak-ng espeak-ng \
        gsettings-desktop-schemas \
        gir1.2-gdkpixbuf-2.0 python3-gi fonts-dejavu-core
    odq_hyprland_files /
    # install -d may create the intermediate .config as root; Orca needs it writable.
    chown odq:odq /home/odq/.config
    chown -R odq:odq /home/odq/.config/hypr
    systemctl disable --now gdm3.service lightdm.service 2>/dev/null || true
    systemctl enable sddm.service
    systemctl set-default graphical.target
    odq_finalize
    # Parent reboots/starts the guest through the one-VM-at-a-time lifecycle.
}

odq_hyprland_platform() {
    local ID VERSION_CODENAME
    # shellcheck source=/dev/null
    source "${1:?os-release required}"
    [[ ${ID:-} == ubuntu && ${VERSION_CODENAME:-} == resolute && $(uname -m) == x86_64 ]] || {
        echo 'Hyprland recipe requires Ubuntu resolute x86_64' >&2; return 77;
    }
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    [[ $# == 0 ]] || { echo 'usage: hyprland.sh (guest install only)' >&2; exit 64; }
    odq_hyprland_install
fi
