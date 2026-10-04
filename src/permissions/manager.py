"""Authenticated profile owner gate. No implicit or ambient privilege."""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..desktop.authority import OwnerAuthority, OwnerContext

_request_owner = contextvars.ContextVar("desktop_request_owner", default=None)


class PermissionManager:
    def __init__(self, authority: OwnerAuthority) -> None:
        self.authority = authority

    @staticmethod
    def set_request_owner(context: OwnerContext) -> contextvars.Token:
        return _request_owner.set(context)

    @staticmethod
    def reset_request_owner(token: contextvars.Token) -> None:
        _request_owner.reset(token)

    def is_owner(self, owner_id: str) -> bool:
        context = _request_owner.get()
        return self.authority.accepts(context) and owner_id == self.authority.owner_id

    def filter_tools(self, owner_id: str, tools: list[dict]) -> list[dict] | None:
        return tools if self.is_owner(owner_id) else None

    def allowed_tool_names(self, owner_id: str) -> set[str] | None:
        # Identity only. No exact-action consent or safety bypass.
        return None if self.is_owner(owner_id) else set()
