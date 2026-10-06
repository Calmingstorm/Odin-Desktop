"""Harmless, parent-linked Unix socket occupant for isolated lifecycle E2E."""
import json
import os
import socket
import sys

path, mode = sys.argv[1:]
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(path)
sock.listen(8)
info = os.stat(path)
print(json.dumps({"pid": os.getpid(), "inode": info.st_ino, "device": info.st_dev,
                  "namespace": os.readlink("/proc/self/ns/pid"), "mode": mode}), flush=True)
if mode == "stale":
    sock.close()
elif mode == "live":
    sys.stdin.buffer.read()
    sock.close()
else:
    raise ValueError("Only harmless live/stale socket occupants are supported")
