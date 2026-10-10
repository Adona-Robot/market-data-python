"""The REST half: tokens and candle history.

The API key belongs on your server. :class:`Client` exchanges it for a short-lived
token per end user (``POST /v1/tokens``), reads candles with that token, and retries
only what waiting can clear: the network, the server's own errors, and a 429 other
than the daily guard, honouring ``Retry-After``.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Iterator, Mapping

import requests

from ._errors import Refused, code_of, retryable
from ._models import Candle, candles_to_pandas, format_time

API = "https://api.adona-robot.com"
TIMEFRAMES = ("S1", "M1", "M5", "M15", "H1", "H4", "D1")
#: The most bars one ``GET /v1/candles`` page returns.
PAGE_MAX = 5000
#: A token is renewed this many seconds before it expires.
TOKEN_MARGIN_SECONDS = 60
#: Refusals that mean "this token is no longer good": a fresh one is asked for, once.
TOKEN_REFUSALS = ("INVALID_JWT", "CUSTOMER_ACCESS_REVOKED")


class Client:
    """A client of the adona-robot market-data API, for one end user.

    ``api_key`` defaults to the ``ADONA_API_KEY`` environment variable. Keep it on a
    server: it never goes to a browser. ``end_user_id`` names the person or the system
    the data is read for; the per-person limits of the API apply to it.

    >>> client = Client()                                # ADONA_API_KEY from the environment
    >>> bars = client.candles("EURUSD", "M1", bars=500)  # oldest first
    >>> frame = client.to_pandas(bars)                   # needs adona-market-data[pandas]
    """

    def __init__(
        self,
        api_key: str | None = None,
        end_user_id: str = "python",
        base_url: str = API,
        attempts: int = 6,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ):
        key = api_key if api_key is not None else os.environ.get("ADONA_API_KEY", "")
        if not key:
            raise ValueError("no API key: pass api_key= or set ADONA_API_KEY")
        self._key = key
        self.end_user_id = end_user_id
        self.base_url = base_url.rstrip("/")
        self.attempts = max(1, attempts)
        self.timeout = timeout
        self._session = session or requests.Session()
        self._sleep = sleep
        self._token: str | None = None
        self._token_until = 0.0
        #: The symbols the last token may read, as the API listed them.
        self.symbols: list[str] = []

    # ------------------------------------------------------------------ the token

    def token(self, fresh: bool = False) -> str:
        """A token for this end user, renewed before it expires (or now, if ``fresh``)."""
        if not fresh and self._token and time.time() < self._token_until:
            return self._token
        body = self._call("POST", "/v1/tokens", bearer=self._key, json={"end_user_id": self.end_user_id})
        self._token = str(body["access_token"])
        self._token_until = time.time() + max(0, int(body["expires_in"]) - TOKEN_MARGIN_SECONDS)
        self.symbols = list(body.get("symbols") or [])
        return self._token

    def ws_ticket(self) -> str:
        """A single-use ticket for the live stream (``POST /v1/ws-ticket``)."""
        return str(self._authed("POST", "/v1/ws-ticket")["ticket"])

    # ------------------------------------------------------------------ candles

    def page(self, symbol: str, timeframe: str, limit: int = PAGE_MAX, before: datetime | str | None = None) -> dict:
        """One page of ``GET /v1/candles``, as the API sent it: ``candles`` oldest
        first, and ``next_before``, the cursor to the page before it (``None`` when
        there is nothing older). Each page is billed in slices of 1000 bars."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
        params: dict[str, Any] = {"symbol": symbol, "timeframe": timeframe, "limit": max(1, min(PAGE_MAX, limit))}
        if before is not None:
            params["before"] = format_time(before) if isinstance(before, datetime) else before
        return self._authed("GET", "/v1/candles", params=params)

    def iter_pages(self, symbol: str, timeframe: str, before: datetime | str | None = None, limit: int = PAGE_MAX) -> Iterator[list[Candle]]:
        """Pages of candles going back in time, the newest page first, each page
        oldest first. Stops when the API says there is nothing older. On S1 a page
        covers one day, so an empty page with a cursor (a weekend) is skipped, not an end."""
        cursor = before
        while True:
            body = self.page(symbol, timeframe, limit=limit, before=cursor)
            yield [Candle.from_api(raw) for raw in body.get("candles") or []]
            cursor = body.get("next_before")
            if not cursor:
                return

    def candles(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 1000,
        before: datetime | str | None = None,
        since: datetime | None = None,
    ) -> list[Candle]:
        """The latest ``bars`` candles before ``before`` (now by default), oldest first.

        With ``since``, reads back to that instant instead (``bars`` is then a cap on
        how many to read). Every page read is billed: ask for what you need.
        """
        out: list[Candle] = []
        for page in self.iter_pages(symbol, timeframe, before=before, limit=min(PAGE_MAX, max(1, bars))):
            if since is not None:
                page = [c for c in page if c.time >= since]
            out[:0] = page
            if len(out) >= bars:
                break
            if since is not None and page and page[0].time <= since:
                break
            if since is not None and not page and timeframe != "S1":
                break
        return out[-bars:]

    def stream(self, channels: list[str], url: str | None = None):
        """Quotes and bars as they arrive, an async iterator (see :mod:`adona_market_data._stream`).

        >>> async for event in client.stream(["quote:XAUUSD", "candle:XAUUSD:M1"]):
        ...     print(event)
        """
        from ._stream import STREAM, stream

        return stream(self, channels, url or STREAM)

    @staticmethod
    def to_pandas(candles: list[Candle], decimals: bool = False):
        """The candles as a pandas DataFrame indexed by time (see :func:`candles_to_pandas`)."""
        return candles_to_pandas(candles, decimals=decimals)

    # ------------------------------------------------------------------ plumbing

    def _authed(self, method: str, path: str, **kwargs) -> dict:
        try:
            return self._call(method, path, bearer=self.token(), **kwargs)
        except Refused as refused:
            if refused.status == 401 and refused.code in TOKEN_REFUSALS:
                # An expired token, or one a key rotation retired: a fresh one, once.
                return self._call(method, path, bearer=self.token(fresh=True), **kwargs)
            raise

    def _call(self, method: str, path: str, bearer: str, **kwargs) -> dict:
        for attempt in range(self.attempts):
            status, code, detail, fields, retry_after = 0, "NETWORK", "", [], None
            try:
                response = self._session.request(
                    method,
                    self.base_url + path,
                    headers={"Authorization": f"Bearer {bearer}"},
                    timeout=self.timeout,
                    **kwargs,
                )
                if response.ok:
                    return response.json()
                status = response.status_code
                body = _json(response)
                detail = str(body.get("detail", "")) if isinstance(body, Mapping) else ""
                code = code_of(detail) or f"HTTP_{status}"
                fields = list(body.get("fields") or []) if isinstance(body, Mapping) else []
                retry_after = _seconds(response.headers.get("Retry-After"))
            except requests.RequestException as error:
                detail = str(error)
            if not retryable(status, code) or attempt == self.attempts - 1:
                raise Refused(status, code, detail, fields, retry_after)
            self._sleep(retry_after if retry_after else min(30.0, 2.0**attempt))
        raise AssertionError("unreachable")  # pragma: no cover


def _json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
