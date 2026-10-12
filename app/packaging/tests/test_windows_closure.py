"""Pure closure selection and refusal checks, never host marker defaults."""
import copy
import sys
import tomllib
from pathlib import Path

import pytest

PYTHON = Path(__file__).resolve().parents[1] / "python"
sys.path.insert(0, str(PYTHON))
from windows_closure import (  # noqa: E402
    StageError,
    exact_artifacts,
    production_closure,
    select_wheel,
)


def fixture():
    artifact = {"url": "https://example.org/a-1.0-py3-none-any.whl",
                "hash": "sha256:" + "a" * 64, "size": 123}
    package = {"name": "a", "version": "1.0", "source": {"registry": "https://pypi.org/simple"},
               "wheels": [artifact]}
    root = {"name": "engine", "version": "1.0", "source": {"editable": "."},
            "dependencies": [{"name": "a"}]}
    return ({"requires-python": "==3.12.*", "package": [root, package]},
            {"name": "engine", "version": "1.0", "dependencies": ["a==1.0"]})


def test_actual_production_windows_closure():
    repo = PYTHON.parents[2]
    lock = tomllib.loads((repo / "uv.lock").read_text())
    project = tomllib.loads((repo / "pyproject.toml").read_text())["project"]
    closure = production_closure(lock, project)
    names = {item["name"] for item in closure}
    assert {"pip", "cryptography", "tzdata", "onnxruntime", "sqlite-vec"} <= names
    assert not {"pytest", "setuptools", "wheel", "pymupdf", "secretstorage", "jeepney"} & names
    assert all("win_amd64" in item["filename"] or "none-any" in item["filename"]
               for item in closure)


@pytest.mark.parametrize("source", [{"editable": "."}, {"git": "https://example.org/a"},
                                    {"url": "https://example.org/a.whl"}])
def test_no_third_party_source_fallback(source):
    lock, project = fixture()
    lock["package"][1]["source"] = source
    with pytest.raises(StageError, match="dependency_source"):
        production_closure(lock, project)


@pytest.mark.parametrize("case,code", [("missing", "locked_version_missing"),
                                      ("conflict", "locked_version_conflict"),
                                      ("marker", "marker_selection"),
                                      ("extras", "extras_selection"),
                                      ("abi", "python_abi")])
def test_graph_refusals(case, code):
    lock, project = fixture()
    if case == "missing":
        lock["package"].pop()
    if case == "conflict":
        lock["package"].append(copy.deepcopy(lock["package"][1]))
    if case == "marker":
        lock["package"][0]["dependencies"][0]["marker"] = "sys_platform == 'linux'"
    if case == "abi":
        lock["requires-python"] = ">=3.13"
    with pytest.raises(StageError) as error:
        production_closure(lock, project, ("pdf",) if case == "extras" else ())
    assert error.value.code == code
    assert set(error.value.as_dict()) == {"code", "package", "path", "detail"}


@pytest.mark.parametrize("filename", ["a-1.0-cp311-cp311-win_amd64.whl",
                                       "a-1.0-cp312-cp312-win32.whl",
                                       "a-1.0-cp312-cp312-manylinux_2_17_x86_64.whl"])
def test_wrong_os_arch_abi_no_sdist(filename):
    lock, _ = fixture()
    package = lock["package"][1]
    package["wheels"][0]["url"] = "https://example.org/" + filename
    package["sdist"] = {"url": "https://example.org/a.tar.gz"}
    with pytest.raises(StageError, match="wheel_unavailable"):
        select_wheel(package)


@pytest.mark.parametrize("field", ["hash", "size"])
def test_missing_artifact_pin(field):
    lock, _ = fixture()
    del lock["package"][1]["wheels"][0][field]
    with pytest.raises(StageError, match="pin_missing"):
        select_wheel(lock["package"][1])


def test_outside_closure_and_duplicate():
    lock, project = fixture()
    closure = production_closure(lock, project)
    for actual in ([], closure * 2, [{**closure[0], "name": "other"}]):
        with pytest.raises(StageError, match="closure_mismatch"):
            exact_artifacts(closure, actual)


def test_transitive_extra_selects_only_requested_edges():
    lock, project = fixture()
    project["dependencies"] = ["a[fast]==1.0"]
    second = copy.deepcopy(lock["package"][1])
    second["name"] = "b"
    second["wheels"][0]["url"] = "https://example.org/b-1.0-py3-none-any.whl"
    lock["package"].append(second)
    lock["package"][1]["optional-dependencies"] = {"fast": [{"name": "b"}]}
    closure = production_closure(lock, project)
    assert [p["name"] for p in closure] == ["a", "b"]
    assert closure[0]["extras"] == ["fast"]
    assert closure[0]["selected_dependencies"] == ["b"]


def test_unknown_transitive_extra_refused():
    lock, project = fixture()
    project["dependencies"] = ["a[notlocked]==1.0"]
    with pytest.raises(StageError, match="extras_selection"):
        production_closure(lock, project)


def test_engine_graph_root_must_be_reviewed_local_project():
    lock, project = fixture()
    lock["package"][0]["source"] = {"git": "https://example.org/engine"}
    with pytest.raises(StageError, match="dependency_source"):
        production_closure(lock, project)
