#!/usr/bin/env python3
"""Use existing lab session discovery, then drop to the guest graphical owner."""
import os
import pwd
import sys

from smoke import session_environment


def main():
    if os.geteuid() != 0 or sys.argv[1] not in ('cinnamon', 'gnome', 'kde'):
        raise RuntimeError('Guest root bootstrap and known desktop required')
    account = pwd.getpwnam('odq')
    expected = 'x11' if sys.argv[1] == 'cinnamon' else 'wayland'
    environment = session_environment(account.pw_uid, expected)
    os.initgroups('odq', account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    environment.update({'HOME': account.pw_dir, 'USER': 'odq', 'LOGNAME': 'odq',
                        'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    os.execvpe(sys.argv[2], sys.argv[2:], environment)


if __name__ == '__main__':
    main()
