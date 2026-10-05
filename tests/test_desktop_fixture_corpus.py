"""Static checks do not execute frozen tests or runtime imports."""

import ast
from types import ModuleType

import pytest

from scripts.maintenance.fixture_corpus import (
    apply_transformations,
    corpus,
    digest,
    dump,
    frozen_source,
    register_module,
    verify_transform,
)


def test_changed_assert_and_parameter_values_have_different_corpora():
    before = ast.parse("@pytest.mark.parametrize('x', [1])\ndef test_a(x): assert x == 1")
    bad_assert = ast.parse("@pytest.mark.parametrize('x', [1])\ndef test_a(x): assert x == 2")
    bad_params = ast.parse("@pytest.mark.parametrize('x', [2])\ndef test_a(x): assert x == 1")
    assert corpus(before) != corpus(bad_assert)
    assert corpus(before) != corpus(bad_params)


def test_static_corpus_never_executes_source():
    assert corpus(ast.parse("raise RuntimeError('forbidden')\ndef test_a(): assert False"))[
        "assertions"
    ]


def test_registration_rebases_module_retaining_factory_globals():
    module = ModuleType("frozen_fixture")
    exec(
        "def factory(): return 7\ndef test_a(): return factory()\n"
        "class TestCase:\n def test_b(self): return factory()",
        module.__dict__,
    )
    namespace = {"__name__": "wrapper_fixture"}
    register_module(namespace, module, prefix="baseline")
    function, cls = namespace["test_baseline_a"], namespace["Test_baseline_Case"]
    assert function.__module__ == cls.__module__ == cls.test_b.__module__ == "wrapper_fixture"
    assert function.__globals__ is module.__dict__
    assert function() == cls().test_b() == 7


def test_hash_checked_before_archive_parsing(tmp_path):
    directory = tmp_path / "maintenance"
    directory.mkdir()
    (directory / "odin-v4.13.0.tar.gz").write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="archive hash"):
        frozen_source("tests/test_agent_tool_policy_branch_coverage.py", root=tmp_path)


def test_frozen_retained_bytes_are_verified_without_importing_tests():
    data = frozen_source("tests/test_agent_tool_policy_branch_coverage.py")
    assert corpus(ast.parse(data))["cases"]


def _synthetic_manifest(tmp_path, monkeypatch):
    """An offline unit fixture, not a waiver for any repository/runtime source."""
    import scripts.maintenance.fixture_corpus as helper

    original = ast.parse(
        "def test_a():\n x = Config(discord={'token': 'dummy'}, tools={})\n assert x\n"
    )
    call = next(n for n in ast.walk(original) if isinstance(n, ast.Call))
    row = {
        "path": "tests/test_synthetic.py",
        "baseline_sha256": digest(b"synthetic"),
        "transformations": [
            {
                "operation": "remove_config_discord_keyword",
                "symbol": "test_a",
                "line": 2,
                "before_sha256": digest(dump(call).encode()),
            }
        ],
    }
    monkeypatch.setattr(helper, "suite_record", lambda path, root: row)
    return helper, original


def test_exact_keyword_operation_removes_only_keyword(tmp_path, monkeypatch):
    helper, original = _synthetic_manifest(tmp_path, monkeypatch)
    adapted = apply_transformations("tests/test_synthetic.py", original)
    call = next(n for n in ast.walk(adapted) if isinstance(n, ast.Call))
    assert [k.arg for k in call.keywords] == ["tools"]
    assert corpus(original) == corpus(adapted)
    assert helper.dump(original) != helper.dump(adapted)


def test_wrong_hunk_location_is_rejected(tmp_path, monkeypatch):
    helper, original = _synthetic_manifest(tmp_path, monkeypatch)
    row = helper.suite_record("tests/test_synthetic.py", tmp_path)
    row["transformations"][0]["symbol"] = "other_test"
    with pytest.raises(ValueError, match="exactly once"):
        apply_transformations("tests/test_synthetic.py", original)


def test_assert_and_parameter_mutation_verifier_fails_before_execution(monkeypatch):
    original = ast.parse("@pytest.mark.parametrize('x', [1])\ndef test_a(x): assert x == 1")
    for source in (
        "@pytest.mark.parametrize('x', [2])\ndef test_a(x): assert x == 1",
        "@pytest.mark.parametrize('x', [1])\ndef test_a(x): assert x == 2",
    ):
        adapted = ast.parse(source)
        with pytest.raises(ValueError, match="Assertion"):
            verify_transform("tests/test_forbidden.py", original, adapted)


