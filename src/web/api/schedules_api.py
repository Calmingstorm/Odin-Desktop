"""Phase 2: authenticated owner/job/destination scheduling commands.

Require validated existing conversation revisions, reservation/no-replay,
history and owned background CRUD/run/reset. Empty requesters confer no power.
"""
from . import require_phase2


def register_schedules(*args, **kwargs):
    require_phase2("Durable scheduling commands")
