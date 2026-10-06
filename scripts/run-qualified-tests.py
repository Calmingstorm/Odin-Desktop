#!/usr/bin/env python3
"""Execute each reviewed Phase 1 group through the isolated namespace launcher."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = "maintenance/qualification-group-weights.json"


def assign_shards(groups, minutes, count):
    """Assign whole groups to `count` shards, longest measured cluster first.

    Each group lands in exactly one shard, so the shards together run the plan
    once. Groups that select the same test file always share a shard: its
    invocation-local once-only ownership then gives every node to the first such
    group in plan order, exactly as one unsharded run does. A group without a
    measurement takes the median measured duration.
    """
    measured = sorted(float(value) for value in minutes.values())
    default = measured[len(measured) // 2] if measured else 1.0

    def weight(index):
        return float(minutes.get(groups[index]["name"], default))

    parent = list(range(len(groups)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner = {}
    for index, group in enumerate(groups):
        for selector in group.get("files", ()):
            path = selector.split("::", 1)[0]
            if path in owner:
                parent[root(index)] = root(owner[path])
            else:
                owner[path] = index
    clusters = {}
    for index in range(len(groups)):
        clusters.setdefault(root(index), []).append(index)

    loads = [0.0] * count
    members = [[] for _ in range(count)]
    for cluster in sorted(clusters.values(), key=lambda c: (-sum(map(weight, c)), min(c))):
        shard = min(range(count), key=lambda s: (loads[s], s))
        loads[shard] += sum(map(weight, cluster))
        members[shard].extend(cluster)
    return [sorted(member) for member in members]


def parse_shard(arguments):
    """Return (K, N) for ["--shard", "K/N"], or None for other arguments."""
    if arguments[:1] != ["--shard"]:
        return None
    match = (re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", arguments[1])
             if len(arguments) == 2 else None)
    if not match or int(match[1]) > int(match[2]):
        raise SystemExit("--shard requires K/N with 1 <= K <= N")
    return int(match[1]), int(match[2])


def main(argv=None, *, deduplicate=True) -> int:
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    groups = plan["groups"]
    if not groups:
        raise SystemExit("No classified qualification groups")
    failures = []
    collection = []
    arguments_input = [] if argv is None else argv
    collect_only = arguments_input == ["--collect-only"]
    shard = None if collect_only else parse_shard(arguments_input)
    if arguments_input and not collect_only and shard is None:
        raise SystemExit("Only --collect-only or --shard K/N is supported")
    selected = set(range(len(groups)))
    if shard is not None:
        weights = ROOT / WEIGHTS
        minutes = json.loads(weights.read_text())["minutes"] if weights.exists() else {}
        selected = set(assign_shards(groups, minutes, shard[1])[shard[0] - 1])
    (ROOT / ".test-state").mkdir(mode=0o700, exist_ok=True)
    state_directory = tempfile.TemporaryDirectory(
        prefix="qualification-once-", dir=ROOT / ".test-state")
    once_state = Path(state_directory.name) / "seen.json"
    once_state.write_text(json.dumps({"seen": [], "groups": []}) + "\n")
    for index, group in enumerate(groups):
        files = group["files"]
        if not files or not group.get("reason"):
            raise SystemExit("Group lacks files or reviewed selection rationale")
        for path in files:
            relative = Path(path)
            if (relative.is_absolute() or ".." in relative.parts
                    or not str(path).startswith("tests/")):
                raise SystemExit("Unsafe test selection path")
        if index not in selected:
            continue
        arguments = [*files, "--tb=short"]
        excluded = group.get("exclude_expression")
        if excluded:
            arguments.extend(["-k", f"not ({excluded})"])
        xml = f".test-state/qualification-{index}.xml"
        arguments.append(f"--junitxml={xml}")
        if collect_only:
            arguments.extend(["--collect-only", "-p", "tests.test_desktop_qualification"])
        if deduplicate:
            arguments.extend(["-p", "scripts.qualification_once",
                              f"--qualification-once-state={once_state}"])
        print(f"Qualification group {index + 1}/{len(groups)}: {group['name']}", flush=True)
        result = subprocess.call(
            [sys.executable, str(ROOT / "scripts/run-phase1-tests.py"), *arguments],
            cwd=ROOT,
        )
        if result:
            failures.append({"name": group["name"], "exit_code": result})
        elif collect_only:
            captured = ROOT / ".test-state/qualification-collected.json"
            collection.extend(json.loads(captured.read_text())["cases"])
    if collect_only:
        # Replace once after all groups. A failed group must not forge a complete
        # corpus; callers inspect failed_groups before updating accounting.
        target = ROOT / ".test-state/qualification-collected.json"
        unique = {row["executable"]: row for row in collection}
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as file:
            json.dump({"schema_version": 1, "cases": list(unique.values())}, file, indent=2)
            file.write("\n")
        Path(file.name).replace(target)
    output = {"groups": len(groups), "failed_groups": failures}
    if shard is not None:
        output["shard"] = f"{shard[0]}/{shard[1]}"
        output["selected_groups"] = [groups[index]["name"] for index in sorted(selected)]
    if deduplicate:
        (ROOT / ".test-state/qualification-once-result.json").write_text(once_state.read_text())
    state_directory.cleanup()
    (ROOT / ".test-state/qualification-result.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
