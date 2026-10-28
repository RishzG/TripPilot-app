"""The live trip event stream (plan 01-09, D-24): replay, membership, isolation, resilience.

httpx's ASGITransport waits for the whole response body, so an endless SSE stream would hang
it. These tests start a real uvicorn server on a free port inside the test's own event loop (the
lifespan, and with it the LISTEN bridge, runs) and read the stream over real HTTP. Every read
carries a timeout, so a broken stream fails the test instead of hanging it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI

from trippilot.realtime.hub import StreamEvent
from trippilot.trips.invites import invite_rate_limit

if TYPE_CHECKING:
    from conftest import MakeApp, MakeMember


Conn = psycopg.Connection[tuple[object, ...]]

READ_TIMEOUT = 8.0
"""Seconds any single read of the stream may take before the test fails."""


@dataclass(frozen=True)
class LiveServer:
    """A running app: its base URL and the app object (for `app.state`)."""

    base_url: str
    app: FastAPI


def _free_port() -> int:
    """Return a TCP port nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return int(probe.getsockname()[1])


async def _no_limit() -> None:
    """Stand-in for the per-IP invite limiter."""


@pytest.fixture
async def live_server(make_app: MakeApp, test_database: str) -> AsyncIterator[LiveServer]:
    """Serve a non-demo app with uvicorn on a free port for the length of one test."""
    app = make_app(False)
    app.dependency_overrides[invite_rate_limit] = _no_limit
    port = _free_port()
    config = uvicorn.Config(
        app,
        host='127.0.0.1',
        port=port,
        log_level='warning',
        lifespan='on',
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started or task.done():
            break
        await asyncio.sleep(0.05)
    assert server.started, 'uvicorn did not start'
    yield LiveServer(base_url=f'http://127.0.0.1:{port}', app=app)
    server.should_exit = True
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=15)


def _cookie(raw: str) -> dict[str, str]:
    """Return a Cookie header carrying the raw session value."""
    return {'Cookie': f'tp_session={raw}'}


class SseReader:
    """Parses a text/event-stream response into events, one blocking read at a time."""

    def __init__(self, response: httpx.Response) -> None:
        self._lines = response.aiter_lines()

    async def _line(self) -> str:
        return await asyncio.wait_for(self._lines.__anext__(), READ_TIMEOUT)

    async def wait_ready(self) -> None:
        """Read until the server's `: ready` comment: the subscription is in place."""
        while True:
            if (await self._line()).startswith(': ready'):
                return

    async def next_event(self) -> dict[str, str]:
        """Return the next event (id, event, data fields), skipping comments and pings."""
        event: dict[str, str] = {}
        while True:
            line = await self._line()
            if line == '':
                if event:
                    return event
                continue
            if line.startswith(':'):
                continue
            field, _, value = line.partition(':')
            event[field] = value[1:] if value.startswith(' ') else value

    async def ended(self) -> bool:
        """Return True when the server closes the stream (reads to end of body)."""
        try:
            while True:
                await self._line()
        except StopAsyncIteration:
            return True


@contextlib.asynccontextmanager
async def open_stream(
    server: LiveServer, raw: str, trip_id: str, *, last_event_id: int | None = None
) -> AsyncIterator[SseReader]:
    """Open the trip's event stream as the holder of the session and wait until it is ready."""
    headers = _cookie(raw)
    if last_event_id is not None:
        headers['Last-Event-ID'] = str(last_event_id)
    async with (
        httpx.AsyncClient(base_url=server.base_url, timeout=READ_TIMEOUT) as http,
        http.stream('GET', f'/api/trips/{trip_id}/events', headers=headers) as response,
    ):
        assert response.status_code == 200, await response.aread()
        assert response.headers['content-type'].startswith('text/event-stream')
        reader = SseReader(response)
        await reader.wait_ready()
        yield reader


async def _start_trip(http: httpx.AsyncClient, raw: str, name: str = 'Tahoe weekend') -> str:
    """Start a trip as the holder of the session and return its id."""
    response = await http.post('/api/trips', json={'name': name}, headers=_cookie(raw))
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


