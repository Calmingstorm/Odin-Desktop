"""Static PR #2 round-3 documentation acceptance, not runtime parity evidence.

Reads only repository Markdown. No engine imports, profile creation, endpoints,
service operations or inherited-suite qualification belong in these tests.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_SHA = "3fac196eadf75f7bb34349c5c5fc8320d811d3e9"
TABLE = ROOT / "maintenance/pr2-model-facing-string-approvals.md"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def section(document: str, number: int) -> str:
    return document.split(f"## {number}. ", 1)[1].split("\n## ", 1)[0]


def rows(document: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in document.splitlines()
        if line.startswith("| ") and not line.startswith("| Source / selector |")
    ]


def row_for(document: str, fragment: str) -> list[str]:
    matches = [row for row in rows(document) if any(fragment in cell for cell in row)]
    assert len(matches) == 1, (fragment, matches)
    return matches[0]


# Exact named part-E coverage, not a search for all uses of "conversation".
D19_RESULTS = (
    "[INHERITED FROM {parent_name}]",
    "Parent conversation context:",
    "Only 'limit' is accepted; the conversation is the one this request came from.",
    "File {filename} ({len(file_bytes)} bytes) attached to conversation.",
    "Permission denied: authenticated owner identity is required.",
    "Progress will be posted to this conversation.",
    "Permission denied: tool '{tool_name}' is not available for this authenticated owner request.",
    "Browser unavailable: required bundled Chromium is not configured.",
    "Browser unavailable: required bundled Playwright dependency is missing.",
    "Failed to launch required bundled Chromium. Repair the desktop installation. ({e})",
    "The required bundled dependency is unavailable; repair the desktop installation.",
    "{kind} not in allowed import roots: {actual admitted roots}",
    "Access denied. Only the turn's requester may steer it.",
    "Reading the conversation",
    "Digest {schedule['id']} has no conversation_id",
    "Scheduled task {schedule['id']} has no conversation_id",
    "Let the authorized owner proceed past a governor refusal.",
    "See the desktop configuration documentation for examples.",
    "no bundled embedding model roots configured",
)


@pytest.mark.parametrize("fragment", D19_RESULTS)
def test_part_e_named_results_are_d19(fragment: str):
    row = row_for(section(TABLE.read_text(encoding="utf-8"), 4), fragment)
    assert "D19 / part E" in row[-1]
    assert "NONE" not in row[-1]


def test_no_blanket_approval_of_remaining_section_four_rows():
    inventory = section(TABLE.read_text(encoding="utf-8"), 4)
    audited_rows = [row for row in rows(inventory) if len(row) == 4]
    covered = {tuple(row_for(inventory, fragment)) for fragment in D19_RESULTS}
    restored_or_c7 = {
        tuple(row_for(inventory, "http_probe without target host")),
        tuple(row_for(inventory, "prompt consumer label")),
        tuple(row_for(inventory, "checkpoint description")),
        tuple(row_for(inventory, "invalid mapping guidance")),
    }
    remaining = [row for row in audited_rows if tuple(row) not in covered | restored_or_c7]
    assert remaining, "The pending inventory must not disappear into generic approval."
    assert all("NONE" in row[-1] and "D19" not in row[-1] for row in remaining)
    actual_d19 = {tuple(row) for row in audited_rows if "D19" in row[-1]}
    assert actual_d19 == covered


@pytest.mark.parametrize(
    "fragment",
    (
        "Conversation artifact publication is unavailable until Phase 2.",
        "Phase 2 background request admission and delivery is not implemented.",
        "Tool unavailable: '{name}' has no ready handler",
        "Output retention unavailable: no authenticated executor consumer",
        "Conversation delivery is unavailable until Phase 2 wiring.",
        "Approved isolated skill dependency installation is unavailable in Phase 1.",
        "DependencyError: skill dependencies unavailable",
        "empty adapter read",
        "generated-image URL suffix and status metadata",
        "Full report attached ({len(task.results)} steps).",
        "Full summary attached.",
        "Config validation failed: unsupported top-level configuration fields",
    ),
)
def test_key_leftovers_remain_none(fragment: str):
    row = row_for(section(TABLE.read_text(encoding="utf-8"), 4), fragment)
    assert "NONE" in row[-1]


def test_c4_labels_and_http_fallback_are_restorations_not_d19():
    inventory = section(TABLE.read_text(encoding="utf-8"), 4)
    expected_labels = {
        "prompt consumer label": "`Chat, conversation, and loop prompts`",
        "checkpoint description": "`Checkpoint conversation turns so they survive an outage.`",
    }
    for selector, expected in expected_labels.items():
        row = row_for(inventory, selector)
        assert row[2] == expected
        assert "D7-C, C4" in row[-1]
        assert "NONE" not in row[-1] and "D19" not in row[-1]
    row = row_for(inventory, "http_probe without target host")
    assert "127.0.0.1" in row[1] and "_exec_command" in row[1]
    assert "Restored local fallback for the authenticated owner" in row[2]
    assert "refusal is removed" in row[2]
    assert "D17 restored baseline, not a new approval" in row[-1]
    assert "explicit-host and omitted-host" in row[-1]


@pytest.mark.parametrize(
    ("selector", "expected", "approval"),
    (
        (
            "post_message docstring",
            "Send a message to the conversation that invoked this skill.",
            "D7-C, C6 SkillContext rule",
        ),
        (
            "Same file, post_file docstring",
            "Send a binary file to the conversation that invoked this skill.",
            "D7-C, C6 SkillContext rule",
        ),
        ("search_history docstring", "Search conversation history.", "D19 / part E"),
        (
            "search_history result field docstring",
            "Returns list of {type, content, timestamp, conversation_id}.",
            "D19 / part E",
        ),
        (
            "get_hosts docstring (part E calls it list_hosts)",
            "List host aliases admitted by the authenticated owner context.",
            "D19 / part E",
        ),
    ),
)
def test_skillcontext_documentation_has_precise_coverage(
    selector: str, expected: str, approval: str
):
    row = row_for(section(TABLE.read_text(encoding="utf-8"), 5), selector)
    assert expected in row[2]
    assert approval in row[-1] and "NONE" not in row[-1]
    if selector.startswith("get_hosts"):
        assert "actual Python method is get_hosts, no method rename" in row[-1]


def test_non_runtime_documentation_leftovers_are_not_silently_approved():
    inventory = section(TABLE.read_text(encoding="utf-8"), 5)
    for selector in (
        "skill configuration help", "schedule_task docstring", "list_schedules docstring"
    ):
        assert "NONE" in row_for(inventory, selector)[-1]


def test_skill_history_opening_was_already_conversation_in_baseline():
    row = row_for(section(TABLE.read_text(encoding="utf-8"), 5), "search_history docstring")
    assert row[1].startswith("`Search conversation history.")
    assert row[2].startswith("`Search conversation history.")
    assert "channel_id" in row[1] and "conversation_id" in row[2]
    assert "only the result field changes" in row[-1]


def test_internal_lifecycle_inventory_remains_without_wording_approval():
    inventory = section(TABLE.read_text(encoding="utf-8"), 4)
    internal = inventory.split("### Internal control/storage and lifecycle diagnostics", 1)[1]
    assert "Each has **NONE** for exact wording approval" in internal
    for selector in (
        "store/record/control validation",
        "`src/__main__.py`, main",
        "`src/cli.py`, main",
        "`src/restart.py`, relaunch",
        "`src/setup_wizard.py`, setup",
        "delivery readiness",
        "`src/web/api/__init__.py`, shared stub",
    ):
        row = row_for(internal, selector)
        assert len(row) == 3
        assert "D19" not in " ".join(row)


@pytest.mark.parametrize("path", ("docs/design/roadmap.md", "maintenance/test-plan.md"))
def test_phase_two_exit_has_complete_disposition_and_runtime_host_proofs(path: str):
    document = text(path)
    normalized = " ".join(document.split())
    for fragment in (
        "NONE row in section 4",
        "removed with Odin's behavior restored or explicitly dispositioned under D19",
        "wording swaps go to Claude",
        "behavior/instruction change",
        "goes to Aaron",
        '"unavailable" and "not implemented" gates',
        "readiness backstops",
        "attachment suffix or image URL",
        "skill dependency installation",
        "resume empty-read disposition",
        "same local host and default host as an Odin install",
        "runtime parity",
        "explicit-host and omitted-host",
        "authenticated-owner local fallback",
        "No model request path is",
        "wired in Phase 1",
        "deferred",
        "no Phase 2 runtime parity",
    ):
        assert fragment in normalized, (path, fragment)
    assert "326 Phase-2-deferred suites" in document
    assert "never dropped" in document


def test_summary_uses_current_approval_sha_and_truthful_static_limits():
    document = TABLE.read_text(encoding="utf-8")
    readme = text("maintenance/README.md")
    for content in (document, readme):
        assert APPROVAL_SHA in content and "D19" in content
        assert "NONE" in content
        assert "No model request path is wired in Phase 1" in content
    assert "5993851093" in document
    assert "Historical round-2 local validation" in document
    assert "documentation/static checks do not prove execution or host parity" in document
    assert "D17" in readme and "not new wording approval" in readme
    assert "Inventory completion is not blanket approval" in readme
    assert "ae8aaebb" not in document
