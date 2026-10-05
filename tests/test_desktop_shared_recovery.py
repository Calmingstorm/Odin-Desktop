"""Audited pure computer safety cases, with real policies and temporary SQLite."""

import ast
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from scripts.maintenance.fixture_corpus import (
    ARCHIVE_SHA256,
    BASELINE,
    ROOT,
    digest,
    frozen_source,
)
from src.computer.controller import ComputerController
from src.computer.models import ComputerError, RequestContext
from src.computer.store import ComputerStore
from tests.desktop_adapters.computer_cases import (
    CORPUS_SELECTIONS,
    PROOFS,
    adapt,
    export,
)

for suite in CORPUS_SELECTIONS:
    export(globals(), suite)


def test_computer_exact_fixture_corpus_manifest():
    record = json.loads((ROOT / "maintenance/computer-suite-triage.json").read_text())
    assert record["baseline"] == BASELINE
    assert record["archive_sha256"] == ARCHIVE_SHA256
    assert record["suites"] == [
        {
            "path": row["path"],
            "source_sha256": row["source_sha256"],
            "proof_sha256": digest(json.dumps(row, sort_keys=True).encode()),
            "executed_definitions": len(row["case_mapping"]),
            "removed_definitions": len(row["removed_cases"]),
            "helper_only": row["helper_only"],
        }
        for row in PROOFS.values()
    ]
    assert all(row["assert_case_ast_preserved"] for row in PROOFS.values())
    assert set(record["dependencies"]) == {
        "tests/test_computer_contract_r1.py",
        "tests/test_hyprland_store_campaign.py",
        "tests/test_hyprland_durable_reconnect.py",
    }
    for path, sha256 in record["dependencies"].items():
        assert digest(frozen_source(path)) == sha256
    assert {row["baseline_selector"] for row in record["removed_cases"]} == {
        f"{row['path']}::{case}" for row in PROOFS.values() for case in row["removed_cases"]
    }
    for row in PROOFS.values():
        adapted = adapt(row["path"].removeprefix("tests/").removesuffix(".py"))
        selected = {
            n.name
            for n in ast.walk(adapted)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
        }
        if not row["helper_only"]:
            assert selected == set(row["case_mapping"])


@pytest.mark.parametrize(
    "route",
    [
        "reconcile_recovery",
        "acknowledge_legacy_recovery",
        "operator_reconcile",
        "operator_session",
        "operator_release_owned_input",
        "operator_observe",
        "operator_export",
        "read_evidence",
    ],
)
@pytest.mark.parametrize("surface", ["desktop", "webui", "discord"])
async def test_desktop_denies_removed_operator_routes(tmp_path, route, surface):
    store = ComputerStore(tmp_path / "db", tmp_path / "evidence")
    context = RequestContext("owner", "conversation", "turn", "host", surface=surface)
    authorize = AsyncMock(return_value=True)
    backend = AsyncMock()
    controller = ComputerController(store, backend, authorize, enabled=True)
    grant = store.create_session(replace(context, surface="desktop"), "drawing")
    store.recover()
    grant = store.get_session(grant.session_id)
    before = store.get_session(grant.session_id)
    acknowledgment = f"ACKNOWLEDGE UNVERIFIED CLEANUP {grant.session_id}"
    arguments = {
        "reconcile_recovery": (grant.session_id, grant.generation),
        "acknowledge_legacy_recovery": (grant.session_id, grant.generation, acknowledgment),
        "operator_reconcile": (grant.session_id, grant.generation, acknowledgment),
        "operator_session": ("status",),
        "operator_release_owned_input": (grant.session_id, grant.generation),
        "operator_observe": (),
        "operator_export": ("result.png",),
        "read_evidence": ("unavailable",),
    }
    try:
        expected = "operator_surface_required" if surface == "desktop" else "foreground_only"
        with pytest.raises(ComputerError, match=expected):
            await getattr(controller, route)(context, *arguments[route])
        assert store.get_session(grant.session_id) == before
        backend.assert_not_called()
        if surface != "desktop":
            authorize.assert_not_awaited()
    finally:
        await controller.close()
        store.close()


@pytest.mark.parametrize("field", ["owner_id", "channel_id", "host_id", "turn_id"])
async def test_desktop_context_is_not_cross_conversation_authority(tmp_path, field):
    store = ComputerStore(tmp_path / "db", tmp_path / "evidence")
    owner = RequestContext("owner", "conversation", "turn", "host", surface="desktop")
    backend = AsyncMock()
    authorize = AsyncMock(return_value=True)
    controller = ComputerController(store, backend, authorize, enabled=True)
    grant = store.create_session(owner, "drawing")
    store.set_state(grant.session_id, "paused")
    try:
        with pytest.raises(ComputerError, match="not_found"):
            await controller.observe(
                replace(owner, **{field: "foreign"}),
                {
                    "session_id": grant.session_id,
                    "generation": grant.generation,
                },
            )
        backend.assert_not_called()
    finally:
        await controller.close()
        store.close()
