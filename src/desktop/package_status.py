"""Read-only package observations and the existing shutdown handoff.

Release metadata belongs to the app's P4.3 notice, not a second core updater.
Core quiescence is weaker than package replacement permission: the entry-point
finalization barrier and P4.2 app/core package leases remain authoritative.
"""
from __future__ import annotations

from copy import deepcopy

from ..version import get_version
from .package_state import compatibility


class PackageStatus:
    """Project retained owners only; never acquire leases or run cleanup on read."""

    def __init__(self, core, record: dict | None) -> None:
        self.core = core
        self.version = get_version()
        self.core_instance_id = core.authority.runtime_id
        self._record = deepcopy(record)
        self._fencing_lost = False

    def migration_committed(self) -> None:
        """Called only after PackageUpgrade.commit's durable barrier succeeds."""
        if self._record is not None:
            self._record["state"] = "committed"

    def snapshot(self) -> dict:
        core = self.core
        authority = core.authority
        identity_current = authority._identity_current() and not authority.durability_degraded
        held = authority._runtime_lock_fd is not None
        fenced = held and authority._runtime_current() and identity_current
        if not identity_current or (held and not fenced):
            # Later release/replacement cannot erase observed ownership loss.
            self._fencing_lost = True
        cleanup = core.resource_cleanup.public() if core.resource_cleanup is not None else None
        clean = (cleanup is not None and cleanup["state"] == "complete"
                 and not cleanup["reconciliation_required"])
        producers = (core.engine is not None
                     and getattr(core.engine, "producers_quiesced", False))
        closed = core._close_complete
        admitting = (core.phase == "ready" and core.lifetime.admitting and fenced
                     and not self._fencing_lost)
        blockers = []
        if core.lifetime.admitting:
            blockers.append("shutdown_not_requested")
        if not closed:
            blockers.append("core_close_not_complete")
        if not producers:
            blockers.append("producers_not_quiesced")
        if not clean:
            blockers.append("cleanup_unverified" if cleanup is None
                            else "cleanup_reconciliation_required"
                            if cleanup["reconciliation_required"]
                            else "cleanup_not_complete")
        if self._fencing_lost:
            blockers.append("ownership_unavailable")
        if held:
            blockers.append("profile_runtime_owned")
        # An in-process observation cannot attest its own later process exit,
        # entry-point containment/finalizers, or the app's independent lease.
        blockers.append("external_package_ownership_barrier_required")
        quiesced = (closed and not core.lifetime.admitting and producers and clean
                    and identity_current and not self._fencing_lost and (not held or fenced))
        state = ("ownership_unavailable" if self._fencing_lost
                 else "cleanup_unknown" if cleanup and cleanup["reconciliation_required"]
                 else "core_closed" if quiesced
                 else "quiescing" if not core.lifetime.admitting
                 else "running" if admitting else "starting")
        return {
            "identity": {
                "product": "odin-desktop", "package_version": self.version,
                "installation_id": authority.installation_id,
                "profile_id": core.paths.profile_id,
                "core_instance_id": self.core_instance_id,
            },
            "compatibility": compatibility(),
            "profile_state": {
                "state": self._record["state"] if self._record else "unrecorded",
                "package_version": self._record["package_version"] if self._record else None,
                "evidence": "startup_compatibility_and_migration_barriers",
            },
            "update": {
                "mode": "notice_only", "state": "not_checked", "owner": "app_release_notice",
                "reason": "release_metadata_not_checked_by_core", "apply_available": False,
            },
            "handoff": {
                "state": state, "admitting": admitting, "stop_reason": core.lifetime.reason,
                "shutdown_method": "runtime.shutdown", "core_quiesced": quiesced,
                "core_close_complete": closed, "producers_quiesced": producers,
                "ownership_current": fenced, "profile_runtime_owned": held,
                "cleanup": deepcopy(cleanup), "replacement_safe": False,
                "replacement_authority": "package_ownership_external_preflight",
                "blockers": blockers, "effects_undone": False, "replay": False,
            },
        }
