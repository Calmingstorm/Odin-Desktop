"""The Windows session protocol (phase 2 plan B2), on any OS: proofs, keys, sealed frames."""
from __future__ import annotations

import asyncio
import json
import socket
import struct
from pathlib import Path

import pytest

from src.desktop import ipc_auth
from src.desktop.protocol import ProtocolError, encode_frame, read_frame

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests/fixtures/windows-session-vectors.json").read_text())
TOKEN = "ab" * 32
ENDPOINT = r"\\.\pipe\odin-desktop-test-default"
CLIENT = {"name": "odin-cli", "version": "0"}
OFFERED = {"major": 0, "minor": 2}
SELECTED = {"major": 0, "minor": 3}


def test_fixed_vectors_pin_every_encoding():
    fields = VECTORS["fields"]
    client_nonce = bytes.fromhex(VECTORS["client_nonce"])
    server_nonce = bytes.fromhex(VECTORS["server_nonce"])
    transcript = ipc_auth.session_transcript(client_nonce=client_nonce, server_nonce=server_nonce,
                                             **fields)
    assert transcript.hex() == VECTORS["transcript"]
    keys = ipc_auth.session_keys(VECTORS["token"], client_nonce, server_nonce, transcript)
    assert {key: value.hex() for key, value in keys.items()} == VECTORS["keys"]
    assert ipc_auth.session_proof(keys, "server", transcript).hex() == VECTORS["server_proof"]
    assert ipc_auth.session_proof(keys, "client", transcript).hex() == VECTORS["client_proof"]
    for direction, key, name in ((ipc_auth.CLIENT_TO_SERVER, keys["c2s"], "client_to_server"),
                                 (ipc_auth.SERVER_TO_CLIENT, keys["s2c"], "server_to_client")):
        sealer = ipc_auth.SealedDirection(key, direction)
        opener = ipc_auth.SealedDirection(key, direction)
        for item in VECTORS[name]:
            frame = sealer.seal(item["payload"].encode())
            assert frame.hex() == item["sealed"]
            assert opener.open(frame[:4], frame[4:]) == item["payload"].encode()


def test_proof_comparison_needs_exact_hex():
    expected = bytes(range(32))
    assert ipc_auth.proof_matches(expected, expected.hex())
    for supplied in (expected.hex().upper(), expected.hex()[:-2], None, 7, "zz" * 32):
        assert not ipc_auth.proof_matches(expected, supplied)


async def _pair():
    left, right = socket.socketpair()
    a = await asyncio.open_connection(sock=left)
    b = await asyncio.open_connection(sock=right)
    return a, b


async def _close(*writers):
    for writer in writers:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass


async def _sessions(*, client_token=TOKEN, server_token=TOKEN):
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    server = asyncio.create_task(ipc_auth.server_session(
        server_reader, server_writer, token=server_token, profile_id="default",
        endpoint=ENDPOINT, instance_id="core-1", max_frame=65536, selected=SELECTED))
    client = asyncio.create_task(ipc_auth.client_session(
        client_reader, client_writer, token=client_token, profile_id="default",
        endpoint=ENDPOINT, client=CLIENT, offered=OFFERED, features=["events"]))
    return client, server, (client_writer, server_writer)


async def test_a_session_seals_both_ways_and_hands_the_server_its_own_hello():
    client, server, writers = await _sessions()
    (client_in, client_out), (server_in, server_out) = await asyncio.gather(client, server)
    hello = await read_frame(server_in, 65536)
    assert hello == {"t": "hello", "protocol": OFFERED, "client": CLIENT, "profile_id": "default",
                     "token": TOKEN, "features": ["events"]}
    server_out.write(encode_frame({"t": "welcome", "n": 1}))
    await server_out.drain()
    assert await read_frame(client_in, 65536) == {"t": "welcome", "n": 1}
    client_out.write(encode_frame({"t": "req", "id": "a"}) + encode_frame({"t": "ping", "n": 2}))
    await client_out.drain()
    assert await read_frame(server_in, 65536) == {"t": "req", "id": "a"}
    assert await read_frame(server_in, 65536) == {"t": "ping", "n": 2}
    await _close(*writers)


