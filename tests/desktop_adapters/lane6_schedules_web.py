"""Socket-free frozen scheduling fixtures through the genuine 6B owner.

No removed HTTP registrar or copied scheduler algorithm is executed.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, frozen_source, nodes
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.events import EventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.schedules import ScheduleService

PATH = "tests/test_web_api_schedules.py"
SOURCE_HASHES = {
    PATH: "e05b80b887ea8ef3ba04cd6bd0f7d519ffa37c853bc4fabf108cf8ff3021788d"
}
SUITES = {
    "test_web_api_schedules": "e05b80b887ea8ef3ba04cd6bd0f7d519ffa37c853bc4fabf108cf8ff3021788d"
}
CORPUS_SELECTIONS = {"test_web_api_schedules": None}
CORPUS_EXCLUSIONS = {}
RETIRED_CASES = {}
DEFERRED_CASES = {"test_web_api_schedules": {
    "TestListCreate.test_create_webhook_without_discord_channel": (
        "Retained outgoing webhook lacks a conversation destination; ScheduleService "
        "requires one for durable run binding. Needs owner-bound external destination design."
    ),
    "TestWebhookApiParity.test_disconnected_create_update_and_run_without_channel": (
        "Retained webhook without conversation cannot meet canonical requester/conversation "
        "run binding; requires external-destination design."
    ),
}}
SELECTED = {
    "TestListCreate.test_create_validation",
    "TestUpdate.test_validation",
    "TestHistoryStats.test_history_and_stats",
    "TestReportFormatApiParity.test_create_update_and_readback",
    "TestReportFormatApiParity.test_invalid_type_and_non_check_use_return_400",
    "TestReportFormatApiParity.test_unknown_format_is_400_on_create_and_update",
    "TestDeleteRunReset.test_delete",
    "TestListCreate.test_list",
    "TestListCreate.test_create_success_and_error",
    "TestUpdate.test_not_found_error_and_success",
    "TestUpdate.test_update_passes_webhook_config",
    "TestDeleteRunReset.test_run_now",
    "TestDeleteRunReset.test_reset_failures",
    "TestValidateCron.test_validate_cron",
    "TestCronPreviewClock.test_next_runs_carry_an_explicit_utc_offset",
    "TestCronPreviewClock.test_preview_agrees_with_the_schedulers_own_computation",
    "TestCronTimezoneApiParity.test_create_update_and_readback",
    "TestCronTimezoneApiParity.test_invalid_timezone_is_a_400_on_create_and_update",
}
CASE_MAP = {}
SETUP_HUNKS = {}
EVIDENCE = []


class Application:
    def __init__(self):
        self.router, self.routes = self, []

    def add_routes(self, routes):
        self.routes.extend(routes)


web = SimpleNamespace(RouteTableDef=list, Application=Application)


def register_schedules(routes, bot):
    routes.append(bot)


class Response:
    def __init__(self, value, status=200):
        self.status, self.value = status, json.dumps(value, allow_nan=False)

    async def json(self):
        return json.loads(self.value)


class TestServer:
    __test__ = False

    def __init__(self, app):
        self.app = app


class TestClient:
    __test__ = False

    def __init__(self, server):
        self.server = server

    async def __aenter__(self):
        self.temp = TemporaryDirectory(prefix="lane6_schedules_web_")
        self.paths = ProfilePaths.from_xdg("fixture", home=Path(self.temp.name), environ={})
        self.authority = OwnerAuthority(self.paths)
        self.owner = self.authority.authenticate_local(peer_uid=self.authority.owner_uid)
        self.store = JournalStore(self.paths.data_dir / "journal.sqlite3", "fixture")
        self.conversations = ConversationStore(self.store, EventJournal(self.store))
        self.cid = self.conversations.create()["conversation"]["id"]
        self.service = ScheduleService(
            self.server.app.routes[0].scheduler,
            authority=self.authority,
            conversations=self.conversations,
        )
        # Only external frozen mock definitions need their setup identity bound.
        # Genuine Scheduler records are always created by ScheduleService.
        from unittest.mock import Mock
        scheduler = self.service.scheduler
        if isinstance(scheduler, Mock):
            scheduler.list_all.return_value = [dict(item, requester_id=self.owner.owner_id)
                                              for item in scheduler.list_all.return_value]
            if isinstance(scheduler.history.query.return_value, list):
                scheduler.history.query.return_value = [
                    dict(item, run_binding={"owner_id": self.owner.owner_id})
                    for item in scheduler.history.query.return_value
                ]
        return self

    async def __aexit__(self, *args):
        self.store.close()
        self.authority.release_runtime()
        self.temp.cleanup()

    async def get(self, path, **kwargs):
        return await self.request("GET", path, **kwargs)

    async def post(self, path, **kwargs):
        return await self.request("POST", path, **kwargs)

    async def put(self, path, **kwargs):
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path, **kwargs):
        return await self.request("DELETE", path, **kwargs)

    async def request(self, verb, path, *, json=None, data=None):
        if data is not None:
            return Response({"error": "invalid JSON"}, 400)
        params = dict(json or {})
        from urllib.parse import parse_qsl, urlsplit
        url = urlsplit(path)
        path = url.path
        if path.endswith("/history"):
            method = "schedules.history"
            params = dict(parse_qsl(url.query))
            params.pop("status", None)
            if "limit" in params:
                params["limit"] = int(params["limit"])
            if path != "/api/schedules/history":
                params["id"] = path.split("/")[-2]
        elif path.endswith("/stats"):
            method = "schedules.stats"
            params = {"id": path.split("/")[-2]}
        elif path.endswith("validate-cron"):
            if not params.get("expression"):
                return Response({"error": "expression required"}, 400)
            method = "schedules.validate_cron"
        elif path.endswith("/run"):
            method = "schedules.run"
            params["id"] = path.split("/")[-2]
        elif path.endswith("/reset-failures"):
            method = "schedules.reset_failures"
            params["id"] = path.split("/")[-2]
        elif verb == "DELETE":
            method = "schedules.delete"
            params["id"] = path.rsplit("/", 1)[1]
        elif verb == "GET":
            method = "schedules.list"
        else:
            method = "schedules.save"
            if verb == "PUT":
                params["id"] = path.rsplit("/", 1)[1]
            if "channel_id" in params:
                if params["channel_id"] != "1":
                    raise ValueError("Unadmitted fixture destination")
                params["channel_id"] = self.cid
        try:
            result = await self.service.invoke(method, params, owner=self.owner)
            EVIDENCE.append((method, self.owner.owner_id))
            if result is None:
                return Response({"error": "not found"}, 404)
            return Response(result, 201 if verb == "POST" and method == "schedules.save" else 200)
        except (ValueError, TypeError) as exc:
            status = 400
            if method == "schedules.run":
                status = 404 if "not found" in str(exc) else 503
            return Response({"error": str(exc)}, status)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, 500)


def transformed_tree():
    source = frozen_source(PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_HASHES[PATH]
    original = ast.parse(source)
    tree = copy.deepcopy(original)
    hunks = []
    for symbol, node in nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "aiohttp", "aiohttp.test_utils", "src.web.api.schedules_api"
        }:
            before = ast.dump(node)
            node.module = __name__
            after = ast.dump(node)
            hunks.append({"symbol": symbol, "line": node.lineno,
                "operation": "lane6_schedules_socket_free_owner_import", "kind": "statement",
                "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                "after_sha256": hashlib.sha256(json.dumps([after]).encode()).hexdigest(),
                "after_source": ast.unparse(node)})
    assert corpus(original) == corpus(tree)
    expected = copy.deepcopy(original)
    for hunk in hunks:
        matches = [n for symbol, n in nodes(expected) if symbol == hunk["symbol"]
                   and getattr(n, "lineno", None) == hunk["line"]
                   and hashlib.sha256(ast.dump(n).encode()).hexdigest() == hunk["before_sha256"]]
        assert len(matches) == 1
        assert isinstance(matches[0], ast.ImportFrom)
        matches[0].module = __name__
        assert (
            hashlib.sha256(json.dumps([ast.dump(matches[0])]).encode()).hexdigest()
            == hunk["after_sha256"]
        )
    assert ast.dump(expected) == ast.dump(tree)
    SETUP_HUNKS[PATH] = hunks
    return ast.fix_missing_locations(tree)


def load(namespace):
    module = ModuleType("lane6_schedules_web_frozen")
    module.__file__ = str(Path(__file__).parents[2] / PATH)
    tree = transformed_tree()
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    register_module(namespace, "test_web_api_schedules", module)


def register_module(namespace, suite, module):
    tree = transformed_tree()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        cls = getattr(module, node.name)
        for method in list(vars(cls)):
            if method.startswith("test_") and f"{node.name}.{method}" not in SELECTED:
                delattr(cls, method)
        if not any(name.startswith("test_") for name in vars(cls)):
            continue
        exported = "TestLane6SchedulesWeb_" + node.name[4:]
        cls.__module__ = namespace["__name__"]
        namespace[exported] = cls
        for method in vars(cls):
            if method.startswith("test_"):
                CASE_MAP[f"{PATH}::{node.name}::{method}"] = f"{exported}::{method}"