def test_static_catalog_alias_preserves_original_name(monkeypatch):
    import scripts.maintenance.fixture_corpus as helper

    original = ast.parse(
        "from src.tools.registry import get_tool_definitions\ndef test_a(): assert True"
    )
    row = {
        "transformations": [
            {
                "operation": "documentation_catalog_import",
                "symbol": "<module>",
                "line": 1,
                "before_sha256": digest(dump(original.body[0]).encode()),
            }
        ]
    }
    monkeypatch.setattr(helper, "suite_record", lambda path, root: row)
    adapted = apply_transformations("tests/test_synthetic.py", original)
    assert adapted.body[0].names[0].name == "get_documentation_tool_definitions"
    assert adapted.body[0].names[0].asname == "get_tool_definitions"
    assert corpus(adapted) == corpus(original)


def test_case_ids_include_class_and_hash_parameters():
    from scripts.maintenance.fixture_corpus import case_mapping

    original = ast.parse(
        "class TestCase:\n @pytest.mark.parametrize('x', [1, 2])\n def test_a(self, x): assert x"
    )
    row = case_mapping("tests/test_baseline.py", original, "wrapper_fixture", "baseline")[0]
    assert row["baseline_selector"] == "tests/test_baseline.py::TestCase::test_a"
    assert row["executable_case"] == "Test_baseline_Case::test_a"
    assert len(row["assertions_sha256"]) == len(row["decorators_sha256"]) == 64


def test_class_decorator_mutation_is_visible():
    original = ast.parse(
        "@pytest.mark.skip(reason='baseline')\nclass TestCase:\n def test_a(self): assert True"
    )
    adapted = ast.parse(
        "@pytest.mark.skip(reason='changed')\nclass TestCase:\n def test_a(self): assert True"
    )
    assert corpus(original) != corpus(adapted)


def test_replacement_full_ast_digest_is_checked(monkeypatch, tmp_path):
    helper, original = _synthetic_manifest(tmp_path, monkeypatch)
    rule = helper.suite_record("tests/test_synthetic.py", tmp_path)["transformations"][0]
    rule.update(kind="expression", after_source="Config(tools={})", after_sha256="0" * 64)
    with pytest.raises(ValueError, match="hash mismatch"):
        apply_transformations("tests/test_synthetic.py", original)


def test_semantic_keyword_rule_cannot_modify_other_inputs(monkeypatch, tmp_path):
    helper, original = _synthetic_manifest(tmp_path, monkeypatch)
    rule = helper.suite_record("tests/test_synthetic.py", tmp_path)["transformations"][0]
    rule.update(kind="expression", after_source="Config(tools={'mutated': 1})")
    with pytest.raises(ValueError, match="changed more"):
        apply_transformations("tests/test_synthetic.py", original)


def test_verifier_rejects_unlisted_setup_and_forged_baseline(monkeypatch, tmp_path):
    helper, original = _synthetic_manifest(tmp_path, monkeypatch)
    source = ast.unparse(original).encode()
    row = helper.suite_record("tests/test_synthetic.py", tmp_path)
    row["baseline_sha256"] = digest(source)
    monkeypatch.setattr(helper, "frozen_source", lambda path, root: source)
    adapted = apply_transformations("tests/test_synthetic.py", original)
    assert verify_transform("tests/test_synthetic.py", original, adapted)
    adapted.body.append(ast.Expr(value=ast.Constant(value="unlisted")))
    with pytest.raises(ValueError, match="outside"):
        verify_transform("tests/test_synthetic.py", original, adapted)
    row["baseline_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Original AST"):
        verify_transform("tests/test_synthetic.py", original, original)


def test_exact_baseline_to_adapter_mapping_is_static_and_complete():
    from scripts.maintenance.fixture_corpus import adapter_case_associations
    result = adapter_case_associations(
        "tests/test_desktop_shared_tools.py", "tests/desktop_adapters/tools_cases.py"
    )
    assert result["case_count"] == len(result["cases"]) > 100
    assert len({row["baseline_selector"] for row in result["cases"]}) == result["case_count"]
    assert all(row["executable_selector"].startswith("tests/test_desktop_shared_tools.py::")
               for row in result["cases"])
    assert len(result["mapping_sha256"]) == len(result["adapter_sha256"]) == 64
    assert not any("test_native_launch_failure_raises" in row["baseline_selector"]
                   for row in result["cases"])


def test_manifest_pins_independent_adapter_case_associations():
    from scripts.maintenance.fixture_corpus import adapter_case_associations, manifest
    for record in manifest()["adapter_associations"]:
        observed = adapter_case_associations(
            record["adapter_path"], record["declaration_path"],
            full_class_name=record["full_class_name"],
        )
        for field in ("adapter_sha256", "declaration_sha256", "case_count", "mapping_sha256"):
            assert observed[field] == record[field]