async def test_the_token_never_crosses_the_pipe():
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    seen = []
    original = server_reader.readexactly

    async def recording(n):
        data = await original(n)
        seen.append(data)
        return data

    server_reader.readexactly = recording
    server = asyncio.create_task(ipc_auth.server_session(
        server_reader, server_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
        instance_id="core-1", max_frame=65536, selected=SELECTED))
    sealed_in, sealed_out = await ipc_auth.client_session(
        client_reader, client_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
        client=CLIENT, offered=OFFERED, features=[])
    await server
    sealed_out.write(encode_frame({"t": "req", "secret": TOKEN}))
    await sealed_out.drain()
    received = (await server)[0]
    assert (await read_frame(received, 65536))["token"] == TOKEN  # the server's own copy
    await read_frame(received, 65536)
    wire = b"".join(seen)
    assert TOKEN.encode() not in wire and bytes.fromhex(TOKEN) not in wire
    await _close(client_writer, server_writer)


async def test_a_client_without_the_token_is_refused():
    client, server, writers = await _sessions(client_token="cd" * 32)
    with pytest.raises(PermissionError, match="engine proof refused"):
        await client
    await _close(*writers)
    with pytest.raises((asyncio.IncompleteReadError, ConnectionError, TimeoutError)):
        await server


async def test_a_squatting_engine_without_the_token_learns_nothing():
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    client = asyncio.create_task(ipc_auth.client_session(
        client_reader, client_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
        client=CLIENT, offered=OFFERED, features=[]))
    hello = await read_frame(server_reader)
    assert "token" not in hello and set(hello["auth"]) == {"v", "client_nonce"}
    server_writer.write(encode_frame({
        "t": "challenge", "server_nonce": "11" * 32, "protocol": SELECTED, "max_frame": 65536,
        "core": {"instance_id": "fake"}, "server_proof": "22" * 32}))
    await server_writer.drain()
    with pytest.raises(PermissionError, match="engine proof refused"):
        await client
    await _close(client_writer)
    assert await server_reader.read() == b""  # nothing after the hello: no proof
    await _close(server_writer)


async def _raw_server(frames, *, max_frame=65536):
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    server = asyncio.create_task(ipc_auth.server_session(
        server_reader, server_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
        instance_id="core-1", max_frame=max_frame, selected=SELECTED))
    for frame in frames:
        client_writer.write(frame if isinstance(frame, bytes) else encode_frame(frame))
    await client_writer.drain()
    return server, client_reader, client_writer, server_writer


def _hello(**changes):
    hello = {"t": "hello", "protocol": OFFERED, "client": CLIENT, "profile_id": "default",
             "features": [], "auth": {"v": 1, "client_nonce": "33" * 32}}
    hello.update(changes)
    return hello


@pytest.mark.parametrize(("frame", "error"), [
    (_hello(token=TOKEN), PermissionError),
    (_hello(auth={"v": 2, "client_nonce": "33" * 32}), ProtocolError),
    (_hello(auth={"v": 1, "client_nonce": "33" * 31}), ProtocolError),
    (_hello(auth={"v": 1}), ProtocolError),
    (_hello(protocol={"major": 0}), ProtocolError),
    (_hello(features=[1]), ProtocolError),
    ({"t": "req", "id": "early", "method": "status.get", "params": {}}, ProtocolError),
    (struct.pack("!I", ipc_auth.PREAUTH_MAX_FRAME + 1) + b"x", ProtocolError),
])
async def test_the_engine_refuses_bad_hellos(frame, error):
    server, _, client_writer, server_writer = await _raw_server([frame])
    with pytest.raises(error):
        await server
    await _close(client_writer, server_writer)


