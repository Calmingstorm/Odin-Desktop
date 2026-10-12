"""The Windows release candidate: windows-release.yml's boundaries, windows_candidate.py's
checks."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/windows-release.yml").read_text())
_SPEC = importlib.util.spec_from_file_location(
    "windows_candidate", ROOT / "scripts/release/windows_candidate.py")
CANDIDATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CANDIDATE)

STEPS = WORKFLOW["jobs"]["candidate"]["steps"]
INSTALLER = "odin-desktop-1.0.6-candidate-x64-setup.exe"


def at(predicate) -> int:
    return next(index for index, step in enumerate(STEPS) if predicate(step))


def test_it_runs_only_by_hand_for_the_owner_and_never_takes_a_tag_push():
    events = WORKFLOW.get("on", WORKFLOW.get(True))
    assert set(events) == {"workflow_dispatch"}  # only release.yml takes tags
    assert events["workflow_dispatch"]["inputs"]["tag"]["required"] is True
    job = WORKFLOW["jobs"]["candidate"]
    assert "github.actor == 'Calmingstorm'" in job["if"]
    assert "github.repository == 'Calmingstorm/Odin-Desktop'" in job["if"]
    assert WORKFLOW["permissions"] == {}
    # GitHub's identity token, for the signing sign-in, is this job's only addition.
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["runs-on"] == "windows-2025"
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False


def test_actions_are_commit_pinned_and_no_expression_reaches_a_shell():
    for step in STEPS:
        if "uses" in step:
            assert re.search(r"@[0-9a-f]{40}$", step["uses"]), step["uses"]
        assert "${{" not in step.get("run", ""), step.get("name")
    checkout = STEPS[at(lambda step: "actions/checkout@" in step.get("uses", ""))]
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["ref"] == "refs/tags/${{ inputs.tag }}"


def test_the_tag_is_checked_then_built_with_release_provenance_accepted_receipted_and_kept():
    tag_format = at(lambda step: step.get("name") == "The input is a release tag")
    checkout = at(lambda step: "actions/checkout@" in step.get("uses", ""))
    validate = at(lambda step: "windows_candidate.py validate" in step.get("run", ""))
    build = at(lambda step: "build-windows.mjs" in step.get("run", ""))
    accept = at(lambda step: "windows-installer-acceptance.ps1" in step.get("run", ""))
    receipt = at(lambda step: "windows_candidate.py receipt" in step.get("run", ""))
    kept = at(lambda step: str(step.get("with", {}).get("name", "")).startswith(
        "release-candidate-windows-"))
    assert tag_format < checkout < validate < build < accept < receipt < kept
    assert STEPS[tag_format]["env"]["RELEASE_TAG"] == "${{ inputs.tag }}"
    assert STEPS[build]["env"]["ODIN_PACKAGING_RELEASE"] == "1"
    # The acceptance tests exactly the installer the receipt retains, named from the validated
    # version.
    assert "RELEASE_VERSION=$version" in STEPS[validate]["run"]
    assert "$env:GITHUB_ENV" in STEPS[validate]["run"]
    assert "odin-desktop-$env:RELEASE_VERSION-candidate-x64-setup.exe" in STEPS[accept]["run"]
    retained = STEPS[kept]
    assert "if" not in retained  # only once every earlier step passed
    assert retained["with"]["if-no-files-found"] == "error"
    assert retained["with"]["overwrite"] is False
    assert retained["with"]["compression-level"] == 0
    assert retained["with"]["retention-days"] == 30


def test_it_signs_in_the_release_environment_with_githubs_identity_and_no_stored_secret():
    job = WORKFLOW["jobs"]["candidate"]
    # The Azure identity's federated credential names this environment, which takes master alone.
    assert job["environment"] == "release-signing"
    login = STEPS[at(lambda step: "azure/login@" in step.get("uses", ""))]
    assert login["with"] == {"client-id": "${{ vars.AZURE_CLIENT_ID }}",
                             "tenant-id": "${{ vars.AZURE_TENANT_ID }}",
                             "allow-no-subscriptions": True}
    text = (ROOT / ".github/workflows/windows-release.yml").read_text()
    assert "secrets." not in text and "creds" not in text and "CLIENT_SECRET" not in text
    assert job["env"] == {"ODIN_SIGNING_ENDPOINT": "https://eus.codesigning.azure.net",
                          "ODIN_SIGNING_ACCOUNT": "Odin", "ODIN_SIGNING_PROFILE": "OdinDesktop",
                          "ODIN_SIGNING_PUBLISHER": "Aaron Charpentier"}


def test_the_tools_and_the_sign_in_come_before_a_build_that_signs_and_an_acceptance_that_checks():
    tools = at(lambda step: "provision-signing.py" in step.get("run", ""))
    login = at(lambda step: "azure/login@" in step.get("uses", ""))
    token = at(lambda step: "az account get-access-token" in step.get("run", ""))
    build = at(lambda step: "build-windows.mjs" in step.get("run", ""))
    accept = at(lambda step: "windows-installer-acceptance.ps1" in step.get("run", ""))
    receipt = at(lambda step: "windows_candidate.py receipt" in step.get("run", ""))
    # The access token is taken right after the sign-in, the last step before the build.
    assert tools < login < token == build - 1 < accept < receipt
    assert "https://codesigning.azure.net/.default" in STEPS[token]["run"]
    provision = STEPS[tools]["run"]
    assert "$env:GITHUB_ENV" in provision and "Get-AuthenticodeSignature" in provision
    assert "Microsoft Corporation" in provision and "Microsoft.NETCore.App 8." in provision
    assert STEPS[build]["env"]["ODIN_WINDOWS_SIGNING"] == "1"
    assert "-Publisher $env:ODIN_SIGNING_PUBLISHER" in STEPS[accept]["run"]
    assert "--publisher $env:ODIN_SIGNING_PUBLISHER" in STEPS[receipt]["run"]


def test_the_installer_name_is_electron_builders_for_the_version():
    config = yaml.safe_load((ROOT / "app/electron-builder.windows.yml").read_text())
    pattern = config["win"]["artifactName"]
    assert pattern.replace("${version}", "1.0.6").replace("${ext}", "exe") == INSTALLER
    assert CANDIDATE.installer_name("1.0.6") == INSTALLER


def project(tmp_path, version="1.0.6") -> Path:
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "package.json").write_text(json.dumps({"version": version}))
    return tmp_path


def git_said(head="a" * 40, tagged="a" * 40, status=""):
    def run(*args, root):
        if args == ("rev-parse", "HEAD"):
            return head
        if args[0] == "rev-parse":
            return tagged
        if args[0] == "status":
            return status
        raise AssertionError(args)
    return run


def test_the_release_source_copy_keeps_every_committed_path_within_windows_limits():
    # Release provenance builds from a git-object copy at <cache>\release-source-XXXXXXXX\
    # (tempfile's eight characters). The hosted runner's temp folder is D:\a\_temp, and Windows
    # refuses a path of 260 characters.
    build = STEPS[at(lambda step: "build-windows.mjs" in step.get("run", ""))]
    cache = build["env"]["ODIN_PACKAGING_CACHE"].replace("${{ runner.temp }}", "D:\\a\\_temp")
    copy = cache + "\\release-source-" + "x" * 8 + "\\"
    committed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                               capture_output=True).stdout.decode().split("\0")
    deepest = max(filter(None, committed), key=len)
    assert len(copy) + len(deepest) < 260, deepest


def test_release_provenance_accepts_the_stages_scratch_folder_and_nothing_else(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "build_runtime", ROOT / "app/packaging/build-runtime.py")
    build_runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_runtime)
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    (repo / "uv.lock").write_text("lock\n")
    (repo / "app" / "package-lock.json").write_text("{}\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "release"]):
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)
    clean = build_runtime.source_record(repo, "release")
    # The Windows build re-checks the source while its scratch folder is beside the stage.
    scratch = repo / (build_runtime.STAGE_SCRATCH + "a1b2c3d4") / "resources"
    scratch.mkdir(parents=True)
    (scratch / "python.exe").write_bytes(b"MZ")
    assert build_runtime.source_record(repo, "release") == clean
    (repo / "notes.txt").write_text("not committed\n")
    with pytest.raises(ValueError, match="clean committed revision"):
        build_runtime.source_record(repo, "release")


@pytest.mark.parametrize("tag", [
    "1.0.6", "v1.0", "v1.0.6-rc1", "v1.0.6\n", "v01.0.6", " v1.0.6", "V1.0.6", "v1.0.6/../x"])
def test_validate_refuses_what_isnt_a_release_tag(tmp_path, tag):
    with pytest.raises(CANDIDATE.CandidateError, match="not a release tag"):
        CANDIDATE.validate(tag, root=project(tmp_path), run=git_said())


@pytest.mark.parametrize(("version", "run", "reason"), [
    ("1.0.5", git_said(), "product version is 1.0.5"),
    ("1.0.6", git_said(tagged="b" * 40), "not v1.0.6's commit"),
    ("1.0.6", git_said(status=" M app/package.json"), "local changes"),
])
def test_validate_refuses_another_version_another_commit_or_local_changes(tmp_path, version,
                                                                          run, reason):
    with pytest.raises(CANDIDATE.CandidateError, match=reason):
        CANDIDATE.validate("v1.0.6", root=project(tmp_path, version), run=run)


def test_validate_against_a_real_repository(tmp_path):
    repo = project(tmp_path / "repo")

    def git(*args):
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e",
                        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                       check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "release")
    git("tag", "v1.0.6")
    assert CANDIDATE.validate("v1.0.6", root=repo) == "1.0.6"
    (repo / "app" / "package.json").write_text(json.dumps({"version": "1.0.6", "x": 1}))
    with pytest.raises(CANDIDATE.CandidateError, match="local changes"):
        CANDIDATE.validate("v1.0.6", root=repo)
    git("commit", "-q", "-am", "after the tag")
    with pytest.raises(CANDIDATE.CandidateError, match="not v1.0.6's commit"):
        CANDIDATE.validate("v1.0.6", root=repo)
    with pytest.raises(CANDIDATE.CandidateError, match="git rev-parse"):
        CANDIDATE.validate("v9.9.9", root=project(tmp_path / "other", "9.9.9"))


def accepted(tmp_path, checks=None, **changes) -> tuple[Path, Path]:
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    (candidates / INSTALLER).write_bytes(b"installer")
    report = tmp_path / "report.json"
    rows = [{"check": "a", "ok": True}, {"check": "b", "ok": True}] if checks is None else checks
    whole = {"mode": "orchestrate", "user": "runner", "failed": 0,
             "installer_sha256": hashlib.sha256(b"installer").hexdigest(), "checks": rows}
    # PowerShell writes the report with a byte order mark.
    report.write_text(json.dumps({**whole, **changes}), encoding="utf-8-sig")
    return candidates, report


def test_the_receipt_names_the_accepted_bytes_the_source_and_the_run(tmp_path):
    candidates, report = accepted(tmp_path)
    out = tmp_path / "out"
    record = CANDIDATE.receipt(
        "v1.0.6", candidates, report, out, root=project(tmp_path / "repo"), run=git_said(),
        env={"RELEASE_RUN_ID": "7", "RELEASE_ATTEMPT": "1", "RELEASE_WORKFLOW_SHA": "b" * 40})
    assert sorted(path.name for path in out.iterdir()) == [
        INSTALLER, "windows-candidate-receipt.json", "windows-installer-acceptance.json"]
    assert json.loads((out / "windows-candidate-receipt.json").read_text()) == record
    assert record["artifacts"] == [{"name": INSTALLER, "size": 9,
                                    "sha256": hashlib.sha256(b"installer").hexdigest()}]
    assert (record["version"], record["tag"], record["signed"]) == ("1.0.6", "v1.0.6", False)
    assert (record["source_sha"], record["workflow_sha"]) == ("a" * 40, "b" * 40)
    assert (record["run_id"], record["run_attempt"]) == ("7", "1")
    assert record["acceptance"] == {
        "report": "windows-installer-acceptance.json", "checks": 2, "failed": 0,
        "sha256": hashlib.sha256(report.read_bytes()).hexdigest()}


@pytest.mark.parametrize("checks", [[], [{"check": "a", "ok": True}, {"check": "b", "ok": False}]])
def test_no_receipt_without_a_passed_acceptance(tmp_path, checks):
    candidates, report = accepted(tmp_path, checks)
    with pytest.raises(CANDIDATE.CandidateError, match="acceptance didn't pass"):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out",
                          root=project(tmp_path / "repo"), run=git_said())
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("changes", [
    {"checks": [{"check": "a", "ok": "true"}]},  # a truthy string is not a passed check
    {"failed": 3},  # the report's own count of failures
    {"mode": "user"},  # a user-mode part, not the whole orchestrated run
    {"installer_sha256": hashlib.sha256(b"other bytes").hexdigest()},  # it tested other bytes
    {"installer_sha256": ""},
])
def test_no_receipt_unless_the_whole_run_passed_on_these_bytes(tmp_path, changes):
    candidates, report = accepted(tmp_path, **changes)
    with pytest.raises(CANDIDATE.CandidateError):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out",
                          root=project(tmp_path / "repo"), run=git_said())
    assert not (tmp_path / "out").exists()


def test_no_receipt_without_the_installer_or_over_an_existing_candidate(tmp_path):
    candidates, report = accepted(tmp_path)
    repo = project(tmp_path / "repo")
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out", root=repo,
                          run=git_said())
    (candidates / INSTALLER).unlink()
    with pytest.raises(CANDIDATE.CandidateError, match="no installer for 1.0.6"):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out2", root=repo,
                          run=git_said())


SIGNED = {"publisher": "Aaron Charpentier",
          "thumbprint": "C2DEDC993AD1DA831FA7AB180FA67879FC1F8C75"}


def test_a_signed_receipt_records_the_signer_the_acceptance_checked(tmp_path):
    candidates, report = accepted(tmp_path, signature=SIGNED)
    record = CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out",
                               publisher="Aaron Charpentier", root=project(tmp_path / "repo"),
                               run=git_said())
    assert record["signed"] is True
    assert record["signature"] == SIGNED
    assert json.loads((tmp_path / "out" / "windows-candidate-receipt.json").read_text()) == record


@pytest.mark.parametrize("signature", [
    None,  # the acceptance checked no signature
    {**SIGNED, "publisher": "Someone Else"},
    {**SIGNED, "thumbprint": ""},
    {**SIGNED, "thumbprint": "not a thumbprint"},
    "Aaron Charpentier",
])
def test_no_signed_receipt_without_the_named_signers_checked_signature(tmp_path, signature):
    candidates, report = accepted(tmp_path, signature=signature)
    with pytest.raises(CANDIDATE.CandidateError, match="didn't check a signature by"):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out",
                          publisher="Aaron Charpentier", root=project(tmp_path / "repo"),
                          run=git_said())
    assert not (tmp_path / "out").exists()


def test_an_unsigned_receipt_never_hides_a_checked_signature(tmp_path):
    repo = project(tmp_path / "repo")
    candidates, report = accepted(tmp_path, signature=SIGNED)
    with pytest.raises(CANDIDATE.CandidateError, match="no publisher was named"):
        CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "out", root=repo,
                          run=git_said())
    (tmp_path / "unsigned").mkdir()
    candidates, report = accepted(tmp_path / "unsigned", signature=None)
    record = CANDIDATE.receipt("v1.0.6", candidates, report, tmp_path / "unsigned" / "out",
                               root=repo, run=git_said())
    assert record["signed"] is False and "signature" not in record


def test_the_command_line_reports_a_refusal_and_exits_1(capsys):
    assert CANDIDATE.main(["validate", "--tag", "v1.0"]) == 1
    assert "Windows candidate refused: not a release tag" in capsys.readouterr().err
