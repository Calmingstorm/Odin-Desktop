"""Phase 2: authenticated owner/job/destination scheduling commands.

Require validated existing conversation revisions, reservation/no-replay,
history and owned background CRUD/run/reset. Empty requesters confer no power.
"""
from ...desktop.schedules import ScheduleService


def schedule_methods(service: ScheduleService):
    """Named local-protocol handlers, never an HTTP/browser authority shim."""
    def bind(method):
        async def handler(params, *, owner):
            return await service.invoke(method, params, owner=owner)
        return handler
    return {method: bind(method) for method in service.methods}


def register_schedules(service: ScheduleService):
    return schedule_methods(service)