async def test_a_reflected_server_proof_and_an_early_request_are_refused():
    server, client_reader, client_writer, server_writer = await _raw_server([_hello()])
    challenge = await read_frame(client_reader)
    client_writer.write(encode_frame({"t": "proof", "client_proof": challenge["server_proof"]}))
    await client_writer.drain()
    with pytest.raises(PermissionError, match="client proof refused"):
        await server
    await _close(client_writer, server_writer)
    server, client_reader, client_writer, server_writer = await _raw_server([_hello()])
    await read_frame(client_reader)
    client_writer.write(encode_frame({"t": "req", "id": "x", "method": "status.get", "params": {}}))
    await client_writer.drain()
    with pytest.raises(ProtocolError):
        await server
    await _close(client_writer, server_writer)
    server, client_reader, client_writer, server_writer = await _raw_server([_hello()])
    await read_frame(client_reader)
    client_writer.write(encode_frame({"t": "ack", "client_proof": "00" * 32}))
    await client_writer.drain()
    with pytest.raises(ProtocolError, match="unexpected handshake frame"):
        await server
    await _close(client_writer, server_writer)


async def test_a_recorded_proof_fails_against_a_fresh_server_nonce():
    server, client_reader, client_writer, server_writer = await _raw_server([_hello()])
    first = await read_frame(client_reader)
    client_nonce, server_nonce = bytes.fromhex("33" * 32), bytes.fromhex(first["server_nonce"])
    transcript = ipc_auth.session_transcript(
        offered=OFFERED, selected=SELECTED, client=CLIENT, profile_id="default", endpoint=ENDPOINT,
        client_nonce=client_nonce, server_nonce=server_nonce, instance_id="core-1",
        max_frame=65536, features=[])
    keys = ipc_auth.session_keys(TOKEN, client_nonce, server_nonce, transcript)
    recorded = ipc_auth.session_proof(keys, "client", transcript).hex()
    client_writer.write(encode_frame({"t": "proof", "client_proof": recorded}))
    await client_writer.drain()
    await server  # the first engine accepts it
    await _close(client_writer, server_writer)
    replay, client_reader, client_writer, server_writer = await _raw_server([
        _hello(), {"t": "proof", "client_proof": recorded}])
    with pytest.raises(PermissionError):
        await replay
    await _close(client_writer, server_writer)


async def test_a_changed_transcript_field_breaks_the_proofs():
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    server = asyncio.create_task(ipc_auth.server_session(
        server_reader, server_writer, token=TOKEN, profile_id="default",
        endpoint=r"\\.\pipe\another-endpoint", instance_id="core-1", max_frame=65536,
        selected=SELECTED))
    with pytest.raises(PermissionError, match="engine proof refused"):
        await ipc_auth.client_session(
            client_reader, client_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
            client=CLIENT, offered=OFFERED, features=[])
    await _close(client_writer, server_writer)
    with pytest.raises((asyncio.IncompleteReadError, ConnectionError, TimeoutError)):
        await server


def _directions():
    key = bytes(range(32))
    return (ipc_auth.SealedDirection(key, ipc_auth.CLIENT_TO_SERVER),
            ipc_auth.SealedDirection(key, ipc_auth.CLIENT_TO_SERVER))


def test_tampered_reordered_and_foreign_frames_are_refused():
    sealer, opener = _directions()
    first, second = sealer.seal(b'{"n":1}'), sealer.seal(b'{"n":2}')
    with pytest.raises(ProtocolError, match="out of order"):
        opener.open(second[:4], second[4:])
    tampered = bytearray(first)
    tampered[-1] ^= 1
    with pytest.raises(ProtocolError, match="rejected"):
        opener.open(bytes(tampered[:4]), bytes(tampered[4:]))
    other = ipc_auth.SealedDirection(bytes(32), ipc_auth.CLIENT_TO_SERVER)
    foreign = other.seal(b'{"n":1}')
    with pytest.raises(ProtocolError, match="rejected"):
        opener.open(foreign[:4], foreign[4:])
    assert opener.open(first[:4], first[4:]) == b'{"n":1}'
    with pytest.raises(ProtocolError, match="out of order"):
        opener.open(first[:4], first[4:])  # a replay of an accepted frame


