"""Setting types storefronts share: a usable duration and a site authority's origin.

Each rule is a plain function that returns the value as the storefront uses it
or raises ``ValueError`` with a reason naming no configured value, and a Pydantic
annotated type over that function. A typed settings model declares a field with
the type; a loader reading untyped settings validates through a ``TypeAdapter``
of it; and a values schema generated from a typed model carries the type's
JSON schema. A caller reporting a refusal prefixes the reason with its key.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import PlainValidator, WithJsonSchema

#: The bound every duration stays below. ``timedelta.max.total_seconds()``
#: rounds up to a float that ``timedelta`` itself cannot hold, so the bound is
#: exclusive: every positive float below it builds a ``timedelta``.
MAX_SECONDS = timedelta.max.total_seconds()


def positive_seconds(value: Any) -> float:
    """A positive, finite number of seconds that ``timedelta`` can represent.

    A number or a numeric string is read as seconds. A boolean is refused
    rather than read as one or zero, and so are NaN, infinity, zero, a negative
    number, and anything at or above :data:`MAX_SECONDS`: a window compared
    against elapsed time is built as a ``timedelta``, which raises on a larger
    value at the comparison rather than at startup.
    """

    if isinstance(value, bool):
        raise ValueError("must be a number of seconds, not a boolean")
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, (int, float, str)):
        raise ValueError("must be a number of seconds")
    try:
        seconds = float(value)
    except ValueError:
        raise ValueError("must be a number of seconds") from None
    except OverflowError:
        seconds = math.inf
    if math.isnan(seconds) or seconds <= 0 or seconds == math.inf:
        raise ValueError("must be a positive, finite number of seconds")
    if seconds >= MAX_SECONDS:
        raise ValueError(
            f"must be below {MAX_SECONDS:.0f} seconds, the longest duration a "
            "timedelta holds"
        )
    return seconds


#: A positive, finite number of seconds below :data:`MAX_SECONDS`.
PositiveSeconds = Annotated[
    float,
    PlainValidator(positive_seconds, json_schema_input_type=float),
    WithJsonSchema(
        {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": MAX_SECONDS}
    ),
]


def site_authority_url(value: Any) -> str:
    """A site authority's HTTP(S) origin, without surrounding whitespace or a
    trailing ``/``.

    The origin is all a site's URL may state: an ``http`` or ``https`` scheme, a
    host, and optionally a numeric port. Credentials, a query, a fragment, and a
    path other than ``/`` are refused, because a client joins its own routes to
    the origin, so a path would become a prefix of every route.
    """

    if not isinstance(value, str):
        raise ValueError("must be a string")
    text = value.strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        raise ValueError("must be an HTTP(S) origin") from None
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("must be an HTTP(S) origin: its scheme is http or https")
    if not parsed.hostname:
        raise ValueError("must be an HTTP(S) origin naming a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("must be an HTTP(S) origin without credentials")
    if parsed.query or parsed.fragment or "?" in text or "#" in text:
        raise ValueError("must be an HTTP(S) origin without a query or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("must be an HTTP(S) origin without a path")
    try:
        # Reading the port parses it, raising for one that is not a number in
        # the port range.
        _ = parsed.port
    except ValueError:
        raise ValueError("must be an HTTP(S) origin with a numeric port") from None
    return text.rstrip("/")


#: A site authority's HTTP(S) origin, normalized by :func:`site_authority_url`.
SiteAuthorityUrl = Annotated[
    str,
    PlainValidator(site_authority_url, json_schema_input_type=str),
    WithJsonSchema({"type": "string"}),
]


__all__ = [
    "MAX_SECONDS",
    "PositiveSeconds",
    "SiteAuthorityUrl",
    "positive_seconds",
    "site_authority_url",
]
