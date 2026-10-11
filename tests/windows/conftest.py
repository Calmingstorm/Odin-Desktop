"""Native Windows tests: collected only on Windows, run by the Windows engine job."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

collect_ignore_glob = [] if sys.platform == "win32" else ["test_*.py"]


@pytest.fixture
def profile_root(tmp_path) -> Path:
    """A Desktop namespace (``odin-desktop\\<profile>``) under the test's own folder."""
    return tmp_path / "odin-desktop" / "test"


@pytest.fixture
def sddl():
    """Apply an SDDL DACL to a path, as a test's own setup step."""
    from src.desktop.platform import win32

    def apply(path, descriptor: str, *, directory: bool) -> None:
        flags = win32.FILE_FLAG_OPEN_REPARSE_POINT
        if directory:
            flags |= win32.FILE_FLAG_BACKUP_SEMANTICS
        handle = win32.create_file(
            path, win32.READ_CONTROL | win32.WRITE_DAC,
            win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE | win32.FILE_SHARE_DELETE,
            win32.OPEN_EXISTING, flags)
        try:
            with win32.SecurityDescriptor(descriptor) as parsed:
                info = win32.DACL_SECURITY_INFORMATION | win32.PROTECTED_DACL_SECURITY_INFORMATION
                status = win32.SetSecurityInfo(handle, win32.SE_FILE_OBJECT, info, None, None,
                                               parsed.dacl(), None)
            if status:
                raise win32.error(status)
        finally:
            win32.close(handle)

    return apply
