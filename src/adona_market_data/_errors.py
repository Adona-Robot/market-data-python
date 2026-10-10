"""Refusals, as the API states them.

Every refusal of the API carries a code in capitals at the start of its ``detail``
(a validation error adds a colon and the reason). Branch on the code, never on the
message: the codes are a published, frozen list (https://adona-robot.com/en/reference).
"""

from __future__ import annotations


class AdonaError(Exception):
    """Base class of every error this package raises."""


class Refused(AdonaError):
    """The API answered with a refusal.

    ``status`` is the HTTP status (0 for a network failure), ``code`` the part of
    ``detail`` before the first colon, ``detail`` the whole text, and ``fields`` the
    offending fields of a validation error, as the API sent them.
    """

    def __init__(self, status: int, code: str, detail: str = "", fields: list | None = None, retry_after: float | None = None):
        super().__init__(f"{status} {code}" + (f": {detail}" if detail and detail != code else ""))
        self.status = status
        self.code = code
        self.detail = detail
        self.fields = fields or []
        self.retry_after = retry_after

    @property
    def is_answer(self) -> bool:
        """True when retrying the same call cannot change the result: an access cut,
        an ended trial, a bad request. False for what waiting can clear."""
        return not retryable(self.status, self.code)


class StreamStopped(AdonaError):
    """The live stream stopped for a reason reconnecting would not change.

    ``code`` is the close reason the API sent (for example ``CUSTOMER_TRIAL_EXPIRED``)
    or the refusal code of the ticket request.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def code_of(detail: str) -> str:
    """The code a ``detail`` starts with: ``"INVALID_REQUEST: limit"`` gives ``INVALID_REQUEST``."""
    return detail.split(":", 1)[0].strip()


def retryable(status: int, code: str) -> bool:
    """Whether waiting can clear this refusal.

    The network (status 0) and the server's own errors (5xx) are temporary. A 429
    clears by waiting, except ``CUSTOMER_DAILY_CAP``, which reopens only the next UTC
    day. Everything else is an answer.
    """
    if status == 0 or status >= 500:
        return True
    if status == 429:
        return code != "CUSTOMER_DAILY_CAP"
    return False
