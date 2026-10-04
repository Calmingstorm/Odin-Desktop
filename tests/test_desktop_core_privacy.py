"""Neutral storage retains tool-specific privacy, not just token detection."""

import pytest

from src.storage_redaction import _scrub_tool_input_for_storage
from src.turn_state.codec import scrub_stored_tool_input


@pytest.mark.parametrize("name", ["computer_act", "computer_session", "computer_observe"])
def test_neutral_storage_scrubber_retains_computer_privacy(name):
    payload = {"session_id": "owned", "payload": {"text": "private document", "value": "opaque"}}
    clean = _scrub_tool_input_for_storage(name, payload)
    # The baseline checkpoint sensitive-key policy also masks session IDs.
    assert clean["session_id"] == "[redacted:sensitive-key]"
    assert clean["payload"]["text"] == "[private desktop content: 16 chars]"
    assert clean["payload"]["value"] == "[private desktop content: 6 chars]"
    assert payload["payload"]["text"] == "private document"


def test_neutral_storage_scrubber_retains_email_privacy():
    clean = _scrub_tool_input_for_storage(
        "email_send", {"body": "private", "attachments": ["/private/report.txt"]}
    )
    assert clean["body"] == "[redacted email body: 7 chars]"
    assert clean["attachments"] == ["report.txt"]


def test_checkpoint_composes_tool_privacy_and_sensitive_key_redaction():
    clean = scrub_stored_tool_input(
        "computer_act", {"text": "private", "nested": {"authorization": "opaque"}}
    )
    assert clean["text"] == "[private desktop content: 7 chars]"
    assert clean["nested"]["authorization"] == "[redacted:sensitive-key]"
