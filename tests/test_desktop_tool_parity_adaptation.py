"""Independent proof of exact review-authorized parity substitutions."""
import ast

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters.tool_parity import REVIEWED_SUBSTITUTIONS, SOURCE_PATH, adapted_source


def test_reviewed_bindings_reverse_to_exact_frozen_bytes():
    text = adapted_source()
    for old, new in reversed(REVIEWED_SUBSTITUTIONS):
        assert text.count(new) == 1
        text = text.replace(new, old, 1)
    assert text.encode() == frozen_source(SOURCE_PATH)


def test_reviewed_bindings_preserve_every_signature_decorator_and_untouched_case():
    original = ast.parse(frozen_source(SOURCE_PATH))
    adapted = ast.parse(adapted_source())
    assert corpus(original)["cases"] == corpus(adapted)["cases"]
    assert corpus(original)["classes"] == corpus(adapted)["classes"]
    assert len(corpus(original)["cases"]) == 10
    untouched = {"test_no_duplicate_names",
                 "test_generate_image_follows_codex_auth_not_chat_provider"}
    original_cases = {n.name: dump(n) for n in ast.walk(original)
                      if isinstance(n, ast.FunctionDef) and n.name in untouched}
    adapted_cases = {n.name: dump(n) for n in ast.walk(adapted)
                     if isinstance(n, ast.FunctionDef) and n.name in untouched}
    assert original_cases == adapted_cases


def test_only_eleven_reviewed_hashes_are_re_pinned():
    namespace = {}
    exec(compile(adapted_source(), SOURCE_PATH, "exec"), namespace)
    inherited = namespace["EXPECTED_TOOL_HASHES"]
    repinned = namespace["REPINNED_TOOL_HASHES"]
    derived = namespace["DESKTOP_TOOL_HASHES"]
    assert set(repinned) == {
        "post_file", "generate_file", "schedule_task", "update_schedule", "search_history",
        "delegate_task", "browser_screenshot", "spawn_agent", "generate_image",
        "get_tool_output", "read_conversation",
    }
    assert {name for name in derived if derived[name] != inherited.get(name)} == set(repinned)


def test_analyze_pdf_gate_binds_decision_f_and_nothing_else():
    """Decision F keeps analyze_pdf offered while its pinned first-use download can start."""
    original, adapted = frozen_source(SOURCE_PATH).decode(), adapted_source()

    def segment(source, name):
        node, = [n for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.FunctionDef) and n.name == name]
        return ast.get_source_segment(source, node).splitlines()

    for name in ("_dependency_gated", "test_analyze_pdf_follows_its_dependency"):
        before, after = segment(original, name), segment(adapted, name)
        assert sum("pdf_resources.pdf_available()" in line for line in after) == 1
        assert not any('find_spec("fitz")' in line for line in after)
        # Only the gate line changed: every other line, docstring included, is Odin's.
        assert [line for line in before if 'find_spec("fitz")' not in line and line.strip()] == [
            line for line in after if "pdf_resources" not in line and line.strip()]
