"""Select, never resolve, Windows CPython production wheels from uv.lock."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

ENVIRONMENT = {
    "implementation_name": "cpython", "implementation_version": "3.12.15",
    "os_name": "nt", "platform_machine": "AMD64", "platform_release": "11",
    "platform_system": "Windows", "platform_version": "10.0",
    "python_full_version": "3.12.15", "platform_python_implementation": "CPython",
    "python_version": "3.12", "sys_platform": "win32", "extra": "",
}
TAGS = tuple(cpython_tags((3, 12), abis=["cp312"], platforms=["win_amd64"])) + tuple(
    compatible_tags((3, 12), interpreter="cp312", platforms=["win_amd64"]))


class StageError(ValueError):
    """Stable sanitized refusal evidence."""

    def __init__(self, code: str, package: str = "", path: str = "", detail: str = ""):
        self.code, self.package, self.path, self.detail = code, package, path, detail
        super().__init__(f"{code}: {package}: {path}: {detail}")

    def as_dict(self) -> dict:
        return {"code": self.code, "package": self.package,
                "path": self.path, "detail": self.detail}


def marker_matches(marker: str | None, extras: set[str] | None = None) -> bool:
    if not marker:
        return True
    try:
        return any(Marker(marker).evaluate({**ENVIRONMENT, "extra": extra})
                   for extra in ({""} | (extras or set())))
    except Exception as exc:
        raise StageError("marker_invalid", detail=str(marker)) from exc


def validate_pin(pin: dict, package: str) -> None:
    for key in ("url", "sha256", "size", "license", "provenance"):
        if not pin.get(key):
            raise StageError("pin_missing", package, detail=key)
    if (urlsplit(pin["url"]).scheme != "https"
            or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
            or not isinstance(pin["size"], int) or isinstance(pin["size"], bool)
            or pin["size"] <= 0):
        raise StageError("pin_invalid", package)


def select_wheel(package: dict) -> dict:
    name, version = package["name"], package["version"]
    candidates = []
    for artifact in package.get("wheels", []):
        filename = unquote(urlsplit(artifact["url"]).path.rsplit("/", 1)[-1])
        try:
            wheel_name, wheel_version, _, tags = parse_wheel_filename(filename)
        except Exception as exc:
            raise StageError("wheel_name_invalid", name, filename) from exc
        if wheel_name != canonicalize_name(name) or wheel_version != Version(version):
            raise StageError("wheel_identity_mismatch", name, filename)
        rank = next((i for i, tag in enumerate(TAGS) if tag in tags), None)
        if rank is not None:
            if not str(artifact.get("hash", "")).startswith("sha256:"):
                raise StageError("pin_missing", name, detail="sha256")
            pin = {"name": name, "version": version, "filename": filename,
                   "url": artifact["url"], "sha256": artifact["hash"][7:],
                   "size": artifact.get("size"),
                   "provenance": package["source"]["registry"],
                   "license": "verified wheel METADATA and shipped notices"}
            validate_pin(pin, name)
            candidates.append((rank, filename, pin))
    if not candidates:
        raise StageError("wheel_unavailable", name,
                         detail="no CPython 3.12 win_amd64 wheel; no sdist fallback")
    return min(candidates, key=lambda item: item[:2])[2]


def production_closure(lock: dict, project: dict, extras: tuple[str, ...] = ()) -> list[dict]:
    """Reachable registry wheels; intentional runtime extras are empty.

    The editable engine lock node is a graph root, built separately into a
    noneditable wheel. Third-party editable/direct/VCS nodes always fail.
    """
    if extras:
        raise StageError("extras_selection", project["name"])
    if lock.get("requires-python") != "==3.12.*":
        raise StageError("python_abi", detail="uv.lock requires-python")
    index: dict[str, list[dict]] = {}
    for package in lock.get("package", []):
        index.setdefault(canonicalize_name(package["name"]), []).append(package)
    root_name = canonicalize_name(project["name"])
    roots = index.get(root_name, [])
    if len(roots) != 1 or roots[0].get("version") != project["version"]:
        raise StageError("locked_version_conflict", root_name)
    root = roots[0]
    if root.get("source") != {"editable": "."}:
        raise StageError("dependency_source", root_name,
                         detail="engine graph root must be the local reviewed project")
    try:
        requirements = [Requirement(value) for value in project.get("dependencies", [])]
    except Exception as exc:
        raise StageError("requirement_invalid", root_name) from exc
    active = {canonicalize_name(r.name): r for r in requirements
              if marker_matches(str(r.marker) if r.marker else None)}
    edges = {canonicalize_name(d["name"]): d for d in root.get("dependencies", [])
             if marker_matches(d.get("marker"))}
    if set(active) != set(edges):
        raise StageError("marker_selection", root_name)
    for requirement in active.values():
        if requirement.url:
            raise StageError("dependency_source", requirement.name)
    selected: dict[str, dict] = {}
    requested_extras: dict[str, set[str]] = {}
    visited: dict[str, frozenset[str]] = {}
    queue = [(edge, set(active[name].extras)) for name, edge in edges.items()]
    while queue:
        edge, extra = queue.pop(0)
        name = canonicalize_name(edge["name"])
        versions = [p for p in index.get(name, [])
                    if (not edge.get("version") or p["version"] == edge["version"])
                    and any(marker_matches(m) for m in p.get("resolution-markers", [""]))]
        if len(versions) != 1:
            code = "locked_version_conflict" if versions else "locked_version_missing"
            raise StageError(code, name)
        package = versions[0]
        if set(package.get("source", {})) != {"registry"}:
            raise StageError("dependency_source", name)
        if name in selected and selected[name]["version"] != package["version"]:
            raise StageError("locked_version_conflict", name)
        if name in active and Version(package["version"]) not in active[name].specifier:
            raise StageError("locked_version_conflict", name, detail="pyproject specifier")
        selected[name] = package
        requested_extras.setdefault(name, set()).update(extra)
        current = frozenset(requested_extras[name])
        if visited.get(name) == current:
            continue
        visited[name] = current
        dependencies = list(package.get("dependencies", []))
        for requested in current:
            if requested not in package.get("optional-dependencies", {}):
                raise StageError("extras_selection", name, detail=requested)
            dependencies.extend(package["optional-dependencies"][requested])
        for dependency in dependencies:
            if marker_matches(dependency.get("marker"), set(current)):
                queue.append((dependency, set(dependency.get("extra", []))))
    for forbidden in ("setuptools", "wheel", "uv", "pytest", "pymupdf"):
        if forbidden in selected:
            raise StageError("build_backend_leakage", forbidden)
    result = []
    for name in sorted(selected):
        dependencies = list(selected[name].get("dependencies", []))
        for extra in requested_extras[name]:
            dependencies.extend(selected[name].get("optional-dependencies", {}).get(extra, []))
        expected = sorted({canonicalize_name(d["name"]) for d in dependencies
                           if marker_matches(d.get("marker"), requested_extras[name])})
        result.append({**select_wheel(selected[name]), "extras": sorted(requested_extras[name]),
                       "selected_dependencies": expected})
    return result


def exact_artifacts(expected: list[dict], actual: list[dict]) -> None:
    expected_ids = {(p["name"], p["version"], p["sha256"]) for p in expected}
    actual_ids = {(p["name"], p["version"], p["sha256"]) for p in actual}
    if expected_ids != actual_ids or len(actual) != len(expected):
        raise StageError("closure_mismatch",
                         detail="missing, duplicate or outside selected closure")
