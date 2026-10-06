"""Deliberate exact dispatcher retry, still blocked by foreign identity goldens."""
from tests.desktop_adapters import step8_review_dispatch as adapter
from tests.test_desktop_step8_review_dispatch import authentic_owner as authentic_owner

adapter.load(globals())
