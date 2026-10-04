"""Phase 1 has no legacy uncheckpointed fresh-effect escape hatch."""

import pytest

from src.turn_state.durability import TurnDurability


@pytest.mark.asyncio
@pytest.mark.parametrize("store", [None, object()])
async def test_unwired_admission_is_blocked_even_without_store(store):
    handle = await TurnDurability.admit(
        store, message=object(), system_prompt="prompt", tools=[], session_snapshot=None
    )
    assert handle.blocked == "admission_error"
