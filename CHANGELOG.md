# Changelog

## 0.1.0 - unreleased

First version.

- `Client`: the API key exchanged for a token per end user, renewed before it expires,
  and replaced once when the API retires it.
- `candles()`, `iter_pages()` and `page()`: candle history by REST on S1 to D1, paged
  back with the cursor. `since=` reads back to an instant.
- `to_pandas()`: a DataFrame indexed by time in UTC, with float prices by default or
  exact `Decimal` prices.
- `stream()`: quotes and bars on the live WebSocket, with the ticket offered as a
  subprotocol, a backoff on reconnect, and a stop on the closes that reconnecting
  cannot change.
- `Refused` carries the API's code. Only what waiting can clear is retried, honouring
  `Retry-After`.
