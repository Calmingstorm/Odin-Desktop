"""Odin 4.22.0 (PR #729) in Desktop: Odin's new and rewritten cases of frozen files.

Desktop keeps Odin's v4.13.0 test files byte for byte; Odin 4.22.0's cases for them run
here verbatim, with those files' own helpers.

- Branch freshness (#699) asks git for the branch's own upstream before fetching, so Odin
  rewrote eight cases of tests/test_branch_freshness.py for that question. The frozen cases
  are retired in tests/desktop_adapters/step8_6a_tools.py under their own reviewed authority
  (scripts/maintenance/phase2_suites.py ODIN_4220_*); Odin's 4.22.0 versions run here, with
  Odin's new TestFreshnessChecksTheTestsRepository class.
- apply_patch (#677): a hard-linked file's other link keeps its mode after a commit.
- Email (#688): an unknown charset label falls back to UTF-8.
- analyze_pdf (#701): an image-only PDF gets the no-text guidance (Odin's extended case; the
  frozen one still runs by its exact selector).
"""
from __future__ import annotations

import email as email_lib
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

from src.tools import email_client as ec
from src.tools.apply_patch import apply_plan, parse_patch
from src.tools.branch_freshness import check_branch_freshness, command_directory
from tests.test_apply_patch import _patch  # noqa: F401
from tests.test_handlers_files_docs import _binary, _fake_fitz, _tools  # noqa: F401


class TestCheckBranchFreshness:
    @pytest.mark.asyncio
    async def test_fresh_branch(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),    # rev-parse
            (0, "origin/master\n"),  # rev-parse @{u}
            (0, ""),            # fetch
            (0, "0\n"),         # rev-list
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is False
        assert status.commits_behind == 0
        assert status.local_branch == "master"
        assert status.remote_ref == "origin/master"

    @pytest.mark.asyncio
    async def test_stale_branch(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "main\n"),      # rev-parse
            (0, "origin/main\n"),  # rev-parse @{u}
            (0, ""),            # fetch
            (0, "7\n"),         # rev-list
        ])
        status = await check_branch_freshness(exec_fn, "10.0.0.1", "deploy")
        assert status.is_stale is True
        assert status.commits_behind == 7
        assert status.local_branch == "main"
        assert status.remote_ref == "origin/main"

    @pytest.mark.asyncio
    async def test_fetch_failure_still_checks(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),   # rev-parse
            (0, "origin/master\n"),  # rev-parse @{u}
            (1, "error\n"),    # fetch fails
            (0, "3\n"),        # rev-list still works (cached remote refs)
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is True
        assert status.commits_behind == 3
        assert status.fetch_failed is True

    @pytest.mark.asyncio
    async def test_fetch_exception_still_checks(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),
            (0, "origin/master\n"),  # rev-parse @{u}
            Exception("network error"),
            (0, "2\n"),
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is True
        assert status.commits_behind == 2
        assert status.fetch_failed is True

    @pytest.mark.asyncio
    async def test_rev_list_failure(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),
            (0, "origin/master\n"),  # rev-parse @{u}
            (0, ""),
            Exception("subprocess error"),
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is False
        assert status.error == "rev-list failed"

    @pytest.mark.asyncio
    async def test_rev_list_bad_output(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),
            (0, "origin/master\n"),  # rev-parse @{u}
            (0, ""),
            (0, "not-a-number\n"),
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is False
        assert status.commits_behind == 0


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_freshness_check_with_branch_name_spaces(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "  master  \n"),
            (0, "origin/master\n"),  # rev-parse @{u}
            (0, ""),
            (0, "2\n"),
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.local_branch == "master"
        assert status.is_stale is True

    @pytest.mark.asyncio
    async def test_freshness_check_empty_rev_list_output(self):
        exec_fn = AsyncMock(side_effect=[
            (0, "master\n"),
            (0, "origin/master\n"),  # rev-parse @{u}
            (0, ""),
            (0, "\n"),
        ])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.is_stale is False
        assert status.commits_behind == 0


