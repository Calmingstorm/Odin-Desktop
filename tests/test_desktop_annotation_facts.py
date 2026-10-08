"""Closed Union metadata must describe the schema, not its first branch."""

from enum import Enum, IntEnum
from typing import Any, Literal, Optional, Union

import pytest

from src.config.apply_registry import _annotation_facts, build_field_record, schema_facts
from src.config.schema import OpenAICodexConfig, ReasoningEffort


class StringChoice(Enum):
    FIRST = "low"
    SECOND = "high"


class NumberChoice(IntEnum):
    FIRST = 1
    SECOND = 2


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (
            ReasoningEffort | Literal["auto"] | None,
            ["none", "low", "medium", "high", "xhigh", "max", "auto"],
        ),
        (Literal["automatic"] | StringChoice, ["automatic", "low", "high"]),
        (StringChoice | Literal["auto", "low"] | None, ["low", "high", "auto"]),
        (Union[Literal["low", "high"], Literal["high", "auto"]], ["low", "high", "auto"]),  # noqa: UP007 - exercise typing.Union
        (Optional[StringChoice], ["low", "high"]),  # noqa: UP045 - exercise typing.Optional
    ],
)
def test_finite_string_union_merges_stably_without_duplicates(annotation, expected):
    facts = _annotation_facts(annotation)
    assert facts["type"] == "string"
    assert facts["enum"] == expected
    assert facts.get("nullable", False) == (type(None) in getattr(annotation, "__args__", ()))


@pytest.mark.parametrize(
    "annotation, expected_type",
    [
        (str | Literal["auto"], "string"),
        (Literal["auto"] | str | None, "string"),
        (StringChoice | str, "string"),
        (Literal["auto"] | int, None),
        (int | Literal["auto"], None),
        (Literal["auto"] | Any, None),
        (Literal[1, 2], "integer"),
        (Literal[True, False], "boolean"),
        (Literal[1.5, 2.5], "number"),
        (NumberChoice, "integer"),
        (Literal[1, "1"], None),
        (Literal[False, "False"], None),
        (list[str] | Literal["auto"], None),
    ],
)
def test_unrestricted_or_mixed_types_never_publish_a_closed_string_enum(annotation, expected_type):
    assert _annotation_facts(annotation)["type"] == expected_type
    assert _annotation_facts(annotation)["enum"] is None


def test_literal_null_is_not_a_string_choice():
    assert _annotation_facts(Literal["none", None] | Literal["auto"]) == {
        "type": "string",
        "enum": ["none", "auto"],
        "nullable": True,
    }
    assert _annotation_facts(Literal[None]) == {"type": None, "enum": None, "nullable": True}
    assert _annotation_facts(Optional[Literal[None]])["nullable"] is True  # noqa: UP045 - typing.Optional coverage


def test_published_agent_effort_covers_every_schema_choice_and_keeps_policy_distinct():
    path = "openai_codex.agent_reasoning_effort"
    facts = schema_facts()[path]
    expected = ["none", "low", "medium", "high", "xhigh", "max", "auto"]
    assert facts["enum"] == expected
    assert facts["nullable"] is True
    assert facts["default"] == "auto"
    for choice in [*expected, None]:
        validated = OpenAICodexConfig(agent_reasoning_effort=choice)
        assert validated.agent_reasoning_effort == choice
        record = build_field_record(path, choice)
        assert record["enum"] == expected
        assert record["nullable"] is True
        assert record["desired"] == choice
    assert schema_facts()["openai_codex.reasoning_effort"]["enum"] == expected[:-1]
    with pytest.raises(ValueError):
        OpenAICodexConfig(agent_reasoning_effort="invented")
