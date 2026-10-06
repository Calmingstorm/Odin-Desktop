"""Catalogue context-window counts remain writable public schema metadata."""
from src.config.sensitivity import is_sensitive_key, is_storage_sensitive_key


def test_context_window_count_is_public_without_weakening_token_credentials():
    assert not is_sensitive_key("total_window_tokens")
    assert not is_sensitive_key("TOTAL_WINDOW_TOKENS")
    assert is_sensitive_key("access_token")
    assert is_sensitive_key("refresh_token")
    assert is_sensitive_key("total_window_tokens_secret")
    assert is_storage_sensitive_key("access_token")
    assert is_storage_sensitive_key("refresh_token")
    assert not is_storage_sensitive_key("total_window_tokens")
