# adona-market-data

A thin Python client for the [adona-robot](https://adona-robot.com/en) market-data API.
It covers 46 FX pairs and 5 metals (gold against the dollar and the euro, silver,
platinum, palladium), with OHLC candles from one second to one day by REST, and the live
bid, ask and closing bars on one WebSocket.

```bash
pip install adona-market-data              # candles by REST
pip install "adona-market-data[pandas]"    # + to_pandas()
pip install "adona-market-data[stream]"    # + the live stream
pip install "adona-market-data[all]"
```

No data ships with this package. Everything is read from the API with your key, and
every page you read is billed in slices of 1 000 bars from your plan.

## History

```python
from adona_market_data import Client

client = Client()  # the API key from ADONA_API_KEY; keep it on a server
bars = client.candles("EURUSD", "M1", bars=1440)  # the last 1 440 one-minute bars, oldest first
frame = client.to_pandas(bars)  # a DataFrame indexed by time (UTC): open, high, low, close, volume
```

- Timeframes are `S1`, `M1`, `M5`, `M15`, `H1`, `H4` and `D1`.
- `client.candles(..., since=datetime(...))` reads back to an instant.
- `client.iter_pages(...)` yields the pages one by one, newest first, if you want to stop early.

Prices arrive as strings and become `Decimal`, so no digit is rounded. `to_pandas()`
gives floats, or pass `decimals=True` to keep them exact.

A candle's `volume` is a tick volume: the number of price updates received in the bar,
not a traded volume.

## Live

```python
import asyncio
from adona_market_data import Bar, Client, Quote

async def main():
    client = Client()
    async for event in client.stream(["quote:XAUUSD", "candle:XAUUSD:M1"]):
        if isinstance(event, Quote):
            print(event.symbol, event.bid, event.ask)
        elif isinstance(event, Bar) and not event.snapshot:
            print(event.channel, event.candle.time, event.candle.close)

asyncio.run(main())
```

The stream reconnects through deploys and network loss with a backoff. It raises
`StreamStopped` on the closes that reconnecting cannot change: an ended trial, a key cut
off, a connection limit.

Each (re)subscribe sends the candle channels' recent bars again (`snapshot=True`), and
those bars are billed like a REST page.

## Refusals

Every refusal is a `Refused` with the API's code, for example `CUSTOMER_MINUTE_CEILING`
or `SYMBOL_NOT_ALLOWED`. It also carries the HTTP status, the fields of a validation
error and `Retry-After`.

The client retries only what waiting can clear:
- the network;
- the server's own errors;
- a 429 other than the daily guard, honouring `Retry-After`.

A retired token is replaced once. `refused.is_answer` tells you when retrying the same
call is pointless. Every code is listed, with what to do, in the
[API reference](https://adona-robot.com/en/reference).

## What it is, and what it is not

- **The depth.** One-minute bars and above go back to May 2025 for EURUSD, GBPUSD,
  USDJPY and XAUUSD, and to spring 2026 for the others. One-second bars are kept 180 days
  rolling. Each symbol's own dates are on its page, https://adona-robot.com/en/symbols.
  That suits a chart or a model on recent months, not a backtest over many years.
- **Where the key goes.** The API key stays on a server. A browser gets a short-lived
  token from your server instead: see the
  [quickstart](https://adona-robot.com/en/quickstart).
- **Trial and plans.** The free trial lasts 7 days, on EURUSD and XAUUSD. Plans are on
  https://adona-robot.com/en.

## Development

```bash
uv venv && uv pip install -e . pytest pytest-asyncio responses pandas "websockets>=13"
.venv/bin/python -m pytest
```

The tests run against recorded answers and a local WebSocket server. None of them calls
the API.

MIT licence for this code. The data you read through it is governed by the
[terms of service](https://adona-robot.com/en/terms).
