FROM ubuntu@sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b
# Official Ubuntu 24.04 amd64 manifest, inspected/pulled 2026-10-06.
# This is an offline fixture image, NOT a native desktop qualification guest.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3.12 python3-pytest python3-pil python3-yaml dconf-cli sudo util-linux bash coreutils procps && rm -rf /var/lib/apt/lists/* \
    && userdel ubuntu && groupadd -g 1000 testuser && useradd -m -u 1000 -g 1000 testuser \
    && printf 'Defaults:testuser !use_pty\ntestuser ALL=(root) NOPASSWD: /usr/bin/env\n' >/etc/sudoers.d/lab-fixture \
    && chmod 0440 /etc/sudoers.d/lab-fixture && visudo -cf /etc/sudoers.d/lab-fixture \
    && mkdir -p /fixture /home/testuser/private && chown 1000:1000 /home/testuser/private
# Root is used only for the copied-tree ownership fix. Pytest is always UID 1000.
# Do NOT set NNP: the unchanged KDE emitter fixtures require real container sudo.
WORKDIR /fixture
ENTRYPOINT ["/bin/bash", "-c", "chown -R 1000:1000 /fixture && exec setpriv --reuid=1000 --regid=1000 --clear-groups --inh-caps=-all --ambient-caps=-all /usr/bin/env -i PATH=/usr/bin:/bin HOME=/home/testuser/private PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.12 /fixture/scripts/qualification/lab/ci/run.py \"$@\"", "lab-fixture"]
