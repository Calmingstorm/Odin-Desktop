"""Durable bound report snapshots. Reading never executes a producer.

Reuse the step-3 report table, with a versioned envelope in its pages column.
Legacy page lists remain readable but never gain fabricated run authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from ..discord.scheduled_report import (
    MAX_PAGES,
    PaginatedEmbedV1Renderer,
    ScheduledReportRendererRegistry,
)
from ..llm.secret_scrubber import scrub_output_secrets
from .artifacts import ResultReadError
from .commands import canonical_json

MAX_PAGE_BYTES = 32768
MAX_REPORT_BYTES = 262144
MAX_ID_CHARS = 256
ERROR_TEXT = "Report rendering failed. The check was not run again."
UNAVAILABLE_TEXT = "Stored report is unavailable. The check was not run again."


@dataclass(frozen=True, slots=True)
class ReportBinding:
    owner_id: str
    conversation_id: str
    request_id: str
    run_id: str
    generation: int
    producer_id: str


def _id(value):
    if (type(value) is not str or not 1 <= len(value) <= MAX_ID_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ResultReadError("bad_request", "Expected a bounded report identity")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ResultReadError("bad_request", "Expected a valid report identity") from None
    return value


def _binding_shape(binding):
    if not isinstance(binding, ReportBinding):
        raise ResultReadError("unauthorized", "Admitted report binding required")
    for key, value in asdict(binding).items():
        if key != "generation":
            _id(value)
    if type(binding.generation) is not int or binding.generation < 1:
        raise ResultReadError("bad_request", "Expected a positive run generation")


def _pages(pages):
    if type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES:
        raise ResultReadError("bad_request", "Expected bounded stored report pages")
    result, total = [], 0
    for text in pages:
        if type(text) is not str:
            raise ResultReadError("bad_request", "Expected report text")
        # Bound input before regex redaction as well as final UTF-8 output.
        if len(text) > MAX_PAGE_BYTES:
            raise ResultReadError("bad_request", "Stored report exceeds its byte limit")
        text = scrub_output_secrets(text)
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError:
            raise ResultReadError("bad_request", "Expected valid report text") from None
        total += size
        if size > MAX_PAGE_BYTES or total > MAX_REPORT_BYTES:
            raise ResultReadError("bad_request", "Stored report exceeds its byte limit")
        result.append(text)
    return result


class ReportService:
    """Publish once, then read saved pages under current tool/host/owner policy.

    assert_binding is the real work owner's validator, not renderer authority.
    Historical reads do not require a still-running job. No execution callback
    exists on this service. Publication joins the journal transaction.
    """

    def __init__(self, store, *, authorize=None, assert_binding=None,
                 events=None, registry=None):
        self.store, self.authorize = store, authorize
        self.assert_binding, self.events = assert_binding, events
        if events is not None and events.store is not store:
            raise ValueError("Reports and events must share durable storage")
        self.registry = registry or ScheduledReportRendererRegistry()
        if registry is None:
            self.registry.register(PaginatedEmbedV1Renderer())
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_reports (
                report_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                conversation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                pages TEXT NOT NULL, tool TEXT NOT NULL, hosts TEXT NOT NULL)""")

    def _binding(self, binding):
        _binding_shape(binding)
        if self.assert_binding is None:
            raise ResultReadError("unauthorized", "Report admission is unavailable")
        try:
            accepted = self.assert_binding(binding)
        except Exception:
            raise ResultReadError("unauthorized", "Report run binding is not authorized") from None
        if accepted is False:
            raise ResultReadError("unauthorized", "Report run binding is not authorized")

    def _allowed(self, tool, hosts, owner):
        try:
            allowed = self.authorize is not None and self.authorize(tool, hosts, owner)
        except Exception:
            raise ResultReadError("unavailable", "Report authorization is unavailable") from None
        if not allowed:
            raise ResultReadError("unauthorized", "Originating report scope is not authorized")

    @staticmethod
    def identity(binding):
        return "report_" + hashlib.sha256(canonical_json(asdict(binding)).encode()).hexdigest()

    @staticmethod
    def _descriptor(report_id, envelope):
        return {"report_id": report_id, "pages": len(envelope["pages"]),
                "status": envelope["status"], "revision": 1,
                "size": sum(len(page.encode("utf-8")) for page in envelope["pages"]),
                "available": envelope["status"] != "unavailable"}

    def publish(self, pages, *, binding, tool, hosts=(), report_id=None,
                status="available"):
        self._binding(binding)
        _id(tool)
        if type(hosts) not in (list, tuple) or len(hosts) > 64:
            raise ResultReadError("bad_request", "Expected bounded report hosts")
        hosts = tuple(_id(host) for host in hosts)
        self._allowed(tool, hosts, binding.owner_id)
        if status not in ("available", "error", "unavailable"):
            raise ResultReadError("bad_request", "Invalid stored report status")
        pages = _pages([UNAVAILABLE_TEXT] if status == "unavailable" else pages)
        report_id = _id(report_id) if report_id is not None else self.identity(binding)
        envelope = {"version": 1, "binding": asdict(binding), "status": status, "pages": pages}
        values = (report_id, binding.owner_id, binding.conversation_id, binding.request_id,
                  canonical_json(envelope), tool, canonical_json(list(hosts)))
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM desktop_reports WHERE report_id=?",
                             (report_id,)).fetchone()
            if row is not None:
                if tuple(row) != values:
                    raise ResultReadError("id_conflict", "Report identity is already bound")
                return self._descriptor(report_id, envelope)
            db.execute("INSERT INTO desktop_reports VALUES (?,?,?,?,?,?,?)", values)
            descriptor = self._descriptor(report_id, envelope)
            if self.events is not None:
                self.events.append("report.published", {"kind": "report", "id": report_id},
                    {"conversation_id": binding.conversation_id,
                     "request_id": binding.request_id, "run_id": binding.run_id,
                     "generation": binding.generation, "producer_id": binding.producer_id,
                     "report": descriptor})
            return descriptor

    def publish_output(self, raw_output, *, report_format, binding, tool,
                       hosts=(), report_id=None):
        """Rendering failures persist generic error pages, not rejected JSON.

        This trusted producer seam accepts stored check output. It does not
        imply success of the check or permission to retry it.
        """
        status = "available"
        try:
            if type(raw_output) is not str or len(raw_output.encode()) > MAX_REPORT_BYTES:
                raise ValueError()
            projection = self.registry.project(report_format, raw_output)
            pages = []
            for page in projection["pages"]:
                lines = [page["title"], page["description"]]
                lines.extend(f"{field['name']}: {field['value']}" for field in page["fields"])
                lines.extend(f"{link['label']}: {link['url']}" for link in page["links"])
                lines.append(page["footer"])
                pages.append("\n".join(line for line in lines if line))
            pages = _pages(pages)
        except Exception:
            pages, status = [ERROR_TEXT], "error"
        return self.publish(pages, binding=binding, tool=tool, hosts=hosts,
                            report_id=report_id, status=status)

    def page(self, report_id, page, *, owner, conversation_id=None):
        _id(report_id)
        if type(page) is not int or page < 1:
            raise ResultReadError("bad_request", "Expected a positive report page")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM desktop_reports WHERE report_id=?",
                             (report_id,)).fetchone()
            if (row is None or row["owner"] != owner or (conversation_id is not None
                    and row["conversation_id"] != conversation_id)):
                raise ResultReadError("not_found", "Report is unavailable")
            try:
                hosts = json.loads(row["hosts"])
                if type(hosts) is not list or len(hosts) > 64:
                    raise ValueError()
                hosts = tuple(_id(host) for host in hosts)
                _id(row["tool"])
            except Exception:
                raise ResultReadError("unavailable", UNAVAILABLE_TEXT) from None
            self._allowed(row["tool"], hosts, owner)
            try:
                saved = json.loads(row["pages"])
                if type(saved) is list:
                    pages = _pages(saved)
                else:
                    if (type(saved) is not dict or set(saved) !=
                            {"version", "binding", "status", "pages"}
                            or type(saved["version"]) is not int or saved["version"] != 1
                            or saved["status"] not in ("available", "error", "unavailable")):
                        raise ValueError()
                    binding = ReportBinding(**saved["binding"])
                    _binding_shape(binding)
                    if (binding.owner_id != row["owner"]
                            or binding.conversation_id != row["conversation_id"]
                            or binding.request_id != row["request_id"]):
                        raise ValueError()
                    pages = _pages(saved["pages"])
                    if saved["status"] == "unavailable":
                        raise ValueError()
            except Exception:
                raise ResultReadError("unavailable", UNAVAILABLE_TEXT) from None
            if page > len(pages):
                raise ResultReadError("bad_request", "Invalid report page")
            return {"page": page, "pages": len(pages), "text": pages[page - 1]}

    def handle(self, method, params, *, owner):
        if method != "reports.page":
            raise ResultReadError("bad_request", "Unknown report operation")
        if type(params) is not dict or set(params) != {"report_id", "page"}:
            raise ResultReadError("bad_request", "Expected report_id and page")
        return self.page(params["report_id"], params["page"], owner=owner)

    def delete_conversation(self, conversation_id):
        with self.store.transaction() as db:
            db.execute("DELETE FROM desktop_reports WHERE conversation_id=?", (conversation_id,))


