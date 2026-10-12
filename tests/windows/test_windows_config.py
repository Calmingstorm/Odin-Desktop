"""Odin's Linux-only computer-use paths keep their meaning on Windows."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.schema import ComputerUseConfig


def test_the_shipped_linux_paths_load_on_windows():
    config = ComputerUseConfig()
    assert config.wayland_guardian_binary == "/usr/libexec/odin-computer-wayland-input"
    assert config.hyprland_guardian_binary.startswith("/usr/local/libexec/")


@pytest.mark.parametrize("field", ["hyprland_guardian_binary", "wayland_guardian_binary"])
@pytest.mark.parametrize("value", ["relative/odin", "/usr/../odin", "C:\\odin\\input.exe"])
def test_they_are_checked_as_posix_paths_as_on_linux(field, value):
    if field == "wayland_guardian_binary" and value == "/usr/../odin":
        pytest.skip("Linux checks parent references only for the Hyprland paths")
    with pytest.raises(ValidationError):
        ComputerUseConfig(**{field: value})


def test_an_empty_hyprland_path_stays_unset_and_the_guardian_stays_required():
    assert ComputerUseConfig(hyprland_guardian_binary="").hyprland_guardian_binary == ""
    with pytest.raises(ValidationError):
        ComputerUseConfig(wayland_guardian_binary="")
