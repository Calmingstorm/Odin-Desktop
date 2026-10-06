"""Whole inherited agent trajectory suite, including retained endpoint reads."""
import ast

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.desktop.trajectories import TrajectoriesService
from tests.desktop_adapters.lane6_trajectory_endpoint_parity import (
    CASE_MAP,
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    ENDPOINT_CASES,
    EVIDENCE,
    NAMED_METHODS,
    SOURCE_PATH,
    WRAPPER,
    adapted_tree,
    load,
)

load(globals())


def test_lane6_trajectory_endpoint_full_corpus_and_exact_mapping():
    original = ast.parse(frozen_source(SOURCE_PATH), filename=SOURCE_PATH)
    assert corpus(original) == corpus(adapted_tree())
    assert CORPUS_SELECTIONS == {"test_agent_trajectory": None}
    assert CORPUS_EXCLUSIONS == {}
    assert len(CASE_MAP) == len(corpus(original)["cases"])
    assert len(set(CASE_MAP.values())) == len(CASE_MAP)
    for name in ENDPOINT_CASES:
        assert CASE_MAP[f"{SOURCE_PATH}::TestAgentTrajectoryAPI::{name}"] == (
            f"{WRAPPER}::TestLane6Trajectory_AgentTrajectoryAPI::{name}")
    assert EVIDENCE[SOURCE_PATH]["whole_suite"] is True


def test_lane6_trajectory_endpoint_named_service_surface():
    # Missing retained methods are a real implementation blocker, not retirement.
    assert set(NAMED_METHODS.values()) <= TrajectoriesService.METHODS
