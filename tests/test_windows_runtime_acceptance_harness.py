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
    assert env["PATH"] == str(Path("C:/Windows") / "System32")  # as the platform renders it
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
    return HARNESS.judge_browser({"listing": {"status": listing}, "processes": rows,
                                  "unreadable": [], "exited": [], "stale_links": []}, BUNDLE)


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


PYTHON = BUNDLE + r"\runtime\python\python.exe"
ROOT_PID = 100


class Table:
    """A process table for lineage_processes: pid -> (parent, image, created, command line,
    token). Hidden pids can't be read; gone pids vanish after the first listing."""

    def __init__(self, rows, hidden=(), gone=()):
        self.rows, self.hidden, self.gone = rows, set(hidden), set(gone)
        self.listings, self.read = 0, set()

    def processes(self):
        self.listings += 1
        return {"status": "complete", "items": [
            (pid, row[0]) for pid, row in self.rows.items()
            if self.listings == 1 or pid not in self.gone]}

    def image(self, pid):
        self.read.add(pid)
        return None if pid in self.hidden else self.rows[pid][1]

    def created(self, pid):
        return None if pid in self.hidden else self.rows[pid][2]

    def command_line(self, pid):
        return self.rows[pid][3]

    def token(self, pid):
        return self.rows[pid][4]

    def modules(self, pid):
        return complete(self.rows[pid][1])


def browser_rows(extra=None):
    rows = {ROOT_PID: (1, PYTHON, 1, "python -I", PLAIN),
            200: (ROOT_PID, NODE, 2, "node.exe cli.js", PLAIN),
            300: (200, CHROME, 3, "chrome --headless", PLAIN),
            301: (300, CHROME, 4, "chrome --type=gpu-process", PLAIN),
            302: (300, CHROME, 5, "chrome --type=renderer", SANDBOXED),
            900: (1, r"C:\Program Files\Unrelated\service.exe", 0, None, {})}
    return {**rows, **(extra or {})}


def lineage(table):
    return HARNESS.lineage_processes(BUNDLE, table, root=ROOT_PID)


def test_discovery_accounts_for_every_live_descendant_of_this_run(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    table = Table(browser_rows(), hidden={900})
    judged = HARNESS.judge_browser(lineage(table), BUNDLE)
    assert sorted(row["pid"] for row in judged) == [200, 300, 301, 302]
    assert 900 not in table.read  # outside the lineage: never read
    # One healthy renderer doesn't qualify another whose image can't be read while it lives.
    extra = browser_rows({303: (300, CHROME, 6, "chrome --type=renderer", SANDBOXED)})
    hidden = lineage(Table(extra, hidden={303}))
    assert hidden["unreadable"] == [{"pid": 303, "parent": 300}]
    assert refused_evidence(hidden)
    gone = lineage(Table(extra, hidden={303}, gone={303}))  # it exited while we looked
    assert gone["exited"] == [{"pid": 303, "parent": 300}] and not gone["unreadable"]
    HARNESS.judge_browser(gone, BUNDLE)


def test_a_reused_pid_link_is_left_out_and_strangers_or_helpers_are_judged(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    # Its parent pid is Chromium's, but it was created first: a reused pid, not a child.
    stale = lineage(Table(browser_rows({400: (300, r"C:\Other\tool.exe", 2, "x", {})})))
    assert [row["pid"] for row in stale["stale_links"]] == [400]
    HARNESS.judge_browser(stale, BUNDLE)
    stranger = browser_rows({500: (300, r"C:\Temp\other.exe", 7, "other", PLAIN)})
    assert refused_evidence(lineage(Table(stranger)))
    helper = browser_rows({501: (200, r"C:\Windows\System32\conhost.exe", 3, "conhost", {})})
    judged = HARNESS.judge_browser(lineage(Table(helper)), BUNDLE)
    assert {row["pid"] for row in judged} >= {501}


def refused_evidence(evidence):
    try:
        HARNESS.judge_browser(evidence, BUNDLE)
    except AssertionError:
        return True
    return False



def test_an_exited_parent_does_not_hide_a_live_child(monkeypatch):
    # Odin's round 6 case: parent 400 (under Node) can't be read and has exited, but its child
    # 401, an unsandboxed renderer with --no-sandbox, is still running: it must be judged.
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    bad = "chrome --type=renderer --no-sandbox"
    rows = browser_rows({400: (200, CHROME, 6, "chrome --type=utility", PLAIN),
                         401: (400, CHROME, 7, bad, PLAIN)})
    evidence = lineage(Table(rows, hidden={400}, gone={400}))
    assert evidence["exited"] == [{"pid": 400, "parent": 200}]
    assert 401 in [row["pid"] for row in evidence["processes"]]
    assert refused_evidence(evidence)
    # Bounded by the nearest readable ancestor: a "child" started before Node is a reused pid.
    rows = browser_rows({400: (200, CHROME, 6, "chrome --type=utility", PLAIN),
                         401: (400, CHROME, 1, bad, PLAIN)})
    stale = lineage(Table(rows, hidden={400}, gone={400}))
    assert [row["pid"] for row in stale["stale_links"]] == [401]
    HARNESS.judge_browser(stale, BUNDLE)
