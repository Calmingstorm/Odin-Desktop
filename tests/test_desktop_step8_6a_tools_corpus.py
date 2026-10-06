"""Whole inherited tool suites, private profile and canonical OS peer owner."""
import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.step8_6a_tools import (
    CASE_MAP,
    STATE,
    SUITES,
    MCPManager,
    adapted_tree,
    load,
    owner_fixture,
)


@pytest.fixture(autouse=True)
async def _private_canonical_owner(tmp_path):
    async with owner_fixture(tmp_path):
        yield


load(globals())


@pytest.mark.parametrize("name", SUITES)
def test_6a_tools_frozen_corpus(name):
    original, adapted = adapted_tree(name)
    assert corpus(original) == corpus(adapted)
    expected = {
        entry[0].replace(".", "::") for entry in corpus(original)["cases"]
    }
    from tests.desktop_adapters.step8_6a_tools import CORPUS_EXCLUSIONS

    expected -= {item["case"].replace(".", "::")
                 for item in CORPUS_EXCLUSIONS.get(name, ())}
    actual = {selector.split("::", 1)[1] for selector in CASE_MAP
              if selector.startswith(f"tests/{name}.py::")}
    assert actual == expected


async def test_6a_mcp_service_rejects_payload_identity_without_canonical_owner():
    manager = MCPManager()
    state = STATE.get()
    outcome = await manager.desktop_service.execute("mcp_missing", {}, owner_id="payload-only")
    assert not outcome.ok
    assert "authority is unavailable" in outcome.text
    outcome = await manager.desktop_service.execute(
        "mcp_missing", {}, owner_id=state.authority.owner_id)
    assert not outcome.ok
    assert "not currently published" in outcome.text
