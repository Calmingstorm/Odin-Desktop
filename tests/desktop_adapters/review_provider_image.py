"""Frozen image corpus admission with honest mixed-suite blockers."""

from __future__ import annotations

import ast
import hashlib

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService

PATH = "tests/test_image_model_config_api.py"
SHA256 = "25a525b1f9b5b5b1c45aac61b61f34c814afafc57d4fc5c3f361e635da145a62"
CORPUS_SELECTIONS = {"test_image_model_config_api": None}
CORPUS_EXCLUSIONS = {}
BLOCKERS = {
    "test_operation_admin_only": (
        "Desktop has no multi-user HTTP api-token/admin policy; "
        "profile authority is not anonymous-token rejection."),
    "test_cancellation_publishes_only_durable_commit": (
        "Synchronous Desktop image intent has no awaited persistence "
        "(error, cancelled) result/publication contract."),
    "test_pin_uses_lock_current_state_and_preserves_concurrent_save": (
        "Desktop uses profile/file locks, not legacy async config_transaction; "
        "inventing a suspended request changes scheduling meaning."),
    "test_error_branches_and_audit_failure": (
        "Desktop image intent does not call the inherited diff-tracker hook; "
        "unused-hook fault injection would not test audit-failure isolation."),
}


def source_tree():
    source = frozen_source(PATH)
    if hashlib.sha256(source).hexdigest() != SHA256:
        raise AssertionError("image inherited bytes changed")
    return ast.parse(source, filename=PATH)


def inherited_corpus():
    return corpus(source_tree())


def export_whole_suite(namespace):
    source_tree()
    raise RuntimeError("Whole frozen image suite unavailable: " + "; ".join(BLOCKERS.values()))


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


def temporary_settings(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("# keep this\nimage:\n  openai:\n    outer_model: custom-outer\n")
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()))
    settings.schema()  # Complete lazy keyring hydration before identity snapshots.
    return settings
