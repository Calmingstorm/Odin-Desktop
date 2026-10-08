"""Grouped settings publish canonical authority, not inferred parents."""
from copy import deepcopy

import pytest

from src.config.apply_registry import build_field_record, build_meta_payload, schema_facts
from src.config.schema import Config

MAPS = (
    "openai_compatible.model_profiles",
    "openai_codex.context_budget_overrides",
    "sessions.context_budget_overrides",
    "tools.governor.host_overrides",
)


def put(dump, path, value):
    parent = dump
    for segment in path.split(".")[:-1]:
        parent = parent[segment]
    parent[path.split(".")[-1]] = value


@pytest.mark.parametrize("populated", [False, True])
def test_grouped_maps_have_unique_authoritative_records(populated):
    dump = Config().model_dump()
    for path in MAPS:
        value = {}
        if populated:
            if path.endswith("model_profiles"):
                value = {"example": {"total_window_tokens": 10000, "max_output_tokens": 1000}}
            else:
                value = {"example": "strict" if path.endswith("host_overrides") else 4096}
        put(dump, path, value)
    payload = build_meta_payload(dump, boot_dump=deepcopy(dump))
    for path in MAPS:
        records = [field for field in payload["fields"] if field["path"] == path]
        assert len(records) == 1
        value = dump
        for segment in path.split("."):
            value = value[segment]
        expected = build_field_record(path, value, boot_value=value, has_boot=True)
        assert {key: val for key, val in records[0].items() if key != "record_members"} == expected
        assert records[0]["type"] == "object"
        assert records[0]["sensitivity"] == "public"
    assert sum(payload["status"]["counts"].values()) == len(payload["fields"])


def test_empty_profile_members_project_schema_facts_not_runtime_values():
    dump = Config().model_dump()
    put(dump, "openai_compatible.model_profiles", {})
    fields = build_meta_payload(dump)["fields"]
    parent = next(field for field in fields if field["path"] == MAPS[0])
    members = parent["record_members"]
    facts = schema_facts()
    expected_paths = {path for path in facts if path.startswith(f"{MAPS[0]}.")}
    assert {member["path"] for member in members} == expected_paths
    for member in members:
        canonical = facts[member["path"]]
        assert set(member) == {
            "path", "type", "enum", "constraints", "default", "nullable", "sensitivity"
        }
        for key in ("type", "enum", "constraints", "default"):
            assert member[key] == canonical.get(key)
        assert member["nullable"] == bool(canonical.get("nullable"))
        assert member["sensitivity"] == "public"


def test_grouped_parents_preserve_boot_comparison():
    dump = Config().model_dump()
    put(dump, "tools.governor.host_overrides", {"example": "strict"})
    boot = deepcopy(dump)
    put(boot, "tools.governor.host_overrides", {})
    fields = build_meta_payload(dump, boot_dump=boot)["fields"]
    parent = next(field for field in fields if field["path"] == "tools.governor.host_overrides")
    assert parent == build_field_record(
        "tools.governor.host_overrides", {"example": "strict"}, boot_value={}, has_boot=True
    )


def test_missing_or_malformed_maps_never_gain_invented_records():
    fields = build_meta_payload({"openai_compatible": {"model_profiles": "not-a-map"}})["fields"]
    assert {field["path"] for field in fields} == {"openai_compatible.model_profiles"}
    assert "record_members" not in fields[0]
