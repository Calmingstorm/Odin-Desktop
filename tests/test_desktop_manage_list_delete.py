"""Delete lists without changing clear semantics (Odin 4.14 #641, carried to Desktop).

Desktop's lists belong to the profile's one owner: the shared/personal label is not an access
control, and a fresh Desktop profile never reads Odin's legacy grocery_list.json. The two cases
that test Odin's ownership and migration rules state Desktop's instead."""

import json

import pytest

from src.tools.execution_outcome import ToolFailure
from src.tools.registry import TOOL_MAP
from tests.test_handlers_state_lists import _make


@pytest.mark.parametrize("clear_first", [False, True])
async def test_delete_persists_removal_and_preserves_other_lists(tmp_path, clear_first):
    tools, _ = _make(tmp_path)
    for name in ("todo", "keep"):
        await tools._handle_manage_list(
            {"action": "add", "list_name": name, "items": ["entry"]}, user_id="owner"
        )
    if clear_first:
        await tools._handle_manage_list({"action": "clear", "list_name": "todo"})
        assert "todo" in tools._load_lists()
        assert tools._load_lists()["todo"]["items"] == []

    result = await tools._handle_manage_list({"action": "delete", "list_name": " TODO "})
    assert result == "Deleted the 'todo' list."
    restarted, _ = _make(tmp_path)
    assert set(restarted._load_lists()) == {"keep"}
    assert "todo" not in await restarted._handle_manage_list({"action": "list_all"})


async def test_delete_unknown_is_refused_without_writing(tmp_path):
    tools, _ = _make(tmp_path)
    result = await tools._handle_manage_list({"action": "delete", "list_name": "missing"})
    assert isinstance(result, ToolFailure)
    assert result == "The 'missing' list doesn't exist."
    assert not (tmp_path / "lists.json").exists()


async def test_a_personal_label_is_not_an_access_control_on_desktop(tmp_path):
    tools, _ = _make(tmp_path)
    await tools._handle_manage_list(
        {"action": "add", "list_name": "secret", "items": ["x"], "owner": "personal"},
        user_id="owner",
    )
    assert "Deleted" in await tools._handle_manage_list(
        {"action": "delete", "list_name": "secret"}, user_id="another-caller"
    )
    restarted, _ = _make(tmp_path)
    assert restarted._load_lists() == {}


async def test_deleting_the_last_list_never_resurrects_a_legacy_grocery_file(tmp_path):
    (tmp_path / "grocery_list.json").write_text(json.dumps({"items": [{"name": "Bread"}]}))
    tools, _ = _make(tmp_path)
    assert "Bread" not in await tools._handle_manage_list(
        {"action": "show", "list_name": "grocery"}
    )  # a fresh Desktop profile never migrates Odin's legacy file
    await tools._handle_manage_list({"action": "add", "list_name": "grocery", "items": ["Milk"]})
    assert "Deleted" in await tools._handle_manage_list(
        {"action": "delete", "list_name": "grocery"}
    )
    restarted, _ = _make(tmp_path)
    assert restarted._load_lists() == {}
    assert "No lists exist" in await restarted._handle_manage_list({"action": "list_all"})


def test_delete_in_tool_schema():
    assert "delete" in TOOL_MAP["manage_list"]["input_schema"]["properties"]["action"]["enum"]
