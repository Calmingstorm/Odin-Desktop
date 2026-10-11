"""Portable harness contract checks; native results come only from Windows CI."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "windows_runtime_acceptance", ROOT / "scripts/packaging/windows-runtime-acceptance.py")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_cold_environment_does_not_inherit_python_trust_proxy_or_user_settings(tmp_path):
    ambient = {"SystemRoot": "C:/Windows", "PATH": "malicious", "PYTHONPATH": "host",
               "CURL_CA_BUNDLE": "host.pem", "HTTPS_PROXY": "host", "SECRET": "hidden",
               "LOCALAPPDATA": "real-user", "GITHUB_TOKEN": "hidden", "PATHEXT": ".COM;.EXE",
               "ProgramData": "C:/ProgramData"}
    env = HARNESS.cold_environment(tmp_path / "work", tmp_path / "resources", ambient)
    assert env["PATH"] == "C:/Windows/System32"
    assert env["PATHEXT"] == ".COM;.EXE"  # PowerShell runs curl.exe only with it
    assert env["ProgramData"] == "C:/ProgramData"  # the bundled OpenSSH needs it
    unwanted = {"PYTHONPATH", "CURL_CA_BUNDLE", "HTTPS_PROXY", "SECRET", "GITHUB_TOKEN"}
    assert not unwanted & env.keys()
    assert env["LOCALAPPDATA"] == str(tmp_path / "work/local")
    assert env["ODIN_DESKTOP_BUNDLE_ROOT"] == str(tmp_path / "resources/runtime")
    assert env["HF_HUB_OFFLINE"] == "1"


def test_profile_environment_differs_from_cold_only_by_the_real_profile(tmp_path):
    ambient = {"SystemRoot": "C:/Windows", "PYTHONPATH": "host", "CURL_CA_BUNDLE": "host.pem",
               "HTTPS_PROXY": "host", "USERPROFILE": "C:/Users/u",
               "LOCALAPPDATA": "C:/Users/u/AppData/Local", "APPDATA": "C:/Users/u/AppData/Roaming",
               "HOMEDRIVE": "C:", "HOMEPATH": "/Users/u"}
    cold = HARNESS.cold_environment(tmp_path, tmp_path / "resources", ambient)
    profile = HARNESS.profile_environment(tmp_path, tmp_path / "resources", ambient)
    differing = {key for key in cold.keys() | profile.keys() if cold.get(key) != profile.get(key)}
    assert differing == {"USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOMEDRIVE", "HOMEPATH"}
    assert profile["LOCALAPPDATA"] == "C:/Users/u/AppData/Local"
    assert not {"PYTHONPATH", "CURL_CA_BUNDLE", "HTTPS_PROXY"} & profile.keys()


def test_resource_snapshot_detects_extra_missing_and_changed_files(tmp_path):
    (tmp_path / "one").write_bytes(b"one")
    before = HARNESS.digest_tree(tmp_path)
    (tmp_path / "two").write_bytes(b"two")
    assert HARNESS.digest_tree(tmp_path) != before
    (tmp_path / "two").unlink()
    assert HARNESS.digest_tree(tmp_path) == before
    (tmp_path / "one").write_bytes(b"changed")
    assert HARNESS.digest_tree(tmp_path) != before
    (tmp_path / "one").unlink()
    assert HARNESS.digest_tree(tmp_path) != before


def test_workflow_has_actual_stage_and_native_acceptance_not_just_source_tests():
    text = (ROOT / ".github/workflows/windows-engine.yml").read_text()
    assert "build-runtime.py" in text
    assert "windows-runtime-acceptance.py" in text
    assert "windows-runtime-acceptance.json" in text


def test_loaded_modules_are_judged_by_origin(monkeypatch):
    # A redistributable is fine from the bundle and a failure from anywhere else: Windows' own
    # copy on a developer machine would mask a missing bundled one.
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    bundle = r"C:\Users\u\AppData\Local\Programs\Odin\resources"
    digest = "0" * 64
    result = HARNESS.classify_modules([
        bundle + r"\runtime\python\python.exe",
        bundle + r"\runtime\python\VCRUNTIME140.dll",
        r"C:\WINDOWS\System32\kernel32.dll",
        r"C:\Windows\System32\msvcrt.dll",  # inbox, not the VC++ redistributable
        r"C:\Windows\System32\ucrtbase.dll",
        r"C:\Windows\System32\MSVCP140.dll",
        r"C:\Program Files\Other\vcruntime140_1.dll",
        r"C:\Windows\System32\libcrypto-3-x64.dll",
        r"C:\Users\u\AppData\Local\odin-desktop\default\data\resources\pdf" + "\\" + digest
        + r"\pymupdf\_mupdf.pyd",
        r"C:\ProgramData\Microsoft\Windows Defender\Platform\4.18\MpOav.dll",
        r"C:\Users\u\AppData\Local\Programs\Odin\resources-old\x.dll",  # a sibling, not inside
    ], bundle)
    counts = [len(result[key]) for key in ("bundle", "windows", "extracted_into_the_profile")]
    assert counts == [2, 3, 1]
    assert result["redistributable_from_outside_the_bundle"] == [
        r"C:\Windows\System32\MSVCP140.dll", r"C:\Program Files\Other\vcruntime140_1.dll",
        r"C:\Windows\System32\libcrypto-3-x64.dll"]
    assert result["other"] == [
        r"C:\ProgramData\Microsoft\Windows Defender\Platform\4.18\MpOav.dll",
        r"C:\Users\u\AppData\Local\Programs\Odin\resources-old\x.dll"]


def walk(items, ending, *, opened=True):
    """observe() over a fake Toolhelp: items, then the last error the API reports."""
    queue = list(items)
    state = {}

    def first(handle):
        return step(handle)

    def step(handle):
        if queue:
            state["current"] = queue.pop(0)
            return True
        return False

    return HARNESS.observe(lambda: "handle" if opened else None, first, step,
                           lambda: state["current"], lambda: ending, lambda handle: None)


def test_a_walk_is_complete_only_when_the_api_says_there_are_no_more():
    assert walk(["a", "b"], 18) == {"status": "complete", "items": ["a", "b"]}
    assert walk([], 18) == {"status": "complete", "items": []}
    assert walk(["a"], 31) == {"status": "failed", "error": 31, "items": ["a"]}  # after one
    assert walk([], 5) == {"status": "failed", "error": 5, "items": []}
    assert walk(["a"], 18, opened=False) == {"status": "unreadable", "items": []}


BUNDLE = r"C:\Users\u\AppData\Local\Programs\Odin\resources"
CHROME = BUNDLE + r"\runtime\browser\shell\chrome-headless-shell.exe"
NODE = BUNDLE + r"\runtime\python\Lib\site-packages\playwright\driver\node.exe"
SANDBOXED = {"integrity": "S-1-16-0", "restricted": True, "appcontainer": False}
PLAIN = {"integrity": "S-1-16-8192", "restricted": False, "appcontainer": False}


def complete(image):
    return {"status": "complete", "items": [image, r"C:\Windows\System32\ntdll.dll"]}


def process(image, command, token=PLAIN, modules=None, pid=1):
    kind = None if command is None else (command.split("--type=")[1].split()[0]
                                         if "--type=" in command else "main")
    return {"image": image, "pid": pid, "command_line": command, "type": kind,
            "no_sandbox_flag": None if command is None else "--no-sandbox" in command,
            "token": token, "modules": complete(image) if modules is None else modules}


def healthy():
    return [process(NODE, "node.exe cli.js", pid=1), process(CHROME, "chrome --headless", pid=2),
            process(CHROME, "chrome --type=gpu-process", pid=3),
            process(CHROME, "chrome --type=renderer", SANDBOXED, pid=4)]


def judge(rows, listing="complete"):
    return HARNESS.judge_browser({"listing": {"status": listing}, "processes": rows}, BUNDLE)


def refused(rows, listing="complete"):
    try:
        judge(rows, listing)
    except AssertionError:
        return True
    return False


def test_the_browser_verdict_needs_every_relevant_process_fully_observed(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    judged = judge(healthy())
    assert [row["type"] for row in judged] == ["main", "main", "gpu-process", "renderer"]
    renderer = healthy()[3]
    assert refused(healthy()[:3] + [{**renderer, "modules": {"status": "unreadable",
                                                             "items": []}}])
    assert refused(healthy()[:3] + [{**renderer, "modules": {"status": "complete",
                                                             "items": []}}])
    assert refused(healthy()[:3] + [{**renderer, "modules": {
        "status": "failed", "error": 31, "items": [CHROME]}}])  # failed after a valid module
    assert refused(healthy()[:3] + [{**renderer, "modules": {  # its own image missing
        "status": "complete", "items": [r"C:\Windows\System32\ntdll.dll"]}}])
    assert refused(healthy()[:3] + [{**renderer, "modules": {"status": "complete", "items": [
        CHROME, r"C:\Windows\System32\MSVCP140.dll"]}}])
    # One healthy renderer doesn't qualify another Chromium process it couldn't classify.
    assert refused(healthy() + [process(CHROME, None, {}, pid=9)])
    assert refused(healthy()[:3] + [process(CHROME, "chrome --type=renderer", PLAIN, pid=4)])
    assert refused(healthy()[:1] + [process(CHROME, "chrome --headless --no-sandbox", pid=2)]
                   + healthy()[2:])
    assert refused([{**healthy()[0], "modules": {"status": "unreadable", "items": []}}]
                   + healthy()[1:])
    assert refused(healthy()[:3])  # no renderer at all
    assert refused(healthy(), listing="failed")

