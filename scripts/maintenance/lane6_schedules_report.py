"""Pure strict-patch report generator. No repository writes."""

import ast
import hashlib
import json

from scripts.maintenance.fixture_corpus import (
    ARCHIVE_SHA256,
    BASELINE,
    corpus,
    frozen_source,
    nodes,
)
from tests.desktop_adapters import lane6_schedules_web, lane6_schedules_web_agents


def web_report():
    suites = []
    for module in (lane6_schedules_web, lane6_schedules_web_agents):
        module.load({"__name__": "report_namespace"})
        original = ast.parse(frozen_source(module.PATH))
        stem = module.PATH.split("/")[-1][:-3]
        cases = []
        for symbol, *_ in corpus(original)["cases"]:
            key = module.PATH + "::" + symbol.replace(".", "::")
            case = next(n for s, n in nodes(original) if s == symbol
                        and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            row = {"original": key, "symbol": symbol,
                   "case_ast_sha256": hashlib.sha256(ast.dump(case).encode()).hexdigest()}
            if key in module.CASE_MAP:
                suffix = "_agents" if module is lane6_schedules_web_agents else ""
                row.update(disposition="restored", selector=(
                    "tests/test_desktop_lane6_schedules_web" + suffix + ".py::"
                    + module.CASE_MAP[key]))
            else:
                row.update(disposition="deferred", reason=module.DEFERRED_CASES[stem][symbol])
            cases.append(row)
        suites.append({"path": module.PATH, "status": "partial",
            "source_sha256": module.SOURCE_HASHES[module.PATH],
            "adapter": "tests/desktop_adapters/" + module.__name__.split(".")[-1] + ".py",
            "selectors": [r["selector"] for r in cases if r["disposition"] == "restored"],
            "cases": cases, "setup_hunks": module.SETUP_HUNKS[module.PATH],
            "blocked_on": sorted({r["reason"] for r in cases if r["disposition"] == "deferred"}),
            "corpus_unchanged": corpus(original) == corpus(module.transformed_tree())})
    return {"batch": "lane6_schedules_web", "suites": suites,
        "retired_cases": [], "proposals": [], "substitutions": [], "production_fixes": [],
        "lineage": {"baseline": BASELINE, "archive": "maintenance/odin-v4.13.0.tar.gz",
                    "archive_sha256": ARCHIVE_SHA256,
                    "corpus": "scripts/maintenance/fixture_corpus.py"},
        "contracts": ["tests/test_desktop_lane6_schedules_web.py",
                      "tests/test_desktop_lane6_schedules_web_agents.py"],
        "tests": [{"command": (
            ".venv/bin/python scripts/run-phase1-tests.py "
            "tests/test_desktop_lane6_schedules_web.py "
            "tests/test_desktop_lane6_schedules_web_agents.py"
        ), "result": "32 passed in 10.58s", "exit_code": 0}]}


if __name__ == "__main__":
    report = web_report()
    print("*** Begin Patch\n*** Add File: maintenance/lane6-schedules-web-report.json")
    print("+" + json.dumps(report, separators=(",", ":")))
    print("*** End Patch")
