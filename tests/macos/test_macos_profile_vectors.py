"""The macOS profile layout and socket paths the app computes are the engine's own.

`tests/fixtures/macos-profile-vectors.json` is read here through the engine's pure helpers and by
the app's vitest through `platform/macos-paths.ts`, so neither side can drift from the other.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.desktop.platform.macos import macos_profile_paths, macos_socket_path

VECTORS = json.loads((Path(__file__).parents[1] / "fixtures" / "macos-profile-vectors.json")
                     .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["layouts"], ids=lambda case: case["socket"][-40:])
def test_the_layout_and_socket_are_the_engines(case):
    paths = macos_profile_paths(case["profile"], home=case["home"])
    assert [str(paths.config_dir), str(paths.data_dir), str(paths.cache_dir)] == [
        case["config"], case["data"], case["cache"]]
    # The app's bootstrap files are the names the engine's first-start check admits.
    assert str(paths.config_dir / "ipc.token") == case["token"]
    assert str(paths.config_dir / "app-state.json") == case["app_state"]
    assert str(paths.data_dir / "logs") == case["logs"]
    assert str(macos_socket_path(case["profile"], Path(case["temp_root"]))) == case["socket"]


@pytest.mark.parametrize("home", VECTORS["refused_by_both"]["home"])
def test_the_engine_refuses_the_homes_the_app_refuses(home):
    with pytest.raises(ValueError):
        macos_profile_paths("default", home=home)


@pytest.mark.parametrize("profile", VECTORS["refused_by_both"]["profile"])
def test_the_engine_refuses_the_profiles_the_app_refuses(profile):
    with pytest.raises(ValueError):
        macos_profile_paths(profile, home="/Users/ada")


@pytest.mark.parametrize("case", VECTORS["refused_by_both"]["socket"])
def test_the_engine_refuses_a_socket_path_over_the_limit(case):
    with pytest.raises(ValueError, match="longer than macOS allows"):
        macos_socket_path(case["profile"], Path(case["temp_root"]))


def test_what_only_the_app_refuses_the_engine_accepts():
    for profile in VECTORS["refused_by_the_app_only"]["profile"]:
        macos_profile_paths(profile, home="/Users/ada")