class ReportDelivery:
    """Atomic report/notice/notification/outbox publication without a window.

    The work owner validates the immutable binding, not foreground liveness.
    Reconnect repairs DurableDelivery's outbox and never reruns a check.
    """

    def __init__(self, reports, delivery):
        if reports.store is not delivery.store or reports.events is not delivery.events:
            raise ValueError("Report delivery must share publication storage and events")
        self.reports, self.delivery = reports, delivery

    async def publish_output(self, raw_output, *, report_format, binding, tool,
                             hosts=(), report_id=None, name="Scheduled report"):
        return await self._publish("publish_output", raw_output, report_format=report_format,
            binding=binding, tool=tool, hosts=hosts, report_id=report_id, name=name)

    async def publish(self, pages, *, binding, tool, hosts=(), report_id=None,
                      status="available", name="Stored report"):
        return await self._publish("publish", pages, binding=binding, tool=tool,
            hosts=hosts, report_id=report_id, status=status, name=name)

    async def _publish(self, method, content, *, binding, name, **kwargs):
        if type(name) is not str:
            raise ResultReadError("bad_request", "Expected report display name")
        name = scrub_output_secrets(name)
        if len(name.encode("utf-8")) > 1024:
            raise ResultReadError("bad_request", "Report display name exceeds its limit")
        delivery = self.delivery
        with self.reports.store.transaction(), delivery._capture() as frames:
            descriptor = getattr(self.reports, method)(content, binding=binding, **kwargs)
            rid = descriptor["report_id"]
            text = {"available": "Stored report", "error": ERROR_TEXT,
                    "unavailable": UNAVAILABLE_TEXT}[descriptor["status"]]
            artifact = {"ref": rid, "name": name, "mime": "text/plain",
                        "size": descriptor["size"], "kind": "report",
                        "available": descriptor["available"]}
            from .delivery import RequestContext

            has_requests = delivery.store.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='desktop_requests'").fetchone()
            request = (delivery.store.connection.execute(
                "SELECT message_id FROM desktop_requests WHERE request_id=?",
                (binding.request_id,)).fetchone() if has_requests else None)
            context = RequestContext(binding.conversation_id, binding.request_id,
                                     binding.generation, binding.owner_id,
                                     request[0] if request is not None else None)
            staged = delivery.consume_staged(context)
            message = delivery.transcript_commit(conversation_id=binding.conversation_id,
                role="notice", text=text, request_id=binding.request_id,
                id="report_message_" + rid, artifacts=[artifact, *staged])
            delivery.notifications.intent(conversation_id=binding.conversation_id,
                message_id=message["id"], category="report", preview=text,
                dedupe_key="report:" + rid, request_id=binding.request_id)
            for frame in frames:
                delivery._enqueue_bound(binding.conversation_id, binding.request_id,
                                        frame, f"event:{frame['seq']}")
        await delivery.drain()
        return descriptor
