"""Empty unbackfilled writer evidence must not fabricate known zero usage."""
from __future__ import annotations

import pytest

from tests.test_desktop_runtime import make_rollup, make_service


@pytest.mark.asyncio
async def test_real_fresh_rollup_empty_index_is_unknown_until_backfill_complete(tmp_path):
    service = make_service(tmp_path)
    rollup = make_rollup(service)
    try:
        unknown = await service.handle("usage.get", {"period": "all"})
        assert unknown["tokens"] == {"value": None, "kind": "unknown"}
        rollup._set_backfill_state(True)
        measured = await service.handle("usage.get", {"period": "all"})
        assert measured["tokens"] == {"value": 0, "kind": "measured"}
    finally:
        await rollup.stop()
