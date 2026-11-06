"""Candles from the API as a backtrader data feed.

    import backtrader as bt
    from adona_market_data import Client
    from adona_market_data.backtrader import feed

    cerebro = bt.Cerebro()
    cerebro.adddata(feed(Client(), "EURUSD", "M5", bars=5000), name="EURUSD")

The feed is read once, when it is built: backtrader replays it from memory, so a
backtest run twice reads the API once. The archive is recent (one-minute bars since
May 2025 for EURUSD, GBPUSD, USDJPY and XAUUSD, spring 2026 for the others; one
second kept 180 days), so this is for strategies tested on recent months.

Needs ``pip install "adona-market-data[backtrader]"``.
"""

from __future__ import annotations

from datetime import datetime

from ._client import Client

#: Each API timeframe as backtrader's (timeframe name, compression).
TIMEFRAMES = {
    "S1": ("Seconds", 1),
    "M1": ("Minutes", 1),
    "M5": ("Minutes", 5),
    "M15": ("Minutes", 15),
    "H1": ("Minutes", 60),
    "H4": ("Minutes", 240),
    "D1": ("Days", 1),
}


def feed(client: Client, symbol: str, timeframe: str, bars: int = 5000, since: datetime | None = None, **kwargs):
    """A ``bt.feeds.PandasData`` of the latest ``bars`` candles (or back to ``since``).

    Times are UTC, as naive datetimes, which is what backtrader expects. The volume is
    the tick volume (price updates in the bar), and there is no open interest. Extra
    keyword arguments go to ``PandasData`` (``fromdate``, ``todate``, ``name``...).
    """
    try:
        import backtrader as bt
    except ImportError as error:  # pragma: no cover
        raise ImportError('this needs backtrader: pip install "adona-market-data[backtrader]"') from error
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    frame = client.to_pandas(client.candles(symbol, timeframe, bars=bars, since=since))
    frame.index = frame.index.tz_convert("UTC").tz_localize(None)
    name, compression = TIMEFRAMES[timeframe]
    return bt.feeds.PandasData(
        dataname=frame,
        timeframe=getattr(bt.TimeFrame, name),
        compression=compression,
        openinterest=None,
        **kwargs,
    )
