"""Candles from the API for vectorbt.

    import vectorbt as vbt
    from adona_market_data import Client
    from adona_market_data.vectorbt import AdonaData

    data = AdonaData.download(["EURUSD", "GBPUSD"], client=Client(), timeframe="M15", bars=3000)
    close = data.get("Close")
    portfolio = vbt.Portfolio.from_signals(close, close > close.rolling(20).mean(), close < close.rolling(20).mean())

Each symbol is read once per ``download``; columns are vectorbt's ``Open``, ``High``,
``Low``, ``Close`` and ``Volume`` (the tick volume), indexed in UTC. The archive is
recent (one-minute bars since May 2025 for EURUSD, GBPUSD, USDJPY and XAUUSD, spring
2026 for the others), so this is for strategies tested on recent months.

``ohlcv()`` gives the same frame without vectorbt. ``AdonaData`` needs
``pip install "adona-market-data[vectorbt]"`` on Python 3.11 or later.
"""

from __future__ import annotations

from datetime import datetime

from ._client import Client

COLUMNS = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


def ohlcv(client: Client, symbol: str, timeframe: str = "M1", bars: int = 1000, since: datetime | None = None):
    """One symbol's candles with vectorbt's column names, indexed by time in UTC."""
    frame = client.to_pandas(client.candles(symbol, timeframe, bars=bars, since=since))
    return frame.rename(columns=COLUMNS)


try:
    import vectorbt as _vbt
except Exception:  # pragma: no cover - absent, or an install that fails on import
    # ohlcv() must keep working without a usable vectorbt; only the class needs it.
    _vbt = None

if _vbt is not None:

    class AdonaData(_vbt.Data):
        """``vbt.Data`` reading from the adona-robot API: pass ``client=`` (a
        :class:`~adona_market_data.Client`), ``timeframe=``, and ``bars=`` or ``since=``
        to :meth:`download`, which vectorbt hands to each symbol's read."""

        @classmethod
        def download_symbol(
            cls,
            symbol,
            client: Client | None = None,
            timeframe: str = "M1",
            bars: int = 1000,
            since: datetime | None = None,
            **kwargs,
        ):
            return ohlcv(client or Client(), str(symbol), timeframe=timeframe, bars=bars, since=since)
