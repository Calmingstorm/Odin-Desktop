"""Desktop socket guard, without changes to upstream pool behavior."""
from __future__ import annotations

import os

from ..runtime_paths import runtime_profile_paths
from ..tools.ssh_pool import SSHConnectionPool as EngineSSHConnectionPool
from .ssh_sockets import (
    REGISTRY_SOCKET_NAME,
    check_socket_path,
    effective_socket_directory,
    prepare_socket_directory,
)


class SSHConnectionPool(EngineSSHConnectionPool):
    def __init__(self, control_persist=60, socket_dir="/tmp/odin_ssh_sockets"):
        socket_dir = effective_socket_directory(socket_dir, runtime_profile_paths())
        check_socket_path(os.path.join(socket_dir, REGISTRY_SOCKET_NAME))
        prepare_socket_directory(socket_dir)
        super().__init__(control_persist=control_persist, socket_dir=socket_dir)

    def get_socket_path(self, host: str, ssh_user: str, target_id: str = "") -> str:
        path = super().get_socket_path(host, ssh_user, target_id)
        check_socket_path(path)
        return path