class TestFreshnessChecksTheTestsRepository:
    """#699: the check ran git in Odin's own working directory (the install
    checkout) instead of the repository the failing test ran in."""

    @pytest.mark.parametrize(("command", "expected"), [
        ("cd /srv/app && pytest -q", "/srv/app"),
        ("cd '/srv/my app' && npm test", "/srv/my app"),
        ("cd -- repo; go test ./...", "repo"),
        ("pytest -q", None),
        ("cd $HOME/app && pytest", None),  # expansion is not re-run
        ("cd ~/app && pytest", None),
        ("cd a b && pytest", None),
        # Double quotes still expand: the probe must not cd into a literal
        # "$PROJECT_ROOT" while the command ran in the expanded directory.
        ('cd "$PROJECT_ROOT" && pytest', None),
        ('cd "${HOME}/repo" && pytest', None),
        ('cd "$(pwd)/sub" && pytest', None),
        ('cd "`pwd`" && pytest', None),
        ('cd "a\\b" && pytest', None),
        ('cd "/srv/my app" && pytest', "/srv/my app"),
        ('cd "~/app" && pytest', "~/app"),  # no tilde expansion inside quotes
        ("cd '$LITERAL' && pytest", "$LITERAL"),  # single quotes never expand
    ])
    def test_command_directory(self, command, expected):
        assert command_directory(command) == expected

    @pytest.mark.asyncio
    async def test_git_runs_in_the_tests_directory_against_its_upstream(self):
        seen = []

        async def exec_fn(address, command, user):
            seen.append(command)
            if "--abbrev-ref HEAD" in command:
                return 0, "feature\n"
            if "@{u}' 2>" in command and "rev-parse" in command:
                return 0, "origin/main\n"
            if "fetch" in command:
                return 0, ""
            return 0, "4\n"

        status = await check_branch_freshness(
            exec_fn, "127.0.0.1", "root", directory="/srv/my app")
        assert status.is_stale and status.commits_behind == 4
        assert status.local_branch == "feature" and status.remote_ref == "origin/main"
        assert all(c.startswith("cd -- '/srv/my app' && git ") for c in seen)
        assert not any("origin/feature" in c for c in seen)

    def test_a_backslash_escaped_target_uses_the_default_directory(self):
        assert command_directory("cd a\\ && pytest") is None

    @pytest.mark.asyncio
    async def test_a_failed_upstream_query_counts_as_no_upstream(self):
        exec_fn = AsyncMock(side_effect=[(0, "feature\n"), RuntimeError("ssh dropped")])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.error == "no upstream" and not status.is_stale

    @pytest.mark.asyncio
    async def test_a_branch_without_an_upstream_is_never_called_fresh_or_stale(self):
        exec_fn = AsyncMock(side_effect=[(0, "feature\n"), (128, "fatal: no upstream\n")])
        status = await check_branch_freshness(exec_fn, "127.0.0.1", "root")
        assert status.error == "no upstream" and not status.is_stale
        assert exec_fn.await_count == 2  # no fetch, no count

    @pytest.mark.asyncio
    async def test_the_check_shares_one_time_budget(self):
        import asyncio

        async def stalled(address, command, user):
            if "fetch" in command:
                await asyncio.sleep(3600)
            if "--abbrev-ref HEAD" in command:
                return 0, "main\n"
            return 0, "origin/main\n"

        status = await asyncio.wait_for(
            check_branch_freshness(stalled, "127.0.0.1", "root", timeout=0.05), 2)
        assert status.error == "timed out" and not status.is_stale

    @pytest.mark.asyncio
    async def test_executor_runs_the_check_where_the_test_ran(self):
        from src.config.schema import ToolsConfig
        from src.tools.executor import ToolExecutor

        executor = ToolExecutor(config=ToolsConfig(command_timeout_seconds=5))
        calls = []

        async def mock_exec_command(address, command, ssh_user, timeout=None,
                                    on_output=None, **kw):
            calls.append((command, kw.get("use_workspace")))
            if "pytest" in command:
                return 1, "3 failed, 10 passed"
            if "--abbrev-ref HEAD" in command:
                return 0, "feature\n"
            if "rev-parse" in command:
                return 0, "origin/main\n"
            if "fetch" in command:
                return 0, ""
            return 0, "2\n"

        executor._exec_command = mock_exec_command
        executor._resolve_host = lambda alias: ("127.0.0.1", "root", "linux")
        result = await executor.system_tools._handle_run_command(
            {"host": "local", "command": "cd /srv/app && pytest -q"})
        text = result[0] if isinstance(result, tuple) else result
        assert "feature is 2 commit(s) behind origin/main" in text
        git_calls = [c for c in calls if " git " in c[0]]
        assert git_calls and all(
            c[0].startswith("cd -- /srv/app && git ") and c[1] is True for c in git_calls)


def test_patching_a_hard_linked_file_keeps_the_other_links_mode(tmp_path):
    # The original inode is private only while it sits in the recovery slot.
    # Another hard link still names it after the commit and keeps its mode.
    target = tmp_path / "config.txt"
    target.write_text("old\n")
    target.chmod(0o644)
    alias = tmp_path / "alias.txt"
    os.link(target, alias)
    apply_plan(str(tmp_path), parse_patch(_patch("*** Update File: config.txt\n@@\n-old\n+new")))
    assert target.read_text() == "new\n" and target.stat().st_mode & 0o777 == 0o644
    assert alias.read_text() == "old\n"
    assert alias.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob(".odin-patch-*"))


