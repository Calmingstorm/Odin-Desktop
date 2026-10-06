"""Explicit storage schemas for the composed Desktop domains.

An older transport-only journal is a supported upgrade. Unknown tables and
changed columns are not silently adopted as a different profile's data.
"""
from __future__ import annotations

DOMAIN_COLUMNS = {
    "desktop_webhook_receipts": {"id", "schedule_id", "destination", "source",
                                 "schedule_binding", "state", "run_binding", "text", "published"},
    "desktop_controls": {"control_command_id", "binding", "conversation_id", "request_id",
                         "generation", "kind", "disposition", "sequence", "response", "created_at"},
    "desktop_conversations": {"id", "record", "context_position", "read_position"},
    "desktop_messages": {"position", "message_id", "conversation_id", "role", "text",
                         "created_at", "record"},
    "desktop_inheritance": {"conversation_id", "ordinal", "record"},
    "desktop_request_context": {"request_id", "conversation_id", "context_position"},
}

# Keep the storage validator independent of service imports: commands imports
# this module before any domain owner exists. Exact columns permit upgrades
# from transport-only profiles without adopting an unrelated database.
DOMAIN_COLUMNS.update({
    "desktop_requests": {"request_id", "conversation_id", "message_id", "owner", "generation",
                         "state", "text", "attachments", "created_at", "started_at", "ended_at",
                         "unknown_effects", "ledger_generation"},
    "desktop_submissions": {"client_submission_id", "binding", "response"},
    "desktop_background_requests": {"request_id", "kind", "run_id", "parent_request_id",
                                    "binding"},
    "desktop_work": {"kind", "id", "manager_generation", "record"},
    "desktop_delivery_outbox": {"delivery_id", "conversation_id", "request_id", "kind",
                                "payload", "event_seq", "state", "created_at", "delivered_at"},
    "desktop_notifications": {"dedupe_key", "conversation_id", "request_id", "payload",
                              "outcome", "created_at", "acked_at"},
    "desktop_uploads": {"upload_id", "client_attachment_id", "conversation_id", "binding",
                        "name", "mime", "size", "received", "state", "sha256", "ref", "expires_at"},
    "desktop_upload_chunks": {"upload_id", "offset", "data"},
    "desktop_attachment_adoptions": {"ref", "request_id", "message_id", "add_to_knowledge"},
    "desktop_artifacts": {"ref", "owner", "conversation_id", "request_id", "name", "mime",
                          "size", "kind", "sha256", "tool", "hosts", "data", "source_cursor",
                          "expires_at"},
    "desktop_reports": {"report_id", "owner", "conversation_id", "request_id", "pages",
                        "tool", "hosts"},
    "desktop_tool_details": {"request_id", "invocation_id", "owner", "conversation_id", "tool",
                             "target", "arguments", "previews", "cursor", "attachment_cursor",
                             "hosts"},
})


def validate_domains(connection, tables: set[str], transport_tables: set[str]) -> bool:
    if not transport_tables <= tables or tables - transport_tables - DOMAIN_COLUMNS.keys():
        return False
    for table in tables - transport_tables:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if columns != DOMAIN_COLUMNS[table]:
            return False
    return True
