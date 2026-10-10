"""A thin client for the adona-robot market-data API: FX and metals candles by REST,
and the live bid, ask and bars on one WebSocket.

No data ships with this package: everything is read from the API with your key.
"""

from ._client import API, PAGE_MAX, TIMEFRAMES, Client
from ._errors import AdonaError, Refused, StreamStopped
from ._models import Bar, Candle, Quote, candles_to_pandas

__version__ = "0.1.0"

__all__ = [
    "API",
    "PAGE_MAX",
    "TIMEFRAMES",
    "AdonaError",
    "Bar",
    "Candle",
    "Client",
    "Quote",
    "Refused",
    "StreamStopped",
    "candles_to_pandas",
    "__version__",
]
