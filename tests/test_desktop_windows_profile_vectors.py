"""The Windows profile layout and pipe names the app computes are the engine's own.

`tests/fixtures/windows-profile-vectors.json` is read here through the engine's pure helpers and by
the app's vitest through `platform/windows.ts`, so neither side can drift from the other.
"""
from __future__ import annotations

import json
import ntpath
from pathlib import Path

import pytest

from src.desktop.platform.windows import pipe_name_for, windows_profile_paths

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "windows-profile-vectors.json")
                     .read_text(encoding="utf-8"))


def windows(path) -> str:
    return ntpath.normpath(str(path))


@pytest.mark.parametrize("case", VECTORS["pipes"], ids=lambda case: case["profile"])
def test_the_pipe_name_is_the_engines(case):
    assert pipe_name_for(case["profile"], case["sid"]) == case["name"]


@pytest.mark.parametrize("case", VECTORS["layouts"], ids=lambda case: case["localappdata"])
def test_the_layout_is_the_engines(case):
    paths = windows_profile_paths(case["profile"], environ={"LOCALAPPDATA": case["localappdata"]})
    assert [windows(paths.config_dir), windows(paths.data_dir), windows(paths.cache_dir)] == [
        case["config"], case["data"], case["cache"]]
    # The app's bootstrap files are the names the engine's first-start check admits.
    assert windows(paths.config_dir / "ipc.token") == case["token"]
    assert windows(paths.config_dir / "app-state.json") == case["app_state"]
    assert windows(paths.data_dir / "logs") == case["logs"]


@pytest.mark.parametrize("base", VECTORS["refused_by_both"]["localappdata"])
def test_the_engine_refuses_what_the_app_refuses(base):
    with pytest.raises(ValueError):
        windows_profile_paths("default", environ={"LOCALAPPDATA": base})


@pytest.mark.parametrize("profile", VECTORS["refused_by_both"]["profile"])
def test_the_engine_refuses_the_profiles_the_app_refuses(profile):
    with pytest.raises(ValueError):
        windows_profile_paths(profile, environ={"LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"})


def test_what_only_the_app_refuses_the_engine_accepts():
    """The app admits a subset of the engine's inputs, named in the vectors."""
    only = VECTORS["refused_by_the_app_only"]
    windows_profile_paths("default", environ={"LOCALAPPDATA": ""}, home="C:\\Users\\x")
    for profile in only["profile"]:
        windows_profile_paths(profile, environ={"LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"})
