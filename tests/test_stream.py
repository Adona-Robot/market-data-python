"""The live half: frames into events, closes into decisions, and one real socket."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from adona_market_data import Bar, Quote, StreamStopped
from adona_market_data._stream import close_policy, events_of


def test_a_quote_frame_is_a_quote():
    [quote] = events_of({"type": "quote.update", "payload": {"symbol": "XAUUSD", "bid": "2400.10", "ask": "2400.40", "as_of": "2026-10-09T12:00:00.250Z"}})
    assert isinstance(quote, Quote) and str(quote.ask) == "2400.40"


def test_a_live_bar_gets_its_channel_back():
    [event] = events_of({"type": "candle.bar", "payload": {"symbol": "EURUSD", "tf": "M1", "ts": "2026-10-09T12:00:00Z", "o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15", "v": 9}})
    assert isinstance(event, Bar) and event.channel == "candle:EURUSD:M1" and not event.snapshot
    assert event.candle.volume == 9


def test_a_snapshot_is_marked_as_one():
    raw = {"time": "2026-10-09T12:00:00Z", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"}
    events = events_of({"type": "candle.snapshot", "payload": {"channel": "candle:EURUSD:S1", "candles": [raw, raw]}})
    assert len(events) == 2 and all(e.snapshot for e in events)


def test_control_frames_carry_no_event():
    assert events_of({"type": "subscribed", "payload": {}}) == []


@pytest.mark.parametrize(
    ("code", "reason", "revoked", "tickets", "action"),
    [
        (1008, "CUSTOMER_TRIAL_EXPIRED", 0, 0, "stop"),
        (1008, "CUSTOMER_CONNECTION_LIMIT", 0, 0, "stop"),
        (1008, "CUSTOMER_ACCESS_REVOKED", 0, 0, "fresh_token"),
        (1008, "CUSTOMER_ACCESS_REVOKED", 1, 0, "stop"),
        (1008, "INVALID_TICKET", 0, 0, "again"),
        (1008, "INVALID_TICKET", 0, 1, "stop"),
        (1008, "RATE_LIMITED", 0, 0, "later"),
        (1009, "FRAME_TOO_LARGE", 0, 0, "stop"),
        (1011, "REDIS_NOT_AVAILABLE", 0, 0, "later"),
        (None, "", 0, 0, "later"),
    ],
)
def test_each_close_has_its_decision(code, reason, revoked, tickets, action):
    assert close_policy(code, reason, revoked, tickets) == action


class FakeClient:
    def __init__(self):
        self.tickets = 0

    def ws_ticket(self):
        self.tickets += 1
        return f"t{self.tickets}"

    def token(self, fresh=False):
        return "tok"


async def test_a_real_socket_subscribes_with_the_ticket_and_yields_events():
    seen = {}

    async def handler(ws):
        seen["subprotocols"] = ws.request.headers.get("Sec-WebSocket-Protocol")
        seen["subscribe"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "subscribed", "payload": {"rejected": []}}))
        await ws.send(json.dumps({"type": "quote.update", "payload": {"symbol": "EURUSD", "bid": "1.1", "ask": "1.2", "as_of": "2026-10-09T12:00:00Z"}}))
        await asyncio.sleep(1)

    async with serve(handler, "127.0.0.1", 0, subprotocols=["adona.data.v1"]) as server:
        port = server.sockets[0].getsockname()[1]
        from adona_market_data._stream import stream

        events = stream(FakeClient(), ["quote:EURUSD"], url=f"ws://127.0.0.1:{port}")
        event = await asyncio.wait_for(events.__anext__(), 5)
        await events.aclose()
    assert isinstance(event, Quote) and event.symbol == "EURUSD"
    assert seen["subprotocols"] == "adona.data.v1, ticket.t1"
    assert seen["subscribe"] == {"type": "subscribe", "request_id": "sub", "payload": {"channels": ["quote:EURUSD"]}}


async def test_an_ended_trial_stops_the_stream():
    async def handler(ws):
        await ws.close(1008, "CUSTOMER_TRIAL_EXPIRED")

    async with serve(handler, "127.0.0.1", 0, subprotocols=["adona.data.v1"]) as server:
        port = server.sockets[0].getsockname()[1]
        from adona_market_data._stream import stream

        with pytest.raises(StreamStopped) as caught:
            await asyncio.wait_for(stream(FakeClient(), ["quote:EURUSD"], url=f"ws://127.0.0.1:{port}").__anext__(), 5)
    assert caught.value.code == "CUSTOMER_TRIAL_EXPIRED"
