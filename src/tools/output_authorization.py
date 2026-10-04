"""Task-local evidence authorization, shared by native tools and skills."""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

request_tool_scope: ContextVar[Any] = ContextVar("request_tool_scope", default=None)
request_scope_authorizer: ContextVar[Any] = ContextVar("request_scope_authorizer", default=None)
request_scope_id = ContextVar("request_scope_id", default="")
request_delivery_channel = ContextVar("request_delivery_channel", default="")
request_host_authorizer: ContextVar[Any] = ContextVar("request_host_authorizer", default=None)
accessed_hosts: ContextVar[dict | None] = ContextVar("output_accessed_hosts", default=None)


@contextmanager
def host_access_capture():
    """Gather child-task accesses into the same invocation-owned collection."""
    existing = accessed_hosts.get()
    token = accessed_hosts.set(existing if existing is not None else {})
    try:
        yield
    finally:
        accessed_hosts.reset(token)


def host_binding(target):
    # Runtime generation alone can collide after restart. Pin connection and
    # trust identity too, without persisting connection details in envelopes.
    identity = [getattr(target, key, None) for key in (
        "address", "ssh_user", "os", "port", "trust_mode", "host_keys",
        "key_path", "known_hosts_path", "host_key_alias")]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {"alias": target.alias, "generation": target.runtime_key, "identity": digest}


def record_host(lease):
    collector = accessed_hosts.get()
    if lease is not None and collector is not None:
        binding = host_binding(lease.target)
        collector[(binding["alias"], binding["generation"], binding["identity"])] = binding
    return lease


def tool_scope_allows(tool):
    scope = request_tool_scope.get()
    if scope is not None and tool not in scope:
        return False
    resolver = request_scope_authorizer.get()
    if resolver is not None:
        current = resolver()
        if current is False or (current is not None and tool not in current):
            return False
    return True


@contextmanager
def owner_output_scope(*args, **kwargs):
    """No admitted conversation scope exists until Phase 2 intake is wired.

    Retained host/tool resolver primitives above remain available for internal
    evidence authorization. A conversation ID or owner-looking argument must
    never manufacture an authentic, generation-bound delivery scope.
    """
    from ..desktop.errors import CapabilityUnavailable

    raise CapabilityUnavailable("Conversation output scope unavailable until Phase 2 admission.")
    yield  # contextmanager never enters without admitted scope
