"""Entire pinned guard corpus, with only the obsolete bot setup replaced.

The setup creates a real authenticated temporary core and ManagementService.
No guard, executor, provider owner, runtime, or authority is substituted.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import os
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from types import ModuleType

import yaml

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.desktop.authority import OwnerAuthority
from src.desktop.core import CoreService
from src.desktop.provisioning import fresh_config_document
from src.permissions.persistence import write_private_atomic
from tests.test_desktop_core_lifecycle import connect, profile, request

PATH = "tests/test_subsystem_guard.py"
SOURCE_PATH = PATH
SOURCE_SHA256 = "5c4f14908ca2b46527800bc7304633e2833509048ee474d9192c8c68de24c1d7"
SUITES = {
    "test_subsystem_guard": "5c4f14908ca2b46527800bc7304633e2833509048ee474d9192c8c68de24c1d7"
}
CORPUS_SELECTIONS = {"test_subsystem_guard": None}
CORPUS_EXCLUSIONS = {}
SYMBOL = (
    "TestGracefulDegradationConfig."
    "test_real_bot_guard_is_always_constructed_with_supported_thresholds"
)
SETUP_SHA256 = "9086afe8b438724161cd25d175c34ec72b2968497b1fbf5d5ce1ce223bd03d90"
REPLACEMENT_SOURCE = "cfg, bot = desktop_guard_graph(legacy_enabled)"
_active_setup = ContextVar("step8_runtime_guard_setup", default=None)


class TemporaryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self.values[service, name] = value

    def delete_password(self, service, name):
        self.values.pop((service, name), None)


@asynccontextmanager
async def authenticated_profile(root, legacy_enabled, *, degraded=7, unavailable=19):
    paths, socket_path, token_file = profile(root)
    OwnerAuthority(paths, app_bootstrap=True)
    document = fresh_config_document(paths)
    document["openai_codex"]["enabled"] = False
    document["graceful_degradation"] = {
        "enabled": legacy_enabled,
    }
    if degraded is not None:
        document["graceful_degradation"]["degraded_threshold"] = degraded
    if unavailable is not None:
        document["graceful_degradation"]["unavailable_threshold"] = unavailable
    if not write_private_atomic(paths.config_file, yaml.safe_dump(document)):
        raise AssertionError("temporary profile config was not durable")
    read_fd, write_fd = os.pipe()
    core = CoreService(paths, socket_path, token_file, secret_backend=TemporaryKeyring())
    writer = None
    try:
        await core.start(read_fd)
        # Real token handshake precedes the authenticated status request.
        reader, writer, welcome = await connect(socket_path, token=token_file.read_text())
        assert welcome["t"] == "welcome", welcome
        answer = await request(reader, writer, "status.get")
        assert answer["ok"], answer
        yield core
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await core.close()
        os.close(read_fd)
        os.close(write_fd)


@contextmanager
def temporary_guard_graph(root, legacy_enabled, **thresholds):
    with asyncio.Runner() as runner:
        context = authenticated_profile(root, legacy_enabled, **thresholds)
        core = runner.run(context.__aenter__())
        try:
            yield core, runner
        finally:
            runner.run(context.__aexit__(None, None, None))


@contextmanager
def inherited_setup(root, legacy_enabled):
    with temporary_guard_graph(root, legacy_enabled) as (core, _):
        token = _active_setup.set((legacy_enabled, core.management))
        try:
            yield core
        finally:
            _active_setup.reset(token)


def desktop_guard_graph(legacy_enabled):
    active = _active_setup.get()
    if active is None or active[0] is not legacy_enabled:
        raise AssertionError("inherited setup requires its authenticated temporary profile")
    manager = active[1]
    return manager.settings.config, manager


def _target(tree):
    owner, name = SYMBOL.split(".")
    matches = [method for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner
               for method in node.body
               if isinstance(method, ast.FunctionDef) and method.name == name]
    if len(matches) != 1:
        raise ValueError("guard setup symbol must match exactly once")
    return matches[0]


def _representation(nodes):
    return [dump(node) for node in nodes]


def _setup_hash(nodes):
    return hashlib.sha256("\n".join(_representation(nodes)).encode()).hexdigest()


def adapt(original):
    adapted = copy.deepcopy(original)
    target = _target(adapted)
    # Exact whole setup AST pin, not a general-purpose Config/OdinBot rewrite.
    if _setup_hash(target.body[1:5]) != SETUP_SHA256:
        raise ValueError("guard setup AST pin changed")
    target.body[1:5] = ast.parse(REPLACEMENT_SOURCE).body
    ast.fix_missing_locations(adapted)
    verify(original, adapted)
    return adapted


def verify(original, adapted):
    if corpus(original) != corpus(adapted):
        raise ValueError("guard assertion/signature/decorator/parameter corpus changed")
    restored = copy.deepcopy(adapted)
    target = _target(restored)
    if _representation(target.body[1:2]) != _representation(ast.parse(REPLACEMENT_SOURCE).body):
        raise ValueError("guard replacement AST pin changed")
    original_setup = _target(original).body[1:5]
    if _setup_hash(original_setup) != SETUP_SHA256:
        raise ValueError("guard original setup AST pin changed")
    target.body[1:2] = copy.deepcopy(original_setup)
    if dump(restored) != dump(original):
        raise ValueError("guard reverse AST differs outside the one pinned setup")
    return restored


def load(namespace):
    source = frozen_source(PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("guard frozen source hash changed")
    original = ast.parse(source, filename=PATH)
    adapted = adapt(original)
    module = ModuleType("desktop_frozen_subsystem_guard")
    module.__file__ = PATH
    module.desktop_guard_graph = desktop_guard_graph
    exec(compile(adapted, PATH, "exec"), module.__dict__)
    register_module(namespace, module)
    return original, adapted
