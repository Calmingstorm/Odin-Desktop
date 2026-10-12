"""Desktop: where the file tools get ``read_binary_file``.

Odin's own ``ssh.read_binary_file``, unchanged off Windows. On Windows its remote read
runs Windows' OpenSSH (phase 3 plan C12); ``ssh.py`` itself stays byte for byte.
"""
from __future__ import annotations

from ..desktop.platform.variants import windows_variant
from . import ssh


@windows_variant("src.desktop.platform.windows_remote:read_binary_file")
async def read_binary_file(
    address: str,
    path: str,
    *,
    max_bytes: int,
    ssh_key_path: str = "",
    known_hosts_path: str = "",
    ssh_user: str = "root",
    port: int = 22,
    host_key_alias: str = "",
    timeout: int = 60,
) -> tuple[bytes | None, str]:
    """``ssh.read_binary_file`` (looked up at call time, as before)."""
    return await ssh.read_binary_file(
        address, path, max_bytes=max_bytes, ssh_key_path=ssh_key_path,
        known_hosts_path=known_hosts_path, ssh_user=ssh_user, port=port,
        host_key_alias=host_key_alias, timeout=timeout)