async def _join(http: httpx.AsyncClient, organiser_raw: str, trip_id: str, joiner_raw: str) -> None:
    """Have the holder of `joiner_raw` join the trip through its invite link."""
    link = await http.get(f'/api/trips/{trip_id}/invite', headers=_cookie(organiser_raw))
    assert link.status_code == 200, link.text
    token = str(link.json()['url']).rsplit('/join/', 1)[1]
    joined = await http.post(f'/api/invites/{token}/join', headers=_cookie(joiner_raw))
    assert joined.status_code == 200, joined.text


def _event_ids(conn: Conn, trip_id: str) -> list[int]:
    """Return the trip's trip_events ids in order."""
    rows = conn.execute(
        'SELECT id FROM trip_events WHERE trip_id = %s ORDER BY id', (trip_id,)
    ).fetchall()
    return [int(str(row[0])) for row in rows]


@pytest.fixture
async def http(live_server: LiveServer) -> AsyncIterator[httpx.AsyncClient]:
    """Return a plain client to the live server for ordinary API calls."""
    async with httpx.AsyncClient(base_url=live_server.base_url, timeout=READ_TIMEOUT) as client:
        yield client


async def test_member_receives_a_join_live_with_the_row_id(
    live_server: LiveServer,
    http: httpx.AsyncClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    _, organiser_raw = await make_member('Maya')
    guest, guest_raw = await make_member('Sam')
    trip_id = await _start_trip(http, organiser_raw)

    async with open_stream(live_server, organiser_raw, trip_id) as stream:
        await _join(http, organiser_raw, trip_id, guest_raw)
        event = await stream.next_event()

    assert event['event'] == 'member.joined'
    assert event['id'] == str(_event_ids(sync_conn, trip_id)[-1])
    assert json.loads(event['data'])['account_id'] == str(guest.id)


async def test_reconnect_with_last_event_id_replays_each_later_event_once(
    live_server: LiveServer,
    http: httpx.AsyncClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    _, organiser_raw = await make_member('Maya')
    guests = [await make_member(name) for name in ('Sam', 'Theo', 'Uma', 'Vik')]
    trip_id = await _start_trip(http, organiser_raw)
    for _, raw in guests[:3]:
        await _join(http, organiser_raw, trip_id, raw)
    first, second, third = _event_ids(sync_conn, trip_id)

    async with open_stream(live_server, organiser_raw, trip_id, last_event_id=first) as stream:
        replayed = [await stream.next_event(), await stream.next_event()]
        await _join(http, organiser_raw, trip_id, guests[3][1])
        live = await stream.next_event()

    ids = [int(item['id']) for item in [*replayed, live]]
    assert ids[:2] == [second, third]
    assert ids[2] == _event_ids(sync_conn, trip_id)[-1]
    assert len(set(ids)) == 3
    assert ids == sorted(ids)


async def test_without_last_event_id_nothing_old_is_replayed(
    live_server: LiveServer,
    http: httpx.AsyncClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    _, organiser_raw = await make_member('Maya')
    (_, early_raw), (_, late_raw) = [await make_member(name) for name in ('Sam', 'Theo')]
    trip_id = await _start_trip(http, organiser_raw)
    await _join(http, organiser_raw, trip_id, early_raw)
    old = _event_ids(sync_conn, trip_id)

    async with open_stream(live_server, organiser_raw, trip_id) as stream:
        await _join(http, organiser_raw, trip_id, late_raw)
        event = await stream.next_event()

    assert int(event['id']) not in old


async def test_a_signed_out_request_gets_401_and_a_stranger_gets_404(
    live_server: LiveServer, http: httpx.AsyncClient, make_member: MakeMember
) -> None:
    _, organiser_raw = await make_member('Maya')
    _, stranger_raw = await make_member('Nosy')
    trip_id = await _start_trip(http, organiser_raw)
    unknown = '00000000-0000-0000-0000-000000000000'

    signed_out = await http.get(f'/api/trips/{trip_id}/events')
    stranger = await http.get(f'/api/trips/{trip_id}/events', headers=_cookie(stranger_raw))
    missing = await http.get(f'/api/trips/{unknown}/events', headers=_cookie(stranger_raw))

    assert signed_out.status_code == 401
    assert stranger.status_code == 404
    assert missing.status_code == 404
    assert stranger.json() == missing.json()


async def test_a_member_never_receives_another_trips_events(
    live_server: LiveServer, http: httpx.AsyncClient, make_member: MakeMember, sync_conn: Conn
) -> None:
    _, maya_raw = await make_member('Maya')
    _, omar_raw = await make_member('Omar')
    (_, sam_raw), (_, theo_raw) = [await make_member(name) for name in ('Sam', 'Theo')]
    maya_trip = await _start_trip(http, maya_raw, 'Maya trip')
    omar_trip = await _start_trip(http, omar_raw, 'Omar trip')

    async with open_stream(live_server, maya_raw, maya_trip) as stream:
        await _join(http, omar_raw, omar_trip, sam_raw)
        await _join(http, maya_raw, maya_trip, theo_raw)
        event = await stream.next_event()

    assert event['id'] == str(_event_ids(sync_conn, maya_trip)[-1])
    assert event['id'] not in {str(i) for i in _event_ids(sync_conn, omar_trip)}


async def test_a_removed_member_gets_the_removal_then_the_stream_ends(
    live_server: LiveServer, http: httpx.AsyncClient, make_member: MakeMember
) -> None:
    _, maya_raw = await make_member('Maya')
    sam, sam_raw = await make_member('Sam')
    trip_id = await _start_trip(http, maya_raw)
    await _join(http, maya_raw, trip_id, sam_raw)

    async with open_stream(live_server, sam_raw, trip_id) as stream:
        removed = await http.post(
            f'/api/trips/{trip_id}/members/{sam.id}/remove', headers=_cookie(maya_raw)
        )
        assert removed.status_code == 200, removed.text
        event = await stream.next_event()
        assert event['event'] == 'member.removed'
        assert await stream.ended()

    again = await http.get(f'/api/trips/{trip_id}/events', headers=_cookie(sam_raw))
    assert again.status_code == 404


async def test_events_still_arrive_after_the_listener_connection_is_killed(
    live_server: LiveServer,
    http: httpx.AsyncClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    _, maya_raw = await make_member('Maya')
    _, sam_raw = await make_member('Sam')
    trip_id = await _start_trip(http, maya_raw)

    async with open_stream(live_server, maya_raw, trip_id) as stream:
        killed = sync_conn.execute(
            'SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity '
            "WHERE application_name = 'trippilot-listener' AND pid <> pg_backend_pid()"
        ).fetchone()
        assert killed is not None
        assert int(str(killed[0])) >= 1
        await _join(http, maya_raw, trip_id, sam_raw)
        event = await stream.next_event()

    assert event['event'] == 'member.joined'
    assert event['id'] == str(_event_ids(sync_conn, trip_id)[-1])


async def test_a_row_seen_by_both_replay_and_live_delivery_is_sent_once(
    live_server: LiveServer,
    http: httpx.AsyncClient,
    make_member: MakeMember,
    sync_conn: Conn,
) -> None:
    _, maya_raw = await make_member('Maya')
    guests = [await make_member(name) for name in ('Sam', 'Theo', 'Uma')]
    trip_id = await _start_trip(http, maya_raw)
    await _join(http, maya_raw, trip_id, guests[0][1])
    await _join(http, maya_raw, trip_id, guests[1][1])
    first, second = _event_ids(sync_conn, trip_id)

    async with open_stream(live_server, maya_raw, trip_id, last_event_id=first) as stream:
        replayed = await stream.next_event()
        # The same row arrives again through the live path, as it would if it committed
        # between the subscribe and the replay.
        live_server.app.state.trip_hub.publish(
            uuid.UUID(trip_id),
            StreamEvent(id=second, trip_id=uuid.UUID(trip_id), type='member.joined', payload={}),
        )
        await _join(http, maya_raw, trip_id, guests[2][1])
        following = await stream.next_event()

    assert replayed['id'] == str(second)
    assert following['id'] == str(_event_ids(sync_conn, trip_id)[-1])
    assert following['id'] != replayed['id']
