"""Frozen lane6 provider corpus through profile owners and real engine algorithms."""
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from src.desktop.providers import _ProviderChange
from src.llm.errors import LLMClientRetiredError
from src.llm.openai_compatible import OpenAICompatibleClient
from tests.desktop_adapters.lane6_providers_cases import load
from tests.desktop_adapters.lane6_providers_engine import GRAPHS


async def test_lane6_providers_cancelled_candidate_rejects_new_generation_lease():
    candidate = OpenAICompatibleClient("fixture", model="chosen")
    candidate.close = AsyncMock()
    change = _ProviderChange(owner=None, config=None, generation=0, clients={},
                             auxiliary=None, created=[candidate])
    await change.rollback()
    candidate.close.assert_awaited_once()
    with pytest.raises(LLMClientRetiredError):
        async with candidate.generation_lease():
            raise AssertionError("Rolled-back candidate admitted a generation")


@pytest_asyncio.fixture(autouse=True)
async def lane6_providers_cleanup():
    yield
    for bot in list(GRAPHS):
        await bot.requests.close()
        await bot.engine.close()
        bot.store.close()
        bot.authority.release_runtime()
        bot._directory.cleanup()
        GRAPHS.remove(bot)

load(globals())
