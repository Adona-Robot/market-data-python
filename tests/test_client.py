"""The REST half against recorded answers: no call ever reaches the API."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import responses

from adona_market_data import Client, Refused
from adona_market_data._client import API

TOKEN = {"access_token": "tok-1", "token_type": "bearer", "expires_in": 43200, "end_user_id": "python", "symbols": ["EURUSD"]}


def bar(minute: int, close: str = "1.10000") -> dict:
    return {"time": f"2026-10-09T12:{minute:02d}:00Z", "open": "1.09990", "high": "1.10010", "low": "1.09980", "close": close, "volume": "17"}


@pytest.fixture
def client():
    return Client(api_key="adk_test_x", sleep=lambda seconds: None)


@responses.activate
def test_a_key_is_exchanged_once_for_a_token_that_reads_candles(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"symbol": "EURUSD", "timeframe": "M1", "candles": [bar(0), bar(1)], "next_before": None})
    candles = client.candles("EURUSD", "M1", bars=10)
    assert [c.close for c in candles] == [Decimal("1.10000"), Decimal("1.10000")]
    assert candles[0].time == datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert candles[0].volume == 17
    client.candles("EURUSD", "M1", bars=10)
    assert [c.request.url.split("?")[0] for c in responses.calls].count(f"{API}/v1/tokens") == 1
    # The key goes to the token door only; the token reads.
    assert responses.calls[0].request.headers["Authorization"] == "Bearer adk_test_x"
    assert responses.calls[1].request.headers["Authorization"] == "Bearer tok-1"
    assert client.symbols == ["EURUSD"]


@responses.activate
def test_pages_are_followed_back_with_the_cursor_until_enough(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": [bar(2), bar(3)], "next_before": "2026-10-09T12:02:00Z"})
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0), bar(1)], "next_before": "2026-10-09T12:00:00Z"})
    candles = client.candles("EURUSD", "M1", bars=3)
    assert [c.time.minute for c in candles] == [1, 2, 3]
    assert "before=2026-10-09T12%3A02%3A00Z" in responses.calls[2].request.url


@responses.activate
def test_reading_stops_when_there_is_nothing_older(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0)], "next_before": None})
    assert len(client.candles("EURUSD", "M1", bars=1000)) == 1
    assert len(responses.calls) == 2


@responses.activate
def test_since_reads_back_to_an_instant(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": [bar(2), bar(3)], "next_before": "2026-10-09T12:02:00Z"})
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0), bar(1)], "next_before": "2026-10-09T12:00:00Z"})
    since = datetime(2026, 10, 9, 12, 1, tzinfo=timezone.utc)
    assert [c.time.minute for c in client.candles("EURUSD", "M1", since=since)] == [1, 2, 3]
    assert len(responses.calls) == 3  # no third page


@responses.activate
def test_an_empty_one_second_day_is_skipped_not_an_end(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": [], "next_before": "2026-10-04T00:00:00Z"})
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0)], "next_before": None})
    assert len(client.candles("EURUSD", "S1", bars=5)) == 1


@responses.activate
def test_a_429_waits_for_retry_after_then_succeeds():
    waits = []
    client = Client(api_key="adk_test_x", sleep=waits.append)
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", status=429, json={"detail": "CUSTOMER_MINUTE_CEILING"}, headers={"Retry-After": "7"})
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0)], "next_before": None})
    assert len(client.candles("EURUSD", "M1")) == 1
    assert waits == [7.0]


@responses.activate
def test_the_daily_cap_is_an_answer_not_a_wait(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", status=429, json={"detail": "CUSTOMER_DAILY_CAP"})
    with pytest.raises(Refused) as caught:
        client.candles("EURUSD", "M1")
    assert caught.value.code == "CUSTOMER_DAILY_CAP" and caught.value.is_answer
    assert len(responses.calls) == 2


@responses.activate
def test_a_validation_error_carries_its_code_and_fields(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(
        f"{API}/v1/candles",
        status=422,
        json={"detail": "SYMBOL_UNKNOWN: no such symbol", "fields": [{"loc": ["query", "symbol"], "reason": "unknown"}]},
    )
    with pytest.raises(Refused) as caught:
        client.page("NOPE", "M1")
    assert caught.value.code == "SYMBOL_UNKNOWN"
    assert caught.value.fields == [{"loc": ["query", "symbol"], "reason": "unknown"}]


@responses.activate
def test_a_retired_token_is_replaced_once(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", status=401, json={"detail": "INVALID_JWT"})
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0)], "next_before": None})
    assert len(client.candles("EURUSD", "M1")) == 1
    assert [c.request.url.split("?")[0] for c in responses.calls].count(f"{API}/v1/tokens") == 2


@responses.activate
def test_a_wrong_key_is_not_retried(client):
    responses.post(f"{API}/v1/tokens", status=401, json={"detail": "INVALID_CUSTOMER_KEY"})
    with pytest.raises(Refused) as caught:
        client.token()
    assert caught.value.code == "INVALID_CUSTOMER_KEY"
    assert len(responses.calls) == 1


def test_no_key_is_refused_before_any_call(monkeypatch):
    monkeypatch.delenv("ADONA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        Client()


def test_a_bad_timeframe_is_refused_before_any_call(client):
    with pytest.raises(ValueError):
        client.page("EURUSD", "M2")


@responses.activate
def test_to_pandas_indexes_by_time_with_float_prices(client):
    responses.post(f"{API}/v1/tokens", json=TOKEN)
    responses.get(f"{API}/v1/candles", json={"candles": [bar(0), bar(1, "1.20000")], "next_before": None})
    frame = client.to_pandas(client.candles("EURUSD", "M1"))
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.index.name == "time" and str(frame.index.tz) == "UTC"
    assert frame["close"].iloc[-1] == 1.2
    exact = client.to_pandas(client.candles("EURUSD", "M1"), decimals=True)
    assert exact["close"].iloc[-1] == Decimal("1.20000")
