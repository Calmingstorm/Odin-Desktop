"""Odin 4.22.0 (#674) on Desktop's skills.save: a rejected create keeps the file it replaced.

A skill file that failed to load is not a loaded skill, so saving its name again goes
through create_skill. A candidate that does not load (bad code, or a definition naming
another skill) used to delete the failed file while the answer said "previous version
retained". Now its bytes and recorded load error stay. create: true still never replaces a
file on disk, a loadable candidate still replaces the failed one, and a file that holds
another loaded skill is never written.
"""
from __future__ import annotations

import pytest

from src.desktop.management import MethodError
from src.permissions.manager import PermissionManager
from tests.test_desktop_skills import code, owner

pytest_plugins = ["tests.test_desktop_skills"]

BROKEN = code("bad", schema={"type": "object", "properties": {}, "required": ["undefined"]})


@pytest.mark.asyncio
async def test_a_rejected_save_over_a_failed_skill_keeps_its_file_and_error(graph):
    directory = graph.settings.paths.data_dir / "skills"
    directory.mkdir()
    (directory / "bad.py").write_text(BROKEN)
    await graph.service.start()
    manager = graph.service.skill_manager
    error = manager.definition_errors["bad.py"]
    token = owner(graph)
    try:
        for candidate in ("def (:::", code("other")):
            with pytest.raises(MethodError) as refused:
                await graph.service.handle("skills.save", {"name": "bad", "code": candidate})
            assert refused.value.code == "bad_request"
            assert (directory / "bad.py").read_text() == BROKEN
            assert manager.definition_errors["bad.py"] == error
            assert not manager.has_skill("bad") and not manager.has_skill("other")
        with pytest.raises(MethodError) as conflict:
            await graph.service.handle("skills.save", {
                "name": "bad", "code": code("bad"), "create": True})
        assert conflict.value.code == "conflict"
        assert (directory / "bad.py").read_text() == BROKEN
        await graph.service.handle("skills.save", {"name": "bad", "code": code("bad")})
        assert manager.has_skill("bad") and "bad.py" not in manager.definition_errors
        assert (directory / "bad.py").read_text() == code("bad")
    finally:
        PermissionManager.reset_request_owner(token)


@pytest.mark.asyncio
async def test_a_file_that_holds_another_loaded_skill_is_never_written(graph):
    directory = graph.settings.paths.data_dir / "skills"
    directory.mkdir()
    (directory / "wrong.py").write_text(code("foreign"))
    await graph.service.start()
    manager = graph.service.skill_manager
    assert manager._skills["foreign"].file_path.name == "wrong.py"
    token = owner(graph)
    try:
        with pytest.raises(MethodError):
            await graph.service.handle("skills.save", {"name": "wrong", "code": code("wrong")})
        assert (directory / "wrong.py").read_text() == code("foreign")
        assert manager.has_skill("foreign") and not manager.has_skill("wrong")
    finally:
        PermissionManager.reset_request_owner(token)
