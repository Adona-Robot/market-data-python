"""backtrader and vectorbt, fed from recorded answers: no call reaches the API."""

import pytest
import responses

from adona_market_data import Client
from adona_market_data._client import API

TOKEN = {"access_token": "tok", "expires_in": 43200, "end_user_id": "python", "symbols": ["EURUSD", "GBPUSD"]}


def bars(n: int, base: float = 1.1) -> list[dict]:
    out = []
    for i in range(n):
        price = f"{base + (i % 7) * 0.0001 - (i % 3) * 0.00005:.5f}"
        out.append({"time": f"2026-10-09T{10 + i // 60:02d}:{i % 60:02d}:00Z", "open": price, "high": price, "low": price, "close": price, "volume": str(10 + i)})
    return out


@pytest.fixture
def client():
    return Client(api_key="adk_test_x", sleep=lambda seconds: None)


@responses.activate
def test_a_backtrader_feed_runs_a_strategy_over_the_candles(client):
    bt = pytest.importorskip("backtrader")
    from adona_market_data.backtrader import feed

    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": bars(120), "next_before": None})
    seen = []

    class Count(bt.Strategy):
        def next(self):
            seen.append((self.data.datetime.datetime(0), self.data.close[0], self.data.volume[0]))

    cerebro = bt.Cerebro()
    cerebro.adddata(feed(client, "EURUSD", "M1", bars=120), name="EURUSD")
    cerebro.addstrategy(Count)
    cerebro.run()
    assert len(seen) == 120
    assert seen[0][0].hour == 10 and seen[0][0].minute == 0  # UTC, naive
    assert seen[-1][2] == 129  # the tick volume


def test_a_backtrader_feed_refuses_an_unknown_timeframe(client):
    pytest.importorskip("backtrader")
    from adona_market_data.backtrader import feed

    with pytest.raises(ValueError):
        feed(client, "EURUSD", "M2")


@responses.activate
def test_ohlcv_uses_vectorbt_s_column_names(client):
    from adona_market_data.vectorbt import ohlcv

    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": bars(5), "next_before": None})
    frame = ohlcv(client, "EURUSD", "M1", bars=5)
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert str(frame.index.tz) == "UTC"


@responses.activate
def test_vectorbt_downloads_each_symbol_once_and_backtests(client):
    vbt = pytest.importorskip("vectorbt")
    from adona_market_data.vectorbt import AdonaData

    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": bars(60, 1.1), "next_before": None})
    responses.get(f"{API}/v1/candles", json={"candles": bars(60, 1.3), "next_before": None})
    data = AdonaData.download(["EURUSD", "GBPUSD"], client=client, timeframe="M1", bars=60)
    close = data.get("Close")
    assert list(close.columns) == ["EURUSD", "GBPUSD"] and len(close) == 60
    assert sum(1 for c in responses.calls if "/v1/candles" in c.request.url) == 2
    fast, slow = close.rolling(3).mean(), close.rolling(9).mean()
    portfolio = vbt.Portfolio.from_signals(close, fast > slow, fast < slow)
    assert len(portfolio.total_return()) == 2
