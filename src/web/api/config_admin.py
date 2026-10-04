"""Neutral settings helpers. Phase 2 owns admission and effective-state wiring.

Require scoped settings/setup, secure durable publication, desired-versus-live
truth, consent revisions and supervised restart. No transport configuration.
"""
import hashlib
import json

import yaml

from ...config.persistence import active_config_path
from . import require_phase2


def _image_intent_revision(metadata: dict) -> str:
    return hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()


def _config_has_explicit_path(*segments: str) -> bool | None:
    """Inspect YAML keys without resolving values or exposing configuration content."""
    path = active_config_path()
    if path is None:
        return None
    try:
        node = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    for segment in segments:
        if not isinstance(node, dict):
            return False
        if segment not in node:
            return False
        node = node[segment]
    return True


def register_setup_wizard(*args, **kwargs):
    require_phase2("Fresh-profile setup")


def register_status_info(*args, **kwargs):
    require_phase2("Effective runtime status")


def register_quick_actions(*args, **kwargs):
    require_phase2("Supervised lifecycle actions")


def register_personality(*args, **kwargs):
    require_phase2("Personality settings")


def register_startup_diagnostics(*args, **kwargs):
    require_phase2("Startup report delivery")
