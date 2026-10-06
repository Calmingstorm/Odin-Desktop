"""Restored dispatcher corpus with exact reviewed foreign-caller exclusions.

The facade shares the real module ContextVar, not an executor. No authority or
result is rewritten. Retired case source remains immutable and hash-pinned.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import frozen_source
from tests.desktop_adapters import step8_review_helpers as helpers

STEM = "characterization/test_executor_dispatch_parity"
SOURCE_PATH = f"tests/{STEM}.py"
SOURCE_SHA256 = helpers.SUITES[STEM]
CORPUS_SELECTIONS = {"characterization/test_executor_dispatch_parity": None}
CORPUS_EXCLUSIONS = {
    "characterization/test_executor_dispatch_parity": [
        {
            "case": "TestMiddlewarePins.test_contextvar_isolation_concurrent",
            "reviewer": "Claude, review of #35, round 2",
            "reason": "multi-user caller identities removed; one canonical owner",
            "source_path": "tests/characterization/test_executor_dispatch_parity.py",
            "source_sha256": "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
        },
        {
            "case": "TestMiddlewarePins.test_rbac_denial_shape_and_metrics",
            "reviewer": "Claude, review of #35",
            "reason": "Guest-tier RBAC is removed by Desktop D17; Claude, review of #35 retires only this guest denial/metrics case.",
            "source_path": "tests/characterization/test_executor_dispatch_parity.py",
            "source_sha256": "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
        },
        {
            "case": "TestPatchSeam.test_memory_manage_receives_user_id_kwarg",
            "reviewer": "Claude, review of #35, round 2",
            "reason": "multi-user caller identities removed; one canonical owner",
            "source_path": "tests/characterization/test_executor_dispatch_parity.py",
            "source_sha256": "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
        },
    ],
}


def load(namespace):
    stem = STEM
    original, tree = helpers.adapt(STEM, frozen_source(SOURCE_PATH))
    module = ModuleType("review_dispatch_unchanged_goldens")
    module.__file__ = str(Path(__file__).resolve().parents[2] / SOURCE_PATH)
    module.__package__ = "tests.characterization"
    module.__dict__["desktop_executor"] = helpers.desktop_executor
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    helpers.register_module(
        namespace, module, prefix="dispatch_candidate",
        excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())],
    )
    return original, tree


class ProfileRoute:
    def __init__(self, state, executor):
        self.state, self.executor = state, executor
        self.owner_id = state.authority.owner_id

    async def execute(self, tool_name, tool_input, *, user_id):
        context = self.state.authority.authenticate_local(peer_uid=self.state.authority.owner_uid)
        token = self.state.manager.set_request_owner(context)
        try:
            # Existing wrapper submits; the real RequestService worker reauthenticates.
            return await self.executor.execute(tool_name, tool_input, user_id=user_id)
        finally:
            self.state.manager.reset_request_owner(token)


class ProfileExecutorFacade:
    """Read-through route selection without permission-manager substitution."""
    def __init__(self, routes):
        self.routes = tuple(routes)
        if len({r.owner_id for r in self.routes}) != len(self.routes):
            raise ValueError("distinct authentic profile IDs required")

    def install_handler_fixture(self, name, handler):
        for route in self.routes:
            setattr(route.executor, "_handle_" + name, handler)

    async def execute(self, tool_name, tool_input, *, user_id):
        route = next((r for r in self.routes if r.owner_id == user_id), self.routes[0])
        return await route.execute(tool_name, tool_input, user_id=user_id)


@asynccontextmanager
async def two_profiles(tmp_path, config):
    async with helpers.owner_fixture(tmp_path / "first") as first:
        first_executor = helpers.desktop_executor(config=config)
        async with helpers.owner_fixture(tmp_path / "second") as second:
            second_executor = helpers.desktop_executor(config=config)
            yield ProfileExecutorFacade((ProfileRoute(first, first_executor),
                                         ProfileRoute(second, second_executor)))
