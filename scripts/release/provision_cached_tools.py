#!/usr/bin/env python3
"""Select release interpreters already installed on a self-hosted runner.

This helper never downloads or installs runtimes. It validates tool-cache
entries and, when requested, falls back to a system Node 22 executable.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _version(executable, code):
    result = subprocess.run(
        [str(executable), *code], capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode:
        return None
    return result.stdout.strip()


def cached_python(tool_cache):
    if not tool_cache:
        raise RuntimeError("RUNNER_TOOL_CACHE is unset; cached Python 3.12 is required.")
    root = Path(tool_cache) / "Python"
    versions = []
    if root.is_dir():
        for marker in root.glob("3.12.*/x64.complete"):
            version = marker.parent.name
            executable = marker.parent / "x64/bin/python"
            valid = len(version.split(".")) == 3 and version.startswith("3.12.")
            if not (valid and version[5:].isdigit()):
                continue
            if marker.is_file() and executable.is_file() and os.access(executable, os.X_OK):
                versions.append((tuple(map(int, version.split("."))), version, executable))
    for _, expected, executable in sorted(versions, reverse=True):
        code = 'import sys; print(".".join(map(str, sys.version_info[:3])))'
        actual = _version(executable, ["-c", code])
        # Workflow/build entrypoints invoke python3 by name after GITHUB_PATH.
        # A lone bin/python must not silently select a different system python3.
        python3 = executable.with_name("python3")
        if (actual == expected and python3.is_file() and os.access(python3, os.X_OK)
                and _version(python3, ["-c", code]) == expected):
            return executable
    raise RuntimeError(
        "Provision Python 3.12 in this runner's tool cache; CI will not download it."
    )


def _node22(executable):
    actual = _version(executable, ["--version"])
    return executable if actual and re.fullmatch(r"v22\.\d+\.\d+", actual) else None


def cached_node(tool_cache):
    if not tool_cache:
        raise RuntimeError("RUNNER_TOOL_CACHE is unset; cached Node.js 22 is required.")
    root = Path(tool_cache) / "node"
    candidates = []
    if root.is_dir():
        for marker in root.glob("22.*/x64.complete"):
            version = marker.parent.name
            if re.fullmatch(r"22\.\d+\.\d+", version):
                executable = marker.parent / "x64/bin/node"
                if marker.is_file() and executable.is_file() and os.access(executable, os.X_OK):
                    candidates.append((tuple(map(int, version.split("."))), executable))
    for version, executable in sorted(candidates, reverse=True):
        actual = _version(executable, ["--version"])
        if actual == "v" + ".".join(map(str, version)):
            return executable
    system = shutil.which("node")
    if system and _node22(system):
        return Path(system)
    raise RuntimeError(
        "Provision Node.js 22 in the runner tool cache or system PATH; CI will not download it."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-node", action="store_true")
    args = parser.parse_args(argv)
    try:
        python = cached_python(os.environ.get("RUNNER_TOOL_CACHE", ""))
        node = cached_node(os.environ.get("RUNNER_TOOL_CACHE", "")) if args.require_node else None
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"python={python}\n")
            if node:
                stream.write(f"node={node}\n")
    path_file = os.environ.get("GITHUB_PATH")
    if path_file:
        with open(path_file, "a", encoding="utf-8") as stream:
            stream.write(f"{python.parent}\n")
            if node:
                stream.write(f"{node.parent}\n")
    print(f"Using cached Python: {python}")
    if node:
        print(f"Using available Node.js: {node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
