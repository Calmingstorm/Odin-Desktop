"""Conversation-native tool dispatch (RFC-001 Phase 5).

One registry serves both pipelines (chat tool loop and autonomous loop),
replacing the two hand-synced if/elif chains. See registry.py.
"""

# Import domains explicitly. Package import never constructs a capability.
__all__: list[str] = []
