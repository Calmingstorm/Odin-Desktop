"""Explicit diagnostic only: deferred frozen admission cases, not qualification."""
import pytest_asyncio

from tests.desktop_adapters.step8_review_resume import load, owner_fixture


@pytest_asyncio.fixture(autouse=True)
async def authenticated_owner(tmp_path):
    async for state in owner_fixture(tmp_path):
        yield state


load(globals())
