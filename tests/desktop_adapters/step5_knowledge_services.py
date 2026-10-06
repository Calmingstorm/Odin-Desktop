"""Test-only syntax projection onto real named management services.

No HTTP server, registrar, store algorithm or outcome implementation lives
here. Legacy request spellings select explicit named methods and project their
actual result/error into the frozen suites' response spelling. Transport-only
malformed JSON goes through the named service's object boundary.
"""
from __future__ import annotations

import contextvars
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit

from src.desktop.knowledge import KnowledgeService
from src.desktop.learned_context import LearnedContextService
from src.desktop.management import MethodError
from src.desktop.state import StateService
from src.knowledge.importer import BulkImporter
from src.tools.executor import ToolExecutor

fixture_state = contextvars.ContextVar("step5_knowledge_fixture", default=None)


class RetainedMemoryBot:
    def __init__(self, executor):
        self.tool_executor = executor

    @property
    def _backing(self):
        return self.tool_executor._load_all_memory()


def retained_memory_bot(initial=None):
    state = fixture_state.get()
    if state is None:
        raise RuntimeError("temporary owner fixture required")
    executor = ToolExecutor(profile_paths=state.paths,
                            memory_path=str(state.paths.data_dir / "memory.json"))
    data = {"global": {}}
    if initial:
        data.update(initial)
    executor._save_all_memory(data)
    return RetainedMemoryBot(executor)


class FixtureServices(list):
    """Admitted temporary scopes are setup, never a renderer-supplied tier."""
    def __init__(self, *args, scope_authorities=None, caller=None):
        super().__init__(*args)
        self.scope_authorities = scope_authorities
        self.caller = caller


class UnavailableStore:
    available = False


def register_knowledge(routes, bot):
    routes.append(KnowledgeService(
        SimpleNamespace(data_dir=Path.cwd()),
        store=bot.knowledge if bot.knowledge is not None else UnavailableStore(),
    ))


def register_learned_context(routes, bot):
    routes.append(LearnedContextService(None, reflector=bot.reflector))


def register_memory_notes(routes, bot):
    routes.append(StateService(None, getattr(bot, "fixture_owner", "alice"),
                               memory=bot.tool_executor))


def app(*registrars, bot):
    services = FixtureServices()
    for registrar in registrars:
        registrar(services, bot)
    if (register_memory_notes in registrars
            and getattr(getattr(bot, "config", None), "web", None) is not None):
        services.scope_authorities = {}
    return services


def scoped_memory_fixture(bot, identity):
    state = fixture_state.get()
    if state is None:
        raise RuntimeError("temporary owner fixture required")
    # User cases grant only global and their temporary profile; admin cases
    # grant all fixture scopes. No tier is forwarded into runtime services.
    scopes = ({"global", f"user_{identity.user_id}"}
              if identity.tier == "user" else set(bot._backing))
    authority = state.authority
    context = authority.authenticate_local(peer_uid=authority.owner_uid)
    # Each granted profile has real retained state. Listing is performed by the
    # real service against that profile, never filtered or invented afterward.
    selected = {scope: value for scope, value in bot._backing.items() if scope in scopes}
    executor = ToolExecutor(profile_paths=state.paths,
                            memory_path=str(state.paths.data_dir / "granted-memory.json"))
    executor._save_all_memory(selected)
    services = app(register_memory_notes, bot=RetainedMemoryBot(executor))
    services.scope_authorities = {scope: authority for scope in scopes}
    services.caller = context
    return services


def knowledge_app(bot):
    return app(register_knowledge, bot=bot)


def search_fixture(bot):
    client = NamedServiceClient(knowledge_app(bot))

    async def search_knowledge(request):
        response = await client.invoke("knowledge.search", request.query)
        return SimpleNamespace(status=response.status, text=response._text)

    return [SimpleNamespace(handler=search_knowledge)]


def import_fixture(bot, root):
    services = knowledge_app(bot)
    services[0]._importer = BulkImporter(bot.knowledge, admitted_roots=[root])
    return services


class Response:
    def __init__(self, status, body):
        self.status = status
        self.body = body
        self._text = json.dumps(body)

    async def json(self):
        return self.body

    async def text(self):
        return self._text


class NamedServiceClient:
    __test__ = False
    def __init__(self, services):
        self.services = services

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def invoke(self, method, params):
        service = next(s for s in self.services if method in s.METHODS)
        authorities = getattr(self.services, "scope_authorities", None)
        if method.startswith("memory.") and authorities is not None and isinstance(params, dict):
            if self.services.caller is None:
                return Response(403, {"error": "memory access denied"})
            scopes = ([entry.get("scope") for entry in params.get("entries", [])
                       if isinstance(entry, dict)] if method == "memory.bulk_delete"
                      else [params["scope"]] if "scope" in params else [])
            if any(scope not in authorities
                   or not authorities[scope].accepts(self.services.caller) for scope in scopes):
                return Response(403, {"error": "memory access denied"})
        try:
            result = await service.handle(method, params)
        except MethodError as error:
            statuses = {"bad_request": 400, "forbidden": 403, "not_found": 404,
                        "conflict": 409, "unavailable": 503, "internal_error": 500}
            return Response(statuses[error.code], {"error": error.message})
        created = method == "knowledge.ingest" and result.get("outcome", "stored") == "stored"
        return Response(201 if created else 200, result)

    async def request(self, verb, url, **kwargs):
        parsed = urlsplit(url)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/")]
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        body = kwargs.get("json", {})
        if "data" in kwargs:
            # Malformed transport cannot invoke a mutation with parsed params.
            body = kwargs["data"]
        domain = parts[1]
        tail = parts[2:]
        if domain == "knowledge":
            if not tail:
                method = {"GET": "knowledge.list", "POST": "knowledge.ingest"}[verb]
            elif tail[0] in {"search", "duplicates", "merge", "import"}:
                method = "knowledge." + tail[0]
            else:
                params["source"] = tail[0]
                if len(tail) == 1:
                    method = "knowledge.delete"
                elif tail[1] != "versions":
                    method = "knowledge." + tail[1]
                elif len(tail) == 2:
                    method = "knowledge.versions"
                elif len(tail) == 3:
                    method, params["version"] = "knowledge.version", int(tail[2])
                elif tail[3] == "restore":
                    method, params["version"] = "knowledge.restore", int(tail[2])
                else:
                    method = "knowledge.diff"
                    params.update(v1=int(tail[2]), v2=int(tail[4]))
        elif domain == "learned":
            method = {"GET": "learned.list", "PUT": "learned.update",
                      "DELETE": "learned.delete"}[verb]
            if tail:
                params["key"] = tail[0]
        elif domain == "memory":
            if not tail:
                method = "memory.list"
            elif tail == ["bulk-delete"]:
                method = "memory.bulk_delete"
            else:
                params["scope"] = tail[0]
                if len(tail) > 1:
                    params["key"] = tail[1]
                method = {"GET": "memory.get", "PUT": "memory.set",
                          "DELETE": "memory.delete"}[verb]
        else:
            raise ValueError("unmapped legacy fixture spelling")
        if not isinstance(body, dict):
            return await self.invoke(method, body)
        params.update(body)
        return await self.invoke(method, params)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self.request("DELETE", url, **kwargs)


def fixture_server(services):
    return services


TestClient = NamedServiceClient
TestServer = fixture_server
