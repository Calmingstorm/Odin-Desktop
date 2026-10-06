"""Explicit storage schemas for the composed Desktop domains.

An older transport-only journal is a supported upgrade. Unknown tables and
changed columns are not silently adopted as a different profile's data.
"""
from __future__ import annotations

DOMAIN_COLUMNS = {
    "desktop_conversations": {"id", "record", "context_position", "read_position"},
    "desktop_messages": {"position", "message_id", "conversation_id", "role", "text",
                         "created_at", "record"},
    "desktop_inheritance": {"conversation_id", "ordinal", "record"},
}


def validate_domains(connection, tables: set[str], transport_tables: set[str]) -> bool:
    if not transport_tables <= tables or tables - transport_tables - DOMAIN_COLUMNS.keys():
        return False
    for table in tables - transport_tables:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if columns != DOMAIN_COLUMNS[table]:
            return False
    return True
