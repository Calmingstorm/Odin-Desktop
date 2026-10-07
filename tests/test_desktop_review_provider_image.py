"""Existing image behavior on real Desktop owners, not inherited restoration."""

import pytest

from src.desktop.management import MethodError
from tests.desktop_adapters.review_provider_image import temporary_settings


@pytest.fixture
def settings(tmp_path):
    return temporary_settings(tmp_path)


async def intent(settings, operations, revision=None):
    return await settings.handle(
        "models.image.intent",
        {
            "operations": operations,
            "expected_revision": revision
            if revision is not None
            else settings.schema()["image_models_revision"],
        },
    )


async def test_presence_pin_and_equal_value_stale_follow(settings):
    initial = settings.schema()
    image = initial["image_models"]["image_model"]
    assert image["status"] == "follow" and image["effective"] == image["default"]
    assert initial["image_models"]["outer_model"]["status"] == "pin"
    pinned = await intent(settings, {"image_model": "pin"})
    assert pinned["image_models"]["image_model"]["status"] == "pin"
    assert "image_model:" in settings.paths.config_file.read_text()
    with pytest.raises(MethodError) as failure:
        await intent(settings, {"image_model": "follow"}, initial["image_models_revision"])
    assert failure.value.code == "stale_binding"
    assert failure.value.disposition == "stale_binding"
    assert "image_model:" in settings.paths.config_file.read_text()


async def test_atomic_follow_preserves_source_and_runtime(settings):
    result = await intent(settings, {"image_model": "follow", "outer_model": "follow"})
    assert all(item["status"] == "follow" for item in result["image_models"].values())
    assert (
        settings.config.image.openai.outer_model == result["image_models"]["outer_model"]["default"]
    )
    text = settings.paths.config_file.read_text()
    assert "outer_model:" not in text and "image_model:" not in text
    assert "# keep this" in text and "image_models" not in text


async def test_real_write_failure_never_publishes(settings, monkeypatch):
    import src.desktop.settings as domain

    before, text = settings.config, settings.paths.config_file.read_text()

    def fail(*args, **kwargs):
        raise OSError("temporary disk full")

    monkeypatch.setattr(domain, "_patch_config_paths", fail)
    with pytest.raises(MethodError) as failure:
        await intent(settings, {"outer_model": "follow"})
    assert failure.value.code == "internal_error"
    assert "not saved" in failure.value.message
    assert settings.config is before and settings.paths.config_file.read_text() == text


@pytest.mark.parametrize("operations", [{}, [], {"image_model": "bad"}, {"other": "follow"}])
async def test_invalid_operation_is_rejected_without_write(settings, operations):
    before, text = settings.config, settings.paths.config_file.read_text()
    with pytest.raises(MethodError) as failure:
        await intent(settings, operations)
    assert failure.value.code == "bad_request"
    assert settings.config is before and settings.paths.config_file.read_text() == text


async def test_leaf_save_preserves_follow_then_pins(settings):
    settings.owners["settings.set"] = lambda desired, previous, changes: True
    await settings.handle(
        "settings.set",
        {
            "expected_revision": settings.revision,
            "changes": [{"path": "timezone", "value": "UTC"}],
        },
    )
    text = settings.paths.config_file.read_text()
    assert "image_model:" not in text and "outer_model: custom-outer" in text
    await settings.handle(
        "settings.set",
        {
            "expected_revision": settings.revision,
            "changes": [{"path": "image.openai.image_model", "value": "my-model"}],
        },
    )
    assert "image_model: my-model" in settings.paths.config_file.read_text()
    assert settings.schema()["image_models"]["image_model"]["status"] == "pin"


async def test_current_intent_conflict_preserves_concurrent_save(settings):
    old = settings.schema()["image_models_revision"]
    settings.save_changes(
        [(("image", "openai", "outer_model"), "new-current"), (("timezone",), "Europe/London")]
    )
    with pytest.raises(MethodError) as failure:
        await intent(settings, {"outer_model": "pin"}, old)
    assert failure.value.code == "stale_binding"
    assert settings.config.image.openai.outer_model == "new-current"
    assert settings.config.timezone == "Europe/London"
    text = settings.paths.config_file.read_text()
    assert "outer_model: new-current" in text and "timezone: Europe/London" in text


async def test_whole_image_roundtrip_preserves_follow_and_pin(settings):
    settings.owners["settings.set"] = lambda desired, previous, changes: True
    result = await settings.handle(
        "settings.set",
        {
            "expected_revision": settings.revision,
            "changes": [
                {"path": "image", "value": settings.config.image.model_dump()},
                {"path": "timezone", "value": "UTC"},
            ],
        },
    )
    assert result["revision"] == settings.revision
    text = settings.paths.config_file.read_text()
    assert "image_model:" not in text and "outer_model: custom-outer" in text
    assert settings.schema()["image_models"]["image_model"]["status"] == "follow"
    assert settings.schema()["image_models"]["outer_model"]["status"] == "pin"
