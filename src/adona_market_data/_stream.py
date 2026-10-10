"""The live half: one WebSocket, quotes and bars as they arrive.

Opened with a single-use ticket offered as the second subprotocol, never in the URL.
Reconnects through deploys and network loss with a jittered backoff, and stops, raising
:class:`StreamStopped`, on the closes that reconnecting cannot change. Each
(re)subscribe sends the candle channels' recent bars again, which is metered: that is
what a reconnect costs, and why the backoff is not a tight loop.

Needs ``pip install "adona-market-data[stream]"`` (websockets 13 or later).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING, AsyncIterator, Union

from ._errors import Refused, StreamStopped
from ._models import Bar, Candle, Quote

if TYPE_CHECKING:  # pragma: no cover
    from ._client import Client

log = logging.getLogger("adona_market_data.stream")

STREAM = "wss://api.adona-robot.com/v1/stream"
SUBPROTOCOL = "adona.data.v1"
#: The most channels one subscribe frame takes.
MAX_CHANNELS = 64
#: Close reasons on 1008 that are answers: stop rather than reconnect.
STOP_REASONS = ("CUSTOMER_TRIAL_EXPIRED", "CUSTOMER_CONNECTION_LIMIT", "EXPECTED_DATA_TOKEN")
#: Wait before asking again once the plan's slices for the minute are spent.
MINUTE_CEILING_WAIT = 15.0

Event = Union[Quote, Bar]


def backoff(failures: int) -> float:
    """Seconds before reconnect number ``failures`` (0-based): doubling, capped at
    30 s, with jitter so a fleet of clients does not come back in step."""
    return min(30.0, 2.0**failures) * (0.5 + random.random() / 2)


def events_of(frame: dict) -> list[Event]:
    """The quotes and bars a frame carries (none for control frames)."""
    kind = frame.get("type")
    payload = frame.get("payload") or {}
    if kind in ("quote.update", "quote.snapshot"):
        return [Quote.from_stream(payload)]
    if kind == "candle.snapshot":
        channel = str(payload.get("channel", ""))
        return [Bar(channel, Candle.from_api(raw), snapshot=True) for raw in payload.get("candles") or []]
    if kind == "candle.bar":
        # Live bars use short keys and carry no channel: rebuild it.
        return [Bar(f"candle:{payload['symbol']}:{payload['tf']}", Candle.from_stream(payload), snapshot=False)]
    return []


def close_policy(code: int | None, reason: str, revoked_retries: int, ticket_retries: int) -> str:
    """What to do after a close: ``"stop"``, ``"fresh_token"`` (ask for a new token,
    then reconnect), ``"again"`` (a new ticket at once) or ``"later"`` (backoff)."""
    if code == 1008:
        if reason in STOP_REASONS:
            return "stop"
        if reason == "CUSTOMER_ACCESS_REVOKED":
            # A key rotation retires the token: a fresh one, once. Twice is an answer.
            return "fresh_token" if revoked_retries == 0 else "stop"
        if reason == "INVALID_TICKET":
            return "again" if ticket_retries == 0 else "stop"
        # RATE_LIMITED, or a reason this version does not know: slow down.
        return "later"
    if code == 1009:
        return "stop"  # FRAME_TOO_LARGE: split the subscription
    return "later"  # 1011 is ours and temporary; anything else is the network


async def stream(client: "Client", channels: list[str], url: str = STREAM) -> AsyncIterator[Event]:
    """Quotes and bars for ``channels`` (``quote:EURUSD``, ``candle:EURUSD:M1``), for
    as long as the caller iterates. Break out of the loop to close the socket."""
    try:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed
    except ImportError as error:  # pragma: no cover
        raise ImportError('the stream needs websockets: pip install "adona-market-data[stream]"') from error
    if not channels or len(channels) > MAX_CHANNELS:
        raise ValueError(f"between 1 and {MAX_CHANNELS} channels")
    subscribe = json.dumps({"type": "subscribe", "request_id": "sub", "payload": {"channels": list(channels)}})

    failures = 0
    revoked_retries = 0
    ticket_retries = 0
    while True:
        try:
            ticket = await asyncio.to_thread(client.ws_ticket)
        except Refused as refused:
            if refused.is_answer:
                raise StreamStopped(refused.code) from refused
            await asyncio.sleep(backoff(failures))
            failures += 1
            continue

        close_code, close_reason = None, ""
        resubscribe: asyncio.Task | None = None
        try:
            async with connect(url, subprotocols=[SUBPROTOCOL, f"ticket.{ticket}"]) as socket:
                await socket.send(subscribe)
                try:
                    async for message in socket:
                        frame = json.loads(message)
                        kind = frame.get("type")
                        if kind == "subscribed":
                            failures = revoked_retries = ticket_retries = 0
                            rejected = (frame.get("payload") or {}).get("rejected") or []
                            if rejected:
                                log.warning("not in your account's list: %s", rejected)
                        elif kind == "error":
                            code = str((frame.get("payload") or {}).get("code", ""))
                            if code == "CUSTOMER_DAILY_CAP":
                                raise StreamStopped(code)
                            if code == "CUSTOMER_MINUTE_CEILING" and (resubscribe is None or resubscribe.done()):
                                # The subscribe was undone; ask again once the minute turns.
                                resubscribe = asyncio.create_task(_later(socket, subscribe, MINUTE_CEILING_WAIT))
                            elif code != "CUSTOMER_MINUTE_CEILING":
                                log.warning("stream error: %s", code)
                        for event in events_of(frame):
                            yield event
                finally:
                    if resubscribe is not None:
                        resubscribe.cancel()
        except ConnectionClosed as closed:
            frame = closed.rcvd
            close_code, close_reason = (frame.code, frame.reason) if frame else (None, "")
        except OSError:
            close_code = None

        action = close_policy(close_code, close_reason, revoked_retries, ticket_retries)
        if action == "stop":
            raise StreamStopped(close_reason or f"CLOSE_{close_code}")
        if action == "fresh_token":
            revoked_retries += 1
            await asyncio.to_thread(client.token, True)
        elif action == "again":
            ticket_retries += 1
        else:
            await asyncio.sleep(backoff(failures))
            failures += 1


async def _later(socket, message: str, delay: float) -> None:
    await asyncio.sleep(delay)
    await socket.send(message)
