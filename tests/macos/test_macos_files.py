"""ACLs on macOS: no allow entry on the profile's own folders, the IPC parent or the credential."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.desktop import ipc_auth, paths
from src.desktop.platform import darwin


def chmod_acl(path: Path, entry: str) -> None:
    subprocess.run(["/bin/chmod", "+a", entry, str(path)], check=True)


@pytest.fixture
def root():
    folder = Path(os.path.realpath(tempfile.mkdtemp(prefix="odacl-")))
    yield folder
    subprocess.run(["/bin/chmod", "-R", "-N", str(folder)], check=False)
    shutil.rmtree(folder, ignore_errors=True)


def test_the_routes_reach_the_macos_variants():
    target = "src.desktop.platform.macos_files:"
    assert paths.private_directory.darwin_target == target + "private_directory"
    assert ipc_auth.private_parent.darwin_target == target + "private_parent"
    assert ipc_auth.load_token.darwin_target == target + "load_token"


def test_allow_entries_count_only_grants(root):
    target = root / "file"
    target.write_text("x")
    fd = os.open(target, os.O_RDONLY)
    try:
        assert darwin.allow_entries(fd) == 0
        chmod_acl(target, "everyone deny write")
        assert darwin.allow_entries(fd) == 0  # a deny entry only narrows access
        chmod_acl(target, "everyone allow read")
        assert darwin.allow_entries(fd) == 1
    finally:
        os.close(fd)
    with pytest.raises(OSError):
        darwin.allow_entries(fd)  # closed: unreadable, never "no ACL"


def test_a_profile_folder_with_a_grant_is_refused_and_left_alone(root):
    profile = root / "odin-desktop" / "default"
    paths.private_directory(profile / "data")
    chmod_acl(profile, "everyone allow list,search")
    with pytest.raises(PermissionError, match="grants access through an ACL entry"):
        paths.private_directory(profile / "data")
    listed = subprocess.run(["/bin/ls", "-led", str(profile)], capture_output=True, text=True)
    assert "everyone allow" in listed.stdout  # refused, never repaired


def test_an_inherited_grant_on_a_new_folder_is_refused(root):
    chmod_acl(root, "everyone allow read,file_inherit,directory_inherit")
    with pytest.raises(PermissionError, match="grants access through an ACL entry"):
        paths.private_directory(root / "odin-desktop" / "default" / "config")


def test_a_deny_entry_and_folders_outside_the_namespace_are_accepted(root):
    chmod_acl(root, "everyone allow read")  # not ours: above the namespace
    profile = root / "odin-desktop" / "default"
    paths.private_directory(profile)
    chmod_acl(profile, "everyone deny delete")
    paths.private_directory(profile / "config")
    outside = root / "configured" / "elsewhere"
    paths.private_directory(outside, repair_namespace=False)
    chmod_acl(outside, "everyone allow read")
    paths.private_directory(outside, repair_namespace=False)  # not a profile folder


def _token(root: Path) -> Path:
    config = root / "odin-desktop" / "default" / "config"
    paths.private_directory(config)
    token = config / "ipc.token"
    token.write_text(secrets.token_hex(32))
    token.chmod(0o600)
    return token


def test_the_credential_is_read_only_without_a_grant(root):
    token = _token(root)
    assert ipc_auth.load_token(token) == token.read_text()
    chmod_acl(token, "everyone allow read")
    with pytest.raises(PermissionError, match="IPC credential file grants access"):
        ipc_auth.load_token(token)


def test_an_ipc_parent_with_a_grant_is_refused_without_leaking_its_descriptor(root):
    socket_path = root / "odin-desktop" / "default" / "core.sock"
    resolved, fd = ipc_auth.private_parent(socket_path, create=True)
    os.close(fd)
    chmod_acl(socket_path.parent, "everyone allow add_file")
    before = darwin.open_descriptor_count()
    with pytest.raises(PermissionError, match="IPC parent grants access"):
        ipc_auth.private_parent(socket_path)
    assert darwin.open_descriptor_count() == before
