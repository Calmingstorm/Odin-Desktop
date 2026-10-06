"""Harmless loopback effect counter and credential-free real-core entry for E2E.

No core method is replaced. The entry injects only the supported secret backend
seam: reads return None and writes fail, so no real keyring or credential exists.
The receiver counts complete POST bodies before deliberately withholding HTTP
responses. Its independent counter is not a core/app success projection.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path


def isolated():
    root = os.environ.get("ODIN_REAL_CORE_ROOT")
    outer = os.environ.get("ODIN_REAL_CORE_OUTER_PID_NS")
    if (os.geteuid() == 0 or os.environ.get("ODIN_APP_E2E") != "1"
            or not root or os.environ.get("HOME") != root or not outer
            or os.readlink("/proc/self/ns/pid") == outer
            or not os.environ.get("DISPLAY", "").startswith(":")
            or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
        raise RuntimeError("Owned HTTP fixture refuses non-isolated execution")


def core_entry():
    isolated()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.__main__ import main
    from src.desktop.management import ManagementService

    class NoCredentials:
        def get_password(self, service, name):
            return None

        def set_password(self, *args):
            raise RuntimeError("Credential writes forbidden in this fixture")

        def delete_password(self, *args):
            raise RuntimeError("Credential writes forbidden in this fixture")

    compose = ManagementService.compose.__func__
    ManagementService.compose = classmethod(
        lambda cls, core, **kwargs: compose(cls, core, secret_backend=NoCredentials())
    )
    sys.argv.remove("--core-entry")
    main()


async def receiver():
    isolated()
    requests = []
    release = asyncio.Event()
    stop = asyncio.Event()
    handlers = set()

    def emit(value):
        print(json.dumps(value), flush=True)

    async def handle(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        row = None
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = headers.decode("ascii").split("\r\n")
            method, path, _ = lines[0].split(" ")
            fields = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
            size = int(fields.get("content-length", "0"))
            if method != "POST" or size <= 0 or size > 64000:
                raise ValueError("Only bounded test POSTs supported")
            if "authorization" in fields or "x-webhook-signature" in fields:
                raise ValueError("No credentials permitted")
            body = json.loads(await reader.readexactly(size))
            row = {"effect": len(requests) + 1, "path": path, "body": body,
                   "response_sent": False, "disconnected": False}
            requests.append(row)
            releasing = asyncio.create_task(release.wait())
            disconnected = asyncio.create_task(reader.read(1))
            done, pending = await asyncio.wait(
                [releasing, disconnected], return_when=asyncio.FIRST_COMPLETED,
            )
            for future in pending:
                future.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if disconnected in done:
                row["disconnected"] = True
            else:
                writer.write(
                    b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                await writer.drain()
                row["response_sent"] = True
        except (asyncio.CancelledError, ConnectionError, ValueError, asyncio.IncompleteReadError):
            if row is not None:
                row["disconnected"] = True
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    emit({"ready": True, "port": port, "pid": os.getpid(),
          "pid_namespace": os.readlink("/proc/self/ns/pid"), "uid": os.geteuid(),
          "start_ticks": Path("/proc/self/stat").read_text().rsplit(") ", 1)[1].split()[19]})

    async def controls():
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        while line := await reader.readline():
            request = json.loads(line)
            try:
                action = request["action"]
                if action == "snapshot":
                    result = {"effect_count": len(requests), "requests": requests}
                elif action == "release":
                    release.set()
                    result = {"released": True}
                elif action == "journal":
                    path = Path(request["path"]).resolve()
                    if (not path.is_relative_to(Path(os.environ["HOME"]).resolve())
                            or path.name != "transport.sqlite3"):
                        raise ValueError("Only the isolated transport journal is readable")
                    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                        connection.row_factory = sqlite3.Row
                        row = connection.execute(
                            "SELECT command_id,state,response,unknown_outcome,"
                            "created_at,finished_at "
                            "FROM command_receipts WHERE command_id=?", (request["command_id"],)
                        ).fetchone()
                        result = dict(row) if row else None
                        if result and result["response"]:
                            result["response"] = json.loads(result["response"])
                elif action == "stop":
                    stop.set()
                    result = {"stopped": True}
                else:
                    raise ValueError("Unknown fixture control")
                emit({"id": request["id"], "ok": True, "result": result})
            except Exception as exc:
                emit({"id": request["id"], "ok": False, "error": str(exc)})
        stop.set()

    control = asyncio.create_task(controls())
    await stop.wait()
    server.close()
    await server.wait_closed()
    for task in list(handlers):
        task.cancel()
    await asyncio.gather(*list(handlers), return_exceptions=True)
    control.cancel()
    await asyncio.gather(control, return_exceptions=True)
    emit({"cleanup": True, "effect_count": len(requests), "listener_closed": True})


if __name__ == "__main__":
    if "--core-entry" in sys.argv:
        core_entry()
    else:
        asyncio.run(receiver())
