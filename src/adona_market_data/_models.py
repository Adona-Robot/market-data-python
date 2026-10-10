"""What the API sends back, as Python values.

Prices travel as strings and become :class:`decimal.Decimal` here, so no digit is
rounded on the way: convert to ``float`` only where you choose to (``to_pandas`` does,
by default, because that is what a chart or a backtest wants).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping


def parse_time(value: str) -> datetime:
    """An RFC 3339 instant as an aware UTC datetime (``Z`` or an offset)."""
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_time(moment: datetime) -> str:
    """An aware datetime as the API reads it, RFC 3339 in UTC."""
    if moment.tzinfo is None:
        raise ValueError("pass an aware datetime (for example datetime.now(timezone.utc))")
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Candle:
    """One OHLC bar of the bid.

    ``time`` is the bar's open time in UTC. ``volume`` is a tick volume: the number of
    price updates received in the bar, not a traded volume.
    """

    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> "Candle":
        """A candle of ``GET /v1/candles`` (long keys)."""
        return cls(
            time=parse_time(str(raw["time"])),
            open=Decimal(str(raw["open"])),
            high=Decimal(str(raw["high"])),
            low=Decimal(str(raw["low"])),
            close=Decimal(str(raw["close"])),
            volume=int(Decimal(str(raw["volume"]))),
        )

    @classmethod
    def from_stream(cls, raw: Mapping[str, Any]) -> "Candle":
        """A live bar of the stream's ``candle.bar`` frame (short keys)."""
        return cls(
            time=parse_time(str(raw["ts"])),
            open=Decimal(str(raw["o"])),
            high=Decimal(str(raw["h"])),
            low=Decimal(str(raw["l"])),
            close=Decimal(str(raw["c"])),
            volume=int(Decimal(str(raw["v"]))),
        )


@dataclass(frozen=True)
class Quote:
    """The live bid and ask of a symbol."""

    symbol: str
    bid: Decimal
    ask: Decimal
    as_of: datetime

    @classmethod
    def from_stream(cls, raw: Mapping[str, Any]) -> "Quote":
        return cls(
            symbol=str(raw["symbol"]),
            bid=Decimal(str(raw["bid"])),
            ask=Decimal(str(raw["ask"])),
            as_of=parse_time(str(raw["as_of"])),
        )


@dataclass(frozen=True)
class Bar:
    """A bar on the stream, with the channel it belongs to (``candle:EURUSD:M1``).

    ``snapshot`` is True for the recent bars a channel sends on (re)subscribe, which
    are billed like a REST page, and False for a bar that has just closed.
    """

    channel: str
    candle: Candle
    snapshot: bool


def candles_to_pandas(candles: list[Candle], decimals: bool = False):
    """A DataFrame indexed by the bar's open time (UTC), one column per field.

    Prices are floats unless ``decimals`` is True, in which case they stay
    :class:`~decimal.Decimal` (object columns). Needs ``pip install "adona-market-data[pandas]"``.
    """
    try:
        import pandas as pd
    except ImportError as error:  # pragma: no cover - exercised without pandas only
        raise ImportError('to_pandas needs pandas: pip install "adona-market-data[pandas]"') from error
    convert = (lambda value: value) if decimals else float
    frame = pd.DataFrame(
        {
            "open": [convert(c.open) for c in candles],
            "high": [convert(c.high) for c in candles],
            "low": [convert(c.low) for c in candles],
            "close": [convert(c.close) for c in candles],
            "volume": [c.volume for c in candles],
        },
        index=pd.DatetimeIndex([c.time for c in candles], name="time"),
    )
    return frame
