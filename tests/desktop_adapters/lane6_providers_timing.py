"""Generation submethod fixtures on the real Desktop runner, no typing transport."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.discord.response_guards import StuckLoopTracker
from src.discord.tool_loop import CHAT_POLICY, _ChatTurn
from src.turn_state.durability import TurnDurability
from tests.desktop_adapters.lane6_providers_engine import build


class FakeChannel:
    id = "c1"


def _make_runner(recorder_save=None):
    bot, _ = build([])
    return bot.tool_loop, [], []


def _stub_state(channel=None):
    return _ChatTurn(
        policy=CHAT_POLICY, _result_store_cap=2000, chat_cap=3, iteration=0,
        stuck_tracker=StuckLoopTracker(), wait_judgment_pending=False,
        _cancel=asyncio.Event(),
        _trajectory=SimpleNamespace(source="desktop", channel_id="c1", message_id="r1"),
        trace=None, _ch_id="c1", _req_id="r1",
        message=SimpleNamespace(channel=channel or FakeChannel(), content="hi"),
        messages=[], tools_used_in_loop=[], _boundary_request_start=0,
        _boundary_elided_replay=0, _boundary_envelope_len=0, _char_latch=None,
        _rescue_passes=0, _gen_identity=None, system_prompt="sys", tools=[],
        user_id="submethod-fixture", durability=TurnDurability.disabled())