def test_the_other_direction_cannot_open_a_frame():
    key = bytes(range(32))
    frame = ipc_auth.SealedDirection(key, ipc_auth.CLIENT_TO_SERVER).seal(b"{}")
    with pytest.raises(ProtocolError, match="rejected"):
        ipc_auth.SealedDirection(key, ipc_auth.SERVER_TO_CLIENT).open(frame[:4], frame[4:])


@pytest.mark.parametrize("size", [ipc_auth.SEAL_OVERHEAD - 1, 1024 + ipc_auth.SEAL_OVERHEAD + 1])
async def test_sealed_sizes_are_bounded_before_reading(size):
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack("!I", size))
    sealed = ipc_auth.SealedReader(reader, _directions()[1], 1024)
    with pytest.raises(ProtocolError, match="invalid sealed frame size"):
        await sealed.readexactly(4)


async def test_an_ended_stream_is_an_incomplete_read():
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x00\x00")
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await ipc_auth.SealedReader(reader, _directions()[1], 1024).readexactly(4)


async def test_concurrent_senders_keep_counter_order():
    (left_reader, left_writer), (right_reader, right_writer) = await _pair()
    sealer, opener = _directions()
    out = ipc_auth.SealedWriter(left_writer, sealer)
    inbound = ipc_auth.SealedReader(right_reader, opener, 65536)

    async def send(n):
        out.write(encode_frame({"n": n}))
        await out.drain()

    await asyncio.gather(*(send(n) for n in range(50)))
    received = [await read_frame(inbound, 65536) for _ in range(50)]
    assert sorted(item["n"] for item in received) == list(range(50))
    assert out.get_extra_info("socket") is not None and not out.is_closing()
    out.close()
    await out.wait_closed()
    await _close(right_writer)


def test_partial_writes_seal_only_complete_frames():
    sent = []
    writer = ipc_auth.SealedWriter(type("W", (), {"write": lambda self, data: sent.append(data)})(),
                                   _directions()[0])
    frame = encode_frame({"t": "ping", "n": 1})
    writer.write(frame[:3])
    writer.write(frame[3:7])
    assert sent == []
    writer.write(frame[7:])
    assert len(sent) == 1


def test_a_key_is_never_used_past_its_budget(monkeypatch):
    sealer, _ = _directions()
    monkeypatch.setattr(ipc_auth, "SESSION_FRAME_LIMIT", 1)
    sealer.seal(b"{}")
    with pytest.raises(ProtocolError, match="exhausted"):
        sealer.seal(b"{}")


@pytest.mark.parametrize("change", [
    {"t": "welcome"}, {"max_frame": 0}, {"protocol": {"major": 0}}, {"core": {}},
])
async def test_the_client_refuses_a_malformed_challenge(change):
    (client_reader, client_writer), (server_reader, server_writer) = await _pair()
    client = asyncio.create_task(ipc_auth.client_session(
        client_reader, client_writer, token=TOKEN, profile_id="default", endpoint=ENDPOINT,
        client=CLIENT, offered=OFFERED, features=[]))
    await read_frame(server_reader)
    challenge = {"t": "challenge", "server_nonce": "11" * 32, "protocol": SELECTED,
                 "max_frame": 65536, "core": {"instance_id": "x"}, "server_proof": "22" * 32}
    challenge.update(change)
    server_writer.write(encode_frame(challenge))
    await server_writer.drain()
    with pytest.raises(ProtocolError):
        await client
    await _close(client_writer, server_writer)


async def test_one_deadline_covers_all_of_pre_auth(monkeypatch):
    import src.desktop.protocol as protocol

    monkeypatch.setattr(protocol, "HANDSHAKE_TIMEOUT", 0.2)
    server, _, client_writer, server_writer = await _raw_server([_hello()])
    with pytest.raises(TimeoutError):
        await server
    await _close(client_writer, server_writer)
