"""Bounded protocol-v0 framing. Payloads never appear in transport errors."""
from __future__ import annotations

import asyncio
import json
import math
import struct
import uuid

PROTOCOL_MAJOR = 0
PROTOCOL_MINOR = 2
MAX_FRAME = 4 * 1024 * 1024
HANDSHAKE_TIMEOUT = 5.0


class ProtocolError(ValueError):
    """Malformed envelope or frame, not a method-level refusal."""


def validate_max_frame(max_frame: int) -> int:
    if type(max_frame) is not int or not 1 <= max_frame <= MAX_FRAME:
        raise ValueError("invalid frame limit")
    return max_frame


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise ProtocolError("nonfinite JSON number")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError("nonfinite JSON number")
    return result


def encode_frame(message: dict, max_frame: int = MAX_FRAME) -> bytes:
    validate_max_frame(max_frame)
    if not isinstance(message, dict):
        raise ProtocolError("JSON object required")
    try:
        data = json.dumps(message, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProtocolError("invalid JSON object") from None
    if not 1 <= len(data) <= max_frame:
        raise ProtocolError("invalid frame size")
    return struct.pack("!I", len(data)) + data


async def read_frame(reader: asyncio.StreamReader, max_frame: int = MAX_FRAME) -> dict:
    validate_max_frame(max_frame)
    header = await reader.readexactly(4)
    size = struct.unpack("!I", header)[0]
    if not 1 <= size <= max_frame:
        raise ProtocolError("invalid frame size")
    data = await reader.readexactly(size)
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=_constant, parse_float=_float)
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolError("invalid JSON object") from None
    if not isinstance(result, dict):
        raise ProtocolError("JSON object required")
    return result


def validate_hello(message: dict) -> None:
    protocol = message.get("protocol")
    client = message.get("client")
    features = message.get("features")
    if (
        message.get("t") != "hello"
        or not isinstance(protocol, dict)
        or type(protocol.get("major")) is not int
        or type(protocol.get("minor")) is not int
        or protocol["minor"] < 0
        or not isinstance(client, dict)
        or not isinstance(client.get("name"), str)
        or not isinstance(client.get("version"), str)
        or not isinstance(message.get("profile_id"), str)
        or not isinstance(message.get("token"), str)
        or not isinstance(features, list)
        or any(not isinstance(item, str) for item in features)
    ):
        raise ProtocolError("invalid hello envelope")


def validate_request(message: dict) -> None:
    """Method params belong to core: invalid known mutations need durable refusals."""
    identity = message.get("id")
    try:
        parsed = uuid.UUID(identity) if isinstance(identity, str) else None
    except ValueError:
        parsed = None
    if (
        message.get("t") != "req"
        or parsed is None
        or parsed.version != 4
        or str(parsed) != identity
        or not isinstance(message.get("method"), str)
        or not message["method"]
        or "params" not in message
    ):
        raise ProtocolError("invalid request envelope")
