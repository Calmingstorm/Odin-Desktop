#!/usr/bin/env bash
# This file is copied into the guest. Never source it on the workstation.
set -euo pipefail

odq_common_packages() {
    printf '%s\n' orca dbus-x11 at-spi2-core python3 python3-gi python3-pil \
        gir1.2-atspi-2.0 gir1.2-gtk-3.0 fonts-dejavu-core mesa-utils \
        libpam-systemd speech-dispatcher speech-dispatcher-espeak-ng espeak-ng iproute2
}

# Pure configuration emitter: the caller supplies the guest root or a fixture.
# No daemon commands, host provisioning, or logind restart in this helper.
odq_common_power_config() {
    local root=${1:?Explicit guest or fixture root required} unit
    install -d -m 0755 "$root/etc/systemd/logind.conf.d" "$root/etc/systemd/system"
    cat >"$root/etc/systemd/logind.conf.d/99-odq-power.conf" <<'EOF'
[Login]
HandlePowerKey=poweroff
HandlePowerKeyLongPress=poweroff
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
EOF
    for unit in sleep.target suspend.target hibernate.target hybrid-sleep.target \
                suspend-then-hibernate.target systemd-suspend.service \
                systemd-hibernate.service systemd-hybrid-sleep.service \
                systemd-suspend-then-hibernate.service; do
        ln -sfn /dev/null "$root/etc/systemd/system/$unit"
    done
}

# Pure emitter, also exercised against a fixture. In production it is called
# only by the VM-guarded provisioning function below, never on the workstation.
odq_common_accessibility_config() {
    local root=${1:?Explicit guest or fixture root required}
    install -d -m 0755 "$root/usr/local/lib/odq" "$root/etc/xdg/autostart"
    # There must be one startup owner, not competing Orca --replace processes.
    # Hidden is the standard XDG autostart override, scoped to the lab guest.
    cat >"$root/etc/xdg/autostart/orca-autostart.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Orca
Hidden=true
EOF
    rm -f -- "$root/etc/xdg/autostart/odq-accessibility.desktop"
    cat >"$root/usr/local/lib/odq/orca-session" <<'EOF'
#!/bin/sh
set -eu
# Serialize both settings with the single Orca launch. The old independent
# accessibility autostart could change screen-reader state during Orca startup.
gsettings set org.gnome.desktop.interface toolkit-accessibility true
gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
case ":${XDG_CURRENT_DESKTOP:-}:" in
    *:KDE:*)
        # Plasma autostarts may run before its shell owns the session bus name.
        # This is a bounded prerequisite wait, not an Orca restart loop. Name
        # ownership is only a readiness proxy; fresh-boot smoke remains required.
        ready=false
        attempt=0
        while [ "$attempt" -lt 30 ]; do
            if dbus-send --session --print-reply --reply-timeout=1000 \
                --dest=org.freedesktop.DBus /org/freedesktop/DBus \
                org.freedesktop.DBus.NameHasOwner string:org.kde.plasmashell \
                2>/dev/null | grep -q 'boolean true'; then
                ready=true
                break
            fi
            attempt=$((attempt + 1))
            if [ "$attempt" -lt 30 ]; then sleep 1; fi
        done
        if [ "$ready" != true ]; then
            echo 'Orca startup refused: Plasma session bus name not ready' >&2
            exit 78
        fi
        ;;
esac
exec orca --replace
EOF
    chmod 0755 "$root/usr/local/lib/odq/orca-session"
    cat >"$root/etc/xdg/autostart/odq-orca.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Qualification Orca
Exec=/usr/local/lib/odq/orca-session
NoDisplay=true
EOF
}

odq_common() {
    [[ $(systemd-detect-virt) == kvm || $(systemd-detect-virt) == qemu ]] || {
        echo 'Refusing provisioning outside an actual VM' >&2; return 1;
    }
    [[ $(id -u) == 0 ]] || { echo 'Guest root required' >&2; return 1; }
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    local -a packages
    mapfile -t packages < <(odq_common_packages)
    apt-get install -y --no-install-recommends "${packages[@]}"
    odq_common_power_config /
    systemctl daemon-reload
    id odq >/dev/null 2>&1 || useradd --create-home --shell /bin/bash odq
    passwd --lock odq
    install -d -m 0755 /usr/local/lib/odq /etc/xdg/autostart
    # Remove remote login and guest discovery services. Incus agent remains the
    # sole management channel, via the VM transport, not a forwarded TCP port.
    for unit in ssh.service ssh.socket sshd.service avahi-daemon.service \
                avahi-daemon.socket cups.service cups.socket; do
        systemctl disable --now "$unit" 2>/dev/null || true
        systemctl mask "$unit"
    done
    odq_common_accessibility_config /
    systemctl set-default graphical.target
}

odq_finalize() {
    [[ $(systemd-detect-virt) == kvm || $(systemd-detect-virt) == qemu ]] || return 1
    [[ $(id -u) == 0 && $(hostname) == odq-* ]] || return 1
    for unit in ssh.service ssh.socket sshd.service avahi-daemon.service \
                avahi-daemon.socket cups.service cups.socket cups.path \
                rpcbind.service rpcbind.socket; do
        systemctl disable --now "$unit" 2>/dev/null || true
        systemctl mask "$unit"
    done
    install -d -m 0700 /root/odq/evidence
    dpkg-query -W >/root/odq/evidence/packages.tsv
    ss -lntup >/root/odq/evidence/listeners.txt
}

# Test-only emission interface. Executing this file never provisions anything.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    case ${1:-} in
        --print-packages) odq_common_packages ;;
        --write-power-config)
            [[ $# == 2 && $2 == /* && $2 != / ]] || exit 64
            odq_common_power_config "$2"
            ;;
        --write-accessibility-config)
            [[ $# == 2 && $2 == /* && $2 != / ]] || exit 64
            odq_common_accessibility_config "$2"
            ;;
        *) exit 64 ;;
    esac
fi
