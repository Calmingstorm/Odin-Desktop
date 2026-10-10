"""Windows: ``read_file`` on the local host, without awk (phase 3 plan, C3).

The handler runs an awk program on the host and parses what it prints. On the
local Windows host this module prints exactly that, byte for byte, so the
handler's parsing, secret scrubbing and framing stay one code path.

* Records are the bytes between LFs. A CR stays in its record, and a final record
  without an LF is still a record, as awk reads them.
* Numbered mode measures characters as gawk does in a UTF-8 locale, an invalid
  byte counting as one. Raw mode (``LC_ALL=C``) measures bytes.
* The shell's own wrapping is reproduced too: raw mode prints the body's base64,
  a newline and the metadata line, or an ``ERROR`` line for an oversize line.
"""
from __future__ import annotations

import base64
import errno
import os
import re
import stat
from collections.abc import Iterator

_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def is_absolute(path: str) -> bool:
    """A POSIX path for a Linux host, or a drive or UNC path for the local Windows host."""
    return path.startswith("/") or bool(_WINDOWS_ABSOLUTE.match(path))


def _records(stream) -> Iterator[bytes]:
    for line in stream:
        yield line[:-1] if line.endswith(b"\n") else line


def _characters(data: bytes) -> int:
    return len(data.decode("utf-8", errors="surrogateescape"))


def numbered(stream, *, start: int, start_label: str, count: int, budget: int) -> bytes:
    """The numbered awk program's output."""
    used = selected = returned = last_returned = continuation = oversize_line = 0
    out = bytearray()
    for nr, record in enumerate(_records(stream), start=1):
        if nr < start:
            continue
        if selected >= count:
            continuation = nr
            break
        selected += 1
        line = f"{nr}: ".encode("ascii") + record
        needed = (1 if returned > 0 else 0) + _characters(line)
        if used + needed > budget:
            if returned == 0:
                oversize_line = nr
            else:
                continuation = nr
            break
        if returned > 0:
            out += b"\n"
        out += line
        used += needed
        returned += 1
        last_returned = nr
    if returned > 0:
        out += b"\n\n"
    if oversize_line > 0:
        out += (f"Error: source line {oversize_line} exceeds the read_file output budget; "
                "no lines returned.").encode("ascii")
    elif returned == 0:
        out += f"[returned empty range starting at start_line={start_label[1:]}]".encode("ascii")
    elif continuation > 0:
        out += (f"[returned {start}-{last_returned}, continue at "
                f"start_line={continuation}]").encode("ascii")
    else:
        out += f"[returned {start}-{last_returned}]".encode("ascii")
    return bytes(out)


def _final_newline(path) -> int:
    """``tail -c 1 < path | wc -l``: 1 when the last byte is an LF."""
    with open(path, "rb") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            return 0
        stream.seek(-1, os.SEEK_END)
        return 1 if stream.read(1) == b"\n" else 0


def raw(path, *, start: int, start_label: str, count: int, budget: int) -> bytes:
    """The raw-mode shell pipeline's output: base64 body, newline, metadata line."""
    final_newline = _final_newline(path)
    used = selected = returned = last_returned = continuation = oversize_line = 0
    pending = False
    pending_nr = 0
    pending_line = b""
    body: list[bytes] = []
    with open(path, "rb") as stream:
        for nr, record in enumerate(_records(stream), start=1):
            if nr < start:
                continue
            if pending:
                if returned == 0:
                    oversize_line = pending_nr
                else:
                    continuation = pending_nr
                pending = False
                break
            if selected >= count:
                continuation = nr
                break
            selected += 1
            needed = len(record) + 1
            if used + needed > budget:
                # The final unterminated line whose synthetic newline is the only
                # byte over budget is decided at the end, as in awk.
                if used + len(record) <= budget:
                    pending, pending_nr, pending_line = True, nr, record
                    continue
                if returned == 0:
                    oversize_line = nr
                else:
                    continuation = nr
                break
            returned += 1
            body.append(record)
            used += needed
            last_returned = nr
    if pending:
        if final_newline == 0:
            returned += 1
            body.append(pending_line)
            used += len(pending_line)
            last_returned = pending_nr
        elif returned == 0:
            oversize_line = pending_nr
        else:
            continuation = pending_nr
    elif returned > 0 and continuation == 0 and final_newline == 0:
        used -= 1
    if oversize_line > 0:
        return f"\nERROR\t{oversize_line}\n".encode("ascii")
    metadata = f"ODIN_READ_FILE_RAW_META_V1\t{start_label[1:]}\t{count}\t"
    metadata += f"{start}\t{last_returned}\t" if returned > 0 else "-\t-\t"
    metadata += f"{continuation}\t{used}\n" if continuation > 0 else f"-\t{used}\n"
    content = bytearray()
    for index, record in enumerate(body, start=1):
        content += record
        if index < returned or continuation > 0 or final_newline != 0:
            content += b"\n"
    return base64.b64encode(bytes(content)) + b"\n" + metadata.encode("ascii")


# The device namespaces: pipes, consoles and raw devices, not files (a drive path written
# with \\?\ is a file).
_DEVICE_PATH = re.compile(r"^[\\/][\\/][.?][\\/](?![A-Za-z]:[\\/])")


def _regular_file(path: str) -> None:
    """Refuse what isn't a regular file: reading a device or a pipe can block for good, and
    a worker thread can't be stopped. Device paths are refused before anything is opened."""
    if _DEVICE_PATH.match(path):
        raise OSError(errno.EINVAL, "not a regular file", path)
    with open(path, "rb") as stream:  # a device name (NUL, CON) opens as a device: no read
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError(errno.EINVAL, "not a regular file", path)


def read_local(path: str, *, start: int, start_label: str, count: int, budget: int,
               raw_mode: bool) -> tuple[int, str]:
    """``(exit code, output)`` as the host transport returns them for the awk command."""
    try:
        _regular_file(path)
        if raw_mode:
            data = raw(path, start=start, start_label=start_label, count=count, budget=budget)
        else:
            with open(path, "rb") as stream:
                data = numbered(stream, start=start, start_label=start_label, count=count,
                                budget=budget)
    except OSError as exc:
        return 2, f"read_file: cannot open {path}: {exc.strerror or exc}\n"
    return 0, data.decode("utf-8", errors="replace")


async def read_on_host(self, alias: str, command: str, *, path: str, start: int,
                       start_label: str, count: int, budget: int, raw_mode: bool):
    """``_run_on_host`` for ``read_file``: the same lease and result; local reads in Python."""
    import asyncio

    from ...tools.command_shell import raw_command_result
    from ...tools.output_authorization import record_host
    from ...tools.ssh import is_local_address

    lease = self._acquire_host(alias)
    if not lease:
        return f"Unknown or disallowed host: {alias}"
    record_host(lease)
    with lease:
        target = lease.target
        if is_local_address(target.address):
            code, output = await lease.run(lambda: asyncio.to_thread(
                read_local, path, start=start, start_label=start_label, count=count,
                budget=budget, raw_mode=raw_mode))
        else:
            code, output = await lease.run(lambda: self._exec_command(
                target.address, command, target.ssh_user, target=target))
    return raw_command_result(code, output), code
