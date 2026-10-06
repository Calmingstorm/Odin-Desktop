"""Sealed historical policy proof, never a desktop service or owner admission.

The unchanged tier assertions can only mean the pinned tier policy, not the
single-owner desktop. Run its actual implementation in disposable tests. Named
Records methods supply tail reads; old transports are test-only sinks.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import sys
import tarfile
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pydantic import BaseModel, Field, field_validator

from scripts.maintenance.fixture_corpus import ARCHIVE_SHA256, ROOT
from src.desktop import records

_ARCHIVE = (ROOT / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
assert hashlib.sha256(_ARCHIVE).hexdigest() == ARCHIVE_SHA256


def _source(path):
    with tarfile.open(fileobj=io.BytesIO(_ARCHIVE), mode="r:gz") as archive:
        members = [member for member in archive if member.name == path]
        assert len(members) == 1 and members[0].isfile()
        return archive.extractfile(members[0]).read()


_schema = ast.parse(_source("src/config/schema.py"))
_classes = [node for node in _schema.body if isinstance(node, ast.ClassDef)
            and node.name in {"ApiTokenIdentity", "WebConfig", "WebhookConfig"}]
for _class in _classes:
    for _node in ast.walk(_class):
        if isinstance(_node, ast.ImportFrom) and _node.module == "web.authentication":
            _node.module, _node.level = "src.web.authentication", 0
_schema_namespace = {"BaseModel": BaseModel, "Field": Field,
                     "field_validator": field_validator}
exec(compile(ast.Module(body=_classes, type_ignores=[]), "frozen-policy-schema", "exec"),
     _schema_namespace)
ApiTokenIdentity = _schema_namespace["ApiTokenIdentity"]
WebConfig = _schema_namespace["WebConfig"]
WebhookConfig = _schema_namespace["WebhookConfig"]
WebConfig.model_rebuild(_types_namespace=_schema_namespace)

_TARGETS = {
    "src.web.authentication", "src.web.session_store", "src.health.server",
    "src.web.websocket", "src.web.api_common", "src.web.api.security",
}
_MODULES = {}


class _Imports(ast.NodeTransformer):
    def __init__(self, source_name):
        self.package = source_name.rsplit(".", 1)[0]

    def visit_ImportFrom(self, node):
        import importlib.util
        original = importlib.util.resolve_name("." * node.level + (node.module or ""),
                                               self.package) if node.level else node.module
        if original == "src.config.schema":
            retained = [item for item in node.names if item.name not in {
                "ApiTokenIdentity", "WebConfig", "WebhookConfig"}]
            swapped = [item for item in node.names if item not in retained]
            result = []
            if retained:
                result.append(ast.copy_location(ast.ImportFrom(original, retained, 0), node))
            if swapped:
                result.append(ast.copy_location(ast.ImportFrom(__name__, swapped, 0), node))
            return result
        if original in _TARGETS:
            loaded = _load(original)
            original = loaded.__name__
        node.module, node.level = original, 0
        return node


def _load(name):
    if name in _MODULES:
        return _MODULES[name]
    module = ModuleType(__name__ + "_" + name.replace(".", "_"))
    module.__file__ = str(ROOT / "maintenance" / (name.replace(".", "/") + ".py"))
    _MODULES[name] = module
    sys.modules[module.__name__] = module
    tree = ast.parse(_source(name.replace(".", "/") + ".py"))
    if name == "src.web.websocket":
        # Unused web-chat import stays explicitly unavailable; no chat shim.
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.ImportFrom) and node.module == "chat")]
        module.MAX_CHAT_CONTENT_LEN = 32000
        async def unavailable_chat(*args, **kwargs):
            raise RuntimeError("Historical policy fixture cannot admit chat")
        module.process_web_chat = unavailable_chat
    tree = ast.fix_missing_locations(_Imports(name).visit(tree))
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    return module


websocket = _load("src.web.websocket")
_health = _load("src.health.server")
_security = _load("src.web.api.security")

# Low-level tail assertions now test the actual desktop algorithms, not the
# frozen transport's own duplicate reader. Public named methods are separately
# exercised in method tests and each transport read is routed through them.
websocket._LOG_READ_BLOCK = records._LOG_READ_BLOCK
websocket._read_log_tail = records._read_log_tail
websocket._read_log_updates = records._read_log_updates


async def _tail_logs(self, ws):
    path = websocket.Path("./data/audit.jsonl")
    service = records.RecordsService(SimpleNamespace(data_dir=path.parent),
                                    get_audit_path=lambda: path)
    # Original monkeypatch boundaries remain diagnostic only. The default
    # operations resolve the named method's real filesystem reader.
    original_tail, original_updates = records._read_log_tail, records._read_log_updates
    records._read_log_tail = websocket._read_log_tail
    records._read_log_updates = websocket._read_log_updates
    cursor = None
    try:
        try:
            page = await service.handle("logs.tail", {})
            cursor = page["cursor"]
            for line in page["lines"]:
                if ws.closed or not await self._send_stream(
                    ws, "logs", {"type": "log", "line": line}
                ):
                    return
        except records.MethodError:
            pass
        while not ws.closed and ws in self._log_subscribers:
            try:
                await websocket.asyncio.sleep(websocket._LOG_POLL_INTERVAL)
                page = await service.handle("logs.tail", {"cursor": cursor} if cursor else {})
                cursor = page["cursor"]
                for line in page["lines"]:
                    if line and not ws.closed:
                        if not await self._send_stream(ws, "logs", {"type": "log", "line": line}):
                            return
            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError, records.MethodError):
                break
    finally:
        records._read_log_tail, records._read_log_updates = original_tail, original_updates


websocket.WebSocketManager._tail_logs = _tail_logs


def production_server():
    """Real pinned middleware/session policy; no live config/persistence/start."""
    config = WebConfig(enabled=True, api_token="[REDACTED]")
    server = _health.HealthServer(web_config=config, webhook_config=WebhookConfig(enabled=False))
    bot = MagicMock()
    bot.config.web = config
    bot.api_token_manager = None
    bot.audit.log_web_action = AsyncMock()
    bot.sessions.items_snapshot.return_value = []
    bot.sessions.get.return_value = None
    server._config_owner = bot
    server._app["token_manager"] = None
    routes = __import__("aiohttp", fromlist=["web"]).web.RouteTableDef()
    _security.register_api_tokens(routes, bot)
    server._app.router.add_routes(routes)
    server._ws_manager = websocket.setup_websocket(server._app, bot, web_config=config)
    server._app["ws_manager"] = server._ws_manager
    return server, bot
