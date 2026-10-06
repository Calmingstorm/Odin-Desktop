"""Round-2 original CLI corpus export and fail-closed provenance guards."""
from __future__ import annotations

import ast

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters.step8_review_cli_exact import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    SETUP_RULES,
    SOURCE_PATH,
    adapt,
    load,
)
from tests.desktop_adapters.step8_review_cli_exact import (
    register_module as export,
)

_module, _original, _adapted = load(globals())


def test_cli_round2_complete_original_corpus_and_exact_projection():
    assert corpus(_original) == corpus(_adapted)
    assert len(corpus(_original)["cases"]) == 5
    assert len(corpus(_original)["assertions"]) == 15
    assert CORPUS_SELECTIONS == {"test_campaign_cli_coverage": None}
    assert CORPUS_EXCLUSIONS == {"test_campaign_cli_coverage": [
        {"case": "test_piped_prompt_and_environment_build_real_authenticated_request",
         "reviewer": "Claude, review of #35, round 2",
         "reason": "HTTP API client replaced by the authenticated local IPC client",
         "source_path": "tests/test_campaign_cli_coverage.py",
         "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
        {"case": "test_transport_failure_is_nonzero_even_in_json_mode",
         "reviewer": "Claude, review of #35, round 2",
         "reason": "HTTP API client replaced by the authenticated local IPC client",
         "source_path": "tests/test_campaign_cli_coverage.py",
         "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
    ]}
    assert [dump(n) for n in ast.walk(_original) if isinstance(n, ast.Assert)] == [
        dump(n) for n in ast.walk(_adapted) if isinstance(n, ast.Assert)]
    retained = {
        "test_empty_prompt_prints_help_without_transport",
        "test_unreadable_prompt_path_does_not_prevent_normal_prose",
        "test_python_client_refuses_legacy_daemon_arguments_before_network",
    }
    retired = {item["case"] for item in CORPUS_EXCLUSIONS["test_campaign_cli_coverage"]}
    original_names = {name for name in vars(_module) if name.startswith("test_")}
    assert original_names == retained | retired
    for name in retained:
        # Export the original compiled function itself, not a replay wrapper.
        exported = globals()["test_test_campaign_cli_coverage_" + name[5:]]
        assert exported is getattr(_module, name)
        assert exported.__globals__ is vars(_module)
    assert all("test_test_campaign_cli_coverage_" + name[5:] not in globals()
               for name in retired)


def test_cli_round2_bytes_and_allowlist_guards():
    source = frozen_source(SOURCE_PATH)
    with pytest.raises(ValueError, match="bytes changed"):
        adapt(source + b"\n")
    for rules in ((), SETUP_RULES[:1], SETUP_RULES * 2, (*SETUP_RULES,
            (30, 'monkeypatch.setattr(cli.sys, "argv", ["odin", "hello", "--json"])',
             "monkeypatch.setattr(cli.sys, 'argv', ['odin'])"))):
        with pytest.raises(ValueError, match="allowlist changed"):
            adapt(source, rules=rules)


@pytest.mark.parametrize("collateral", ["assertion", "setup"])
def test_cli_round2_assertion_and_full_ast_guards(monkeypatch, collateral):
    from tests.desktop_adapters import step8_review_cli_exact as adapter

    fix = ast.fix_missing_locations

    def corrupt(tree):
        fix(tree)
        if collateral == "assertion":
            first = next(node for node in ast.walk(tree) if isinstance(node, ast.Assert))
            first.test = ast.Constant(value=True)
        else:
            tree.body.append(ast.parse("unadmitted_setup = 1").body[0])
        return tree

    monkeypatch.setattr(adapter.ast, "fix_missing_locations", corrupt)
    expected = "assertion/signature/decorator/parameter drift" if collateral == "assertion" else (
        "complete AST reverse replay failed")
    with pytest.raises(ValueError, match=expected):
        adapt(frozen_source(SOURCE_PATH))


def test_cli_round2_export_rejects_missing_extra_duplicate_retirement():
    excluded = [item["case"] for item in CORPUS_EXCLUSIONS["test_campaign_cli_coverage"]]
    for changed in ([], excluded[:1], excluded[::-1], excluded * 2,
                    [*excluded, "test_empty_prompt_prints_help_without_transport"]):
        namespace = {"__name__": "guarded_cli_export"}
        with pytest.raises(ValueError, match="exact approved retirement projection"):
            export(namespace, _module, excluded=changed)
        assert namespace == {"__name__": "guarded_cli_export"}
    namespace = {"__name__": "guarded_cli_export"}
    export(namespace, _module, excluded=excluded)
    assert {name for name in namespace if name.startswith("test_")} == {
        "test_empty_prompt_prints_help_without_transport",
        "test_unreadable_prompt_path_does_not_prevent_normal_prose",
        "test_python_client_refuses_legacy_daemon_arguments_before_network",
    }
