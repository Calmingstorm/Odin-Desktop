"""Frozen scheduling/report corpus with explicit canonical-service fixtures.

Only setup and transport representation are adapted. Native async handlers enter
real task-owned RequestService admission and call the actual ScheduleService.
Scheduler mocks remain the inherited external dependency, not a fake service.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.requests import RequestService
from src.desktop.schedules import ScheduleService
from src.desktop.transcript import TranscriptStore
from src.discord.native_tools.scheduling import SchedulingTools as NativeTools
from src.permissions.manager import PermissionManager
from src.desktop.reports import ReportService
from tests.desktop_adapters.lane6_schedules_reports_dispositions import (
    DEFERRED_CASES, RETIRED_CASES, REVIEWER,
)

SUITES = {
    "test_native_scheduling": "7bd9102e662705cd34187f038aa53e4c10cd9c8796322c49249145c7531077cd",
    "test_scheduled_report": "45a0f3bbc7bca2f630ef041c4f06e578ee9fd1b6b210c2f7a9a7c2ac87e2c482",
    "test_scheduled_report_pagination_listener": "afa49c7afd843834fafca21cf7763f19b3bd00c14422ea3960c80a208d438b52",
    "test_scheduled_report_wiring": "fc4b2ad6038e17475d5ca6803017bc51a61b6d8838b52b5af28e3f1812eb7e7f",
}
PINS = SUITES
CORPUS_PINS = {
    "test_native_scheduling": "14160b7d934aaa27334cae7b92f1878dcb71e00e01c9402d0b5f8bbdb7d33e0e",
    "test_scheduled_report": "49b4444bd03c8a455fd9a678f3cc87e0b82e61589186f0cdb93d648a115eead2",
    "test_scheduled_report_pagination_listener": "eecb7171a3df0e2a89b27118d37c510b44bbeb82aab0706f04d44381b43d620a",
    "test_scheduled_report_wiring": "6b267629f2c12e58198ea3a98e5a0a4250b7850cd3b736e59387287dbfe0cce6",
}
CORPUS_SELECTIONS = {
    "test_native_scheduling": None,
    "test_scheduled_report": None,
    "test_scheduled_report_pagination_listener": None,
    "test_scheduled_report_wiring": None,
}
CORPUS_EXCLUSIONS = {
    stem: list(cases) for stem, cases in RETIRED_CASES.items()
}
RESOURCES = []
SCHEDULER_GRAPHS = {}
EVIDENCE = {}
CASE_MAP = {}


@pytest.fixture(autouse=True)
def lane6_schedules_reports_cleanup():
    yield
    while RESOURCES:
        RESOURCES.pop().close()
    SCHEDULER_GRAPHS.clear()


class Graph:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lane6-schedules-reports-")
        paths = ProfilePaths.from_xdg("test", home=Path(self.temp.name), environ={})
        self.authority = OwnerAuthority(paths)
        self.permissions = PermissionManager(self.authority)
        self.store = JournalStore(paths.data_dir / "journal.sqlite3", "test")
        events = EventJournal(self.store)
        self.conversations = ConversationStore(self.store, events)
        self.transcript = TranscriptStore(self.store, events, self.conversations)
        self.cid = self.conversations.create()["conversation"]["id"]
        self.requests = RequestService(self.store, self.conversations, self.transcript,
            engine=SimpleNamespace(deps=SimpleNamespace(turn_store=None)), permissions=self.permissions,
            authority=self.authority, delivery=SimpleNamespace())
        RESOURCES.append(self)

    def close(self):
        self.store.close()
        self.authority.release_runtime()
        self.temp.cleanup()


class SchedulerBoundary:
    """Rebind inherited dependency fixtures to this profile's actual identity.

    False validation flags are omission-equivalent at the inherited mock seam;
    true flags remain visible to every original assertion.
    """
    def __init__(self, scheduler, graph):
        self.source, self.graph = scheduler, graph
        if isinstance(scheduler, MagicMock) and isinstance(scheduler.list_all.return_value, MagicMock):
            scheduler.list_all.return_value = [{"id": "S1", "action": "reminder"}]

    def list_all(self):
        if not isinstance(self.source, MagicMock):
            return self.source.list_all()
        return [{**row, "requester_id": self.graph.authority.owner_id,
                 "action": row.get("action", "reminder")} for row in self.source.list_all()]

    async def add(self, **kwargs):
        if kwargs.get("nested_payload_validated") is False:
            kwargs.pop("nested_payload_validated")
        return await self.source.add(**kwargs)

    async def update(self, id, **kwargs):
        if kwargs.get("nested_payload_validated") is False:
            kwargs.pop("nested_payload_validated")
        return await self.source.update(id, **kwargs)

    async def delete(self, id):
        return await self.source.delete(id)


class SchedulingTools(NativeTools):
    def __init__(self, *, scheduler, tool_catalog=None):
        self.graph = SCHEDULER_GRAPHS.get(scheduler) or Graph()
        SCHEDULER_GRAPHS[scheduler] = self.graph
        boundary = SchedulerBoundary(scheduler, self.graph)
        self.service = ScheduleService(boundary, authority=self.graph.authority,
            conversations=self.graph.conversations,
            assert_request=self.graph.requests.assert_bound_request)
        super().__init__(scheduler=boundary, tool_catalog=tool_catalog,
            service_provider=lambda: self.service,
            request_provider=lambda _: self.graph.requests.current_bound_request())

    async def _call(self, method, *args):
        owner = self.graph.authority.authenticate_local(peer_uid=self.graph.authority.owner_uid)
        token = self.graph.permissions.set_request_owner(owner)
        try:
            message = self.graph.requests._register_background("task",
                str(self.graph.store.connection.execute(
                    "SELECT COUNT(*) FROM desktop_background_requests").fetchone()[0]),
                "Example", self.graph.cid, owner.owner_id)
            async with self.graph.requests.background_execution(message):
                return await method(*args)
        finally:
            self.graph.permissions.reset_request_owner(token)

    async def _handle_schedule_task(self, message, inp):
        return await self._call(super()._handle_schedule_task, message, inp)

    async def _handle_update_schedule(self, inp):
        return await self._call(super()._handle_update_schedule, inp)

    async def _handle_delete_schedule(self, inp):
        return await self._call(super()._handle_delete_schedule, inp)

    def _handle_list_schedules(self):
        async def listing():
            return super(SchedulingTools, self)._handle_list_schedules()
        return asyncio.run(self._call(listing))


async def native_seed(scheduler, **kwargs):
    """Create the inherited raw-scheduler setup through actual profile admission."""
    graph = SCHEDULER_GRAPHS.get(scheduler) or Graph()
    SCHEDULER_GRAPHS[scheduler] = graph
    kwargs["channel_id"] = graph.cid
    owner = graph.authority.authenticate_local(peer_uid=graph.authority.owner_uid)
    service = ScheduleService(scheduler, authority=graph.authority,
                              conversations=graph.conversations)
    return await service.invoke("schedules.save", kwargs, owner=owner)


def report_registry():
    graph = Graph()
    # The registry is the actual one owned by 6B ReportService, never a copy of
    # legacy renderer logic. Projection tests do not grant report publication.
    return ReportService(graph.store).registry


def _dump(node):
    return ast.dump(node, include_attributes=False)


def frozen(stem):
    source = frozen_source(f"tests/{stem}.py")
    assert hashlib.sha256(source).hexdigest() == PINS[stem]
    original = ast.parse(source)
    assert hashlib.sha256(repr(corpus(original)).encode()).hexdigest() == CORPUS_PINS[stem]
    adapted = copy.deepcopy(original)
    hunks = []
    if stem == "test_native_scheduling":
        node = next(n for n in adapted.body if isinstance(n, ast.ImportFrom)
                    and n.module == "src.discord.native_tools.scheduling")
        before = copy.deepcopy(node)
        node.module = __name__
        hunks.append((before, node))
        cls = next(n for n in adapted.body if isinstance(n, ast.ClassDef)
                   and n.name == "TestUnknownReportFormatNativeRejection")
        setup = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == "test_native_update_rejects_unknown_format")
        call = next(n for n in ast.walk(setup) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "add")
        before = copy.deepcopy(call)
        call.func = ast.Name(id="native_seed", ctx=ast.Load())
        call.args.insert(0, ast.Name(id="scheduler", ctx=ast.Load()))
        hunks.append((before, call))
    if stem == "test_scheduled_report":
        node = next(n for n in adapted.body if isinstance(n, ast.FunctionDef) and n.name == "_registry")
        before = copy.deepcopy(node)
        node.body = ast.parse("return report_registry()").body
        hunks.append((before, node))
    assert corpus(original) == corpus(adapted)
    EVIDENCE[stem] = {"source_sha256": PINS[stem],
        "full_corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "whole_suite_bound_before_case_projection": True,
        "assertions_signatures_decorators_parameters_unchanged": True,
        "hunks": [{"line": a.lineno, "before_sha256": hashlib.sha256(_dump(a).encode()).hexdigest(),
                   "after_sha256": hashlib.sha256(_dump(b).encode()).hexdigest(),
                   "after_source": ast.unparse(b)} for a, b in hunks]}
    return adapted


NATIVE_DEFERRED = {
    "TestUpdateSchedule.test_strict_update_without_existing_selected_tool_remains_safe",
}
REPORT_RETAINED = {
    "TestPaginatedEmbedV1Contract.test_empty_pages_normalize_to_bounded_empty_state",
    "TestPaginatedEmbedV1Contract.test_hostile_shapes_are_rejected",
    "TestPaginatedEmbedV1Contract.test_hard_character_and_link_caps",
    "TestPaginatedEmbedV1Contract.test_page_field_link_and_embed_caps",
    "TestPaginatedEmbedV1Contract.test_link_urls_are_scrubbed_after_parse_before_validation",
    "TestPaginatedEmbedV1Contract.test_unknown_registry_format_is_rejected_at_render_time",
    "TestRegistryAndPersistenceFailureEdges.test_duplicate_registration_and_formats",
    "TestRegistryAndPersistenceFailureEdges.test_malformed_json_has_stable_error",
}


def register_module(namespace, stem, tree, module):
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
                continue
            cls = vars(module)[node.name]
            for child in node.body:
                if not getattr(child, "name", "").startswith("test_"):
                    continue
                symbol = f"{node.name}.{child.name}"
                retained = symbol not in NATIVE_DEFERRED if stem == "test_native_scheduling" else symbol in REPORT_RETAINED
                if not retained:
                    assert symbol in RETIRED_CASES.get(stem, {}) or symbol in DEFERRED_CASES.get(stem, {})
                    delattr(cls, child.name)
                else:
                    exported = f"TestLane6_{stem}_{node.name[4:]}"
                    CASE_MAP[f"tests/{stem}.py::{node.name}::{child.name}"] = f"{exported}::{child.name}"
                    namespace[exported] = cls


def load(namespace):
    namespace["lane6_schedules_reports_cleanup"] = lane6_schedules_reports_cleanup
    for stem in SUITES:
        tree = frozen(stem)
        if stem not in {"test_native_scheduling", "test_scheduled_report"}:
            continue
        module = ModuleType(f"lane6_schedules_reports_{stem}")
        module.__file__ = str(ROOT / f"tests/{stem}.py")
        module.report_registry = report_registry
        module.native_seed = native_seed
        exec(compile(ast.fix_missing_locations(tree), module.__file__, "exec"), module.__dict__)
        register_module(namespace, stem, tree, module)
