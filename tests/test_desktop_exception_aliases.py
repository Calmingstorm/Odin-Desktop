"""Legacy exception imports retain identity after adopting Error-suffixed names."""

import pickle

import pytest

from src.discord.tool_loop import Phase2WiringRequired, Phase2WiringRequiredError
from src.discord.turn_resume import (
    ConversationAccessDenied,
    ConversationAccessDeniedError,
    ConversationFetchUnavailable,
    ConversationFetchUnavailableError,
    ConversationMessageNotFound,
    ConversationMessageNotFoundError,
)
from src.web.api import Phase2Unavailable, Phase2UnavailableError


@pytest.mark.parametrize(
    ("legacy", "canonical", "base"),
    [
        (Phase2Unavailable, Phase2UnavailableError, RuntimeError),
        (Phase2WiringRequired, Phase2WiringRequiredError, RuntimeError),
        (ConversationMessageNotFound, ConversationMessageNotFoundError, LookupError),
        (ConversationAccessDenied, ConversationAccessDeniedError, PermissionError),
        (ConversationFetchUnavailable, ConversationFetchUnavailableError, OSError),
    ],
)
def test_legacy_exception_alias_preserves_identity_and_catches(legacy, canonical, base):
    assert legacy is canonical
    assert issubclass(canonical, base)
    assert canonical.__name__.endswith("Error")
    with pytest.raises(legacy, match="compatibility"):
        raise canonical("compatibility")
    with pytest.raises(canonical, match="compatibility"):
        raise legacy("compatibility")
    restored = pickle.loads(pickle.dumps(legacy("compatibility")))
    assert type(restored) is canonical
    assert restored.args == ("compatibility",)
