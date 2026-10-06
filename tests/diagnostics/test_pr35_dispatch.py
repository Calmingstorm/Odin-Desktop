"""Explicit diagnostic only: original foreign-owner goldens remain blocked.

Not a qualification selector. Run deliberately through the isolated runner.
"""
from tests.desktop_adapters import step8_review_helpers as adapter
from tests.test_desktop_step8_review_helpers import review_owner as review_owner

adapter.load(globals(), include_dispatch=True)