class TestPureHelpers:
    def test_unknown_charset_labels_fall_back_instead_of_failing(self):
        # errors="replace" covers bad bytes, not an unknown codec name; a real
        # label such as unknown-8bit must not fail the read or the listing.
        assert ec._decode_header_value("=?unknown-8bit?b?SGVsbG8=?=") == "Hello"
        single = email_lib.message_from_string(
            "Content-Type: text/plain; charset=x-obsolete-encoding\r\n\r\nplain ascii body")
        assert ec._extract_body(single, 5000) == "plain ascii body"
        for subtype, expected in (("plain", "part body"), ("html", "[HTML content]\npart body")):
            multi = email_lib.message_from_string(
                "Content-Type: multipart/alternative; boundary=b\r\n\r\n"
                f"--b\r\nContent-Type: text/{subtype}; charset=unknown-8bit\r\n\r\n"
                "part body\r\n--b--\r\n")
            assert ec._extract_body(multi, 5000) == expected


class TestAnalyzePdf:
    async def test_page_selection_and_empty(self):
        with (
            patch.dict(sys.modules, {"fitz": _fake_fitz(pages=["one", "two", "three"])}),
            _binary(),
        ):
            out = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p", "pages": "2"})
            assert "Page 2" in out and "two" in out and "Page 1" not in out
        # a 0-page doc yields no parts → empty result → the no-text fallback
        with patch.dict(sys.modules, {"fitz": _fake_fitz(pages=[])}), _binary():
            out = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p"})
            assert "no extractable text" in out
        # a scanned (image-only) PDF: pages exist but none has text
        with patch.dict(sys.modules, {"fitz": _fake_fitz(pages=["", "  \n"])}), _binary():
            out = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p"})
            assert "no extractable text" in out and "## Page" not in out
        # one text page is enough to return the pages as before
        with patch.dict(sys.modules, {"fitz": _fake_fitz(pages=["", "words"])}), _binary():
            out = await _tools()._handle_analyze_pdf({"host": "s", "path": "/p"})
            assert "## Page 1" in out and "## Page 2\nwords" in out


import json  # noqa: E402

from scripts.maintenance import phase2_suites as checker  # noqa: E402
from scripts.maintenance.fixture_corpus import corpus  # noqa: E402
from tests.desktop_adapters.step8_6a_tools import CORPUS_EXCLUSIONS, adapted_tree  # noqa: E402

SOURCE_PATH = "tests/test_branch_freshness.py"
SOURCE_SHA256 = checker.ODIN_4220_CASE_SOURCE_SHA256[SOURCE_PATH]
RETIRED = sorted(checker.ODIN_4220_CASE_REASONS[SOURCE_PATH])


def _carried(rows):
    return [row for row in rows if row["reviewer"] == checker.ODIN_4220_REVIEWER]


def test_the_retirements_are_the_reviewed_source_pinned_ones():
    rows = CORPUS_EXCLUSIONS["test_branch_freshness"]
    assert [row["case"] for row in _carried(rows)] == RETIRED and len(RETIRED) == 8
    assert checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, rows)
    carried = _carried(rows)
    earlier = [row for row in rows if row not in carried]
    assert earlier and all(row["reviewer"] == checker.PART4_REVIEWER for row in earlier)
    for kept in ("TestCheckBranchFreshness.test_not_a_git_repo",
                 "TestIsTestCommand.test_pytest"):
        widened = [*rows, dict(carried[0], case=kept)]
        assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, widened)
    twice = [*rows, dict(earlier[0], reviewer=checker.ODIN_4220_REVIEWER)]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, twice)
    for field in ("reason", "source_sha256"):
        changed = [*earlier, dict(carried[0], **{field: "changed"}), *carried[1:]]
        assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, changed)
    missing = [*earlier, {k: v for k, v in carried[0].items() if k != "reason"}, *carried[1:]]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, missing)
    unsorted = [*earlier, *reversed(carried)]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, unsorted)
    # The earlier authority still holds its own rows exactly.
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                         [*earlier[1:], *carried])


def test_a_case_without_reviewed_authority_is_refused_even_with_a_null_reason():
    approved = _carried(CORPUS_EXCLUSIONS["test_branch_freshness"])[0]
    row = json.loads(json.dumps(dict(approved, case="TestCheckBranchFreshness.test_not_a_git_repo",
                                     reason=None)))
    assert row["reason"] is None
    assert not checker._odin_4220_case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                                   [row])
    assert checker._odin_4220_case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                               [approved])


def test_the_earlier_authorities_still_refuse_these_cases():
    carried = _carried(CORPUS_EXCLUSIONS["test_branch_freshness"])
    assert SOURCE_PATH not in checker.ODIN_4200_CASE_SOURCE_SHA256
    assert SOURCE_PATH not in checker.ODIN_4192_CASE_SOURCE_SHA256
    assert SOURCE_PATH not in checker.PR35_CASE_SOURCE_SHA256
    assert not checker._authority_case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                                   carried)


def test_every_other_frozen_case_still_runs_unchanged():
    original, adapted = adapted_tree("test_branch_freshness")
    assert corpus(original) == corpus(adapted)
    cases = {case for case, _, _ in corpus(original)["cases"]}
    assert set(RETIRED) <= cases
    assert checker._digest(checker._regular(checker.ROOT, SOURCE_PATH).read_bytes()) == (
        SOURCE_SHA256)
