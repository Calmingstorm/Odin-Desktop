#!/usr/bin/env bash
# This file is copied into the guest. Never source it on the workstation.
set -euo pipefail

odq_common() {
    [[ $(systemd-detect-virt) == kvm || $(systemd-detect-virt) == qemu ]] || {
        echo 'Refusing provisioning outside an actual VM' >&2; return 1;
    }
    [[ $(id -u) == 0 ]] || { echo 'Guest root required' >&2; return 1; }
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        orca dbus-x11 at-spi2-core python3 python3-gi python3-pil \
        gir1.2-atspi-2.0 gir1.2-gtk-3.0 fonts-dejavu-core mesa-utils \
        speech-dispatcher espeak-ng iproute2
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
    cat >/etc/xdg/autostart/odq-accessibility.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Qualification accessibility
Exec=sh -c 'gsettings set org.gnome.desktop.interface toolkit-accessibility true; gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true'
NoDisplay=true
EOF
    cat >/etc/xdg/autostart/odq-orca.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Qualification Orca
Exec=orca --replace
NoDisplay=true
EOF
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
