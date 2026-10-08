"""Portal transport cleanup on a closed socket; no desktop, bus daemon or portal helper."""

import socket

from src.computer.runtime import wayland_portal


def test_shutdown_tolerates_an_already_closed_socket():
    # Cancellation may close a socket before cleanup shuts it down; cleanup must not raise.
    closed = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    closed.close()
    wayland_portal._shutdown(closed)
    wayland_portal._shutdown(None)
