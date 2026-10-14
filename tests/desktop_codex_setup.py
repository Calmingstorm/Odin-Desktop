"""Odin 4.14's Codex pool tests (#652) on Desktop: the same pool on the same synthetic file.

Odin's `setup` helper (tests/test_codex_account_mutation_regressions.py) also registers his web
API's Codex routes, which a Desktop core doesn't serve: its accounts are managed over the app's
connection (tests/test_desktop_codex_accounts.py). These copies return no app or routes; the rows,
pool, file and gateway are Odin's.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.llm import codex_auth as ca


def creds(account):
    return {"account_id": account, "access_token": f"synthetic-{account}",
            "refresh_token": f"synthetic-refresh-{account}", "expires_at": 9999999999}


def setup(tmp_path, rows):
    path = tmp_path / "canonical.json"
    path.write_text(json.dumps(rows))
    pool = ca.CodexAuthPool(str(path))
    gateway = SimpleNamespace(codex_client=SimpleNamespace(auth=pool), reload_codex=AsyncMock())
    bot = SimpleNamespace(llm_gateway=gateway, config=SimpleNamespace(
        openai_codex=SimpleNamespace(credentials_path=str(path))))
    return path, pool, bot, None, None
