"""Fresh profile defaults and bounded owned logging, with temporary paths only."""

import logging
from pathlib import Path

from src.desktop.paths import ProfilePaths
from src.runtime_paths import runtime_profile_paths
from src.odin_log.logger import setup_logging
from src.planning.store import PlanStore
from src.scheduler.history import ScheduleHistory


def set_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("ODIN_DESKTOP_PROFILE", raising=False)
    for key, name in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                      ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(key, str(tmp_path / name))
    return ProfilePaths.from_xdg()


def test_default_plan_and_schedule_history_use_fresh_xdg_at_construction(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    plans = PlanStore()
    history = ScheduleHistory()
    assert plans._path == paths.data_dir / "plans.json"
    assert history.path == paths.data_dir / "schedule_history.jsonl"
    assert not (tmp_path / "plans.json").exists()


def test_explicit_paths_remain_injected(tmp_path):
    assert PlanStore(str(tmp_path / "plans.json"))._path == tmp_path / "plans.json"
    assert ScheduleHistory(str(tmp_path / "history.jsonl")).path == tmp_path / "history.jsonl"


def test_selected_profile_is_used_by_default_stores(monkeypatch, tmp_path):
    set_xdg(monkeypatch, tmp_path)
    monkeypatch.setenv("ODIN_DESKTOP_PROFILE", "independent")
    paths = runtime_profile_paths()
    assert paths.profile_id == "independent"
    assert PlanStore()._path == paths.data_dir / "plans.json"
    assert ScheduleHistory().path == paths.data_dir / "schedule_history.jsonl"


def test_default_profile_directories_are_private(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    PlanStore()
    ScheduleHistory()
    assert paths.data_dir.stat().st_mode & 0o777 == 0o700


def test_logging_reinitialization_retires_only_owned_handlers(monkeypatch, tmp_path):
    paths = set_xdg(monkeypatch, tmp_path)
    root = logging.getLogger("odin")
    previous = list(root.handlers)
    root.handlers.clear()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        setup_logging()
        first = [h for h in root.handlers if getattr(h, "_odin_core_owned", False)]
        setup_logging()
        second = [h for h in root.handlers if getattr(h, "_odin_core_owned", False)]
        assert foreign in root.handlers
        assert len(second) == 2
        assert not any(h in root.handlers for h in first)
        files = [h for h in second if hasattr(h, "baseFilename")]
        assert len(files) == 1
        assert Path(files[0].baseFilename) == paths.data_dir / "logs" / "odin.log"
        assert files[0].maxBytes * (files[0].backupCount + 1) == 50 * 1024 * 1024
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler is not foreign:
                handler.close()
        root.handlers.extend(previous)
