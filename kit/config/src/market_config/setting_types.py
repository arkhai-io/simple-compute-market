"""Setting types storefronts share: a usable duration and a site authority's origin.

Each rule is a plain function that returns the value as the storefront uses it
or raises ``ValueError`` with a reason naming no configured value, and a Pydantic
annotated type over that function. A typed settings model declares a field with
the type, and a loader reading untyped settings validates through a
``TypeAdapter`` of it. A caller reporting a refusal prefixes the reason with its
key.

A refusal is raised outside any ``except`` block, so it carries no exception
context either: a parsing error keeps the value it failed on.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import AnyHttpUrl, PlainValidator, TypeAdapter, ValidationError, WithJsonSchema

#: The longest duration a setting may state: the span from 0001-01-01 to the
#: Unix epoch, about 1,969 years. A duration is added to or subtracted from an
#: instant -- a watchdog's "now minus the timeout", a confirmation compared
#: with elapsed time -- so it must stay inside ``datetime``'s range wherever it
#: is applied, not merely build a ``timedelta``. Subtracted from any instant
#: after 1970 it stays after year 1, and added to any instant before about
#: 8030 it stays before year 9999.
MAX_SECONDS = (datetime(1970, 1, 1) - datetime(1, 1, 1)).total_seconds()

_DURATION_REFUSED = "must be a positive, finite number of seconds"


def _seconds(value: Any) -> float | None:
    """``value`` as a float, or ``None`` when it is not a number of seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value.strip() if isinstance(value, str) else value)
    except ValueError:
        return None
    except OverflowError:
        return math.inf


def positive_seconds(value: Any) -> float:
    """A positive, finite number of seconds, at most :data:`MAX_SECONDS`.

    A number or a numeric string is read as seconds. A boolean is refused
    rather than read as one or zero, and so are NaN, infinity, zero, a negative
    number, one too small to survive conversion to a ``timedelta`` (below half
    a microsecond, which rounds to zero), and one longer than
    :data:`MAX_SECONDS`, which would carry an instant out of ``datetime``'s
    range where it is applied rather than at startup.
    """

    if isinstance(value, bool):
        raise ValueError("must be a number of seconds, not a boolean")
    seconds = _seconds(value)
    if seconds is None:
        raise ValueError("must be a number of seconds")
    if math.isnan(seconds) or math.isinf(seconds) or seconds <= 0:
        raise ValueError(_DURATION_REFUSED)
    if seconds > MAX_SECONDS:
        raise ValueError(
            f"must be at most {MAX_SECONDS:.0f} seconds, so that applying it to "
            "an instant stays inside datetime's range"
        )
    if timedelta(seconds=seconds) == timedelta(0):
        raise ValueError(f"{_DURATION_REFUSED} of at least a microsecond")
    return seconds


#: A positive, finite number of seconds, at most :data:`MAX_SECONDS`.
PositiveSeconds = Annotated[
    float,
    PlainValidator(positive_seconds, json_schema_input_type=float),
    WithJsonSchema({"type": "number", "exclusiveMinimum": 0, "maximum": MAX_SECONDS}),
]

_NOT_AN_ORIGIN = "must be an HTTP(S) origin"

#: U+0000 to U+001F and U+007F, which the URL standard strips or drops.
_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: Parses a URL as the WHATWG URL standard does, refusing a scheme other than
#: ``http`` or ``https``.
_HTTP_URL: TypeAdapter[AnyHttpUrl] = TypeAdapter(AnyHttpUrl)

#: A parse refusal's reason by the parser's error type. Its message is not
#: reused: the error keeps the input it refused.
_PARSE_REFUSALS = {"url_scheme": f"{_NOT_AN_ORIGIN}: its scheme is http or https"}
_UNPARSED = f"{_NOT_AN_ORIGIN}: it is not a valid URL"


def _parsed(text: str) -> tuple[AnyHttpUrl | None, str]:
    """``text`` parsed as an HTTP(S) URL and ``""``, or ``None`` and the reason."""
    try:
        return _HTTP_URL.validate_python(text), ""
    except ValidationError as exc:
        return None, _PARSE_REFUSALS.get(exc.errors()[0]["type"], _UNPARSED)


def site_authority_url(value: Any) -> str:
    """A site authority's HTTP(S) origin, as the URL standard normalizes it,
    without a trailing ``/``.

    The URL is parsed by pydantic's ``AnyHttpUrl``, which follows the WHATWG URL
    standard: an ``http`` or ``https`` scheme, a host, and a port in range,
    surrounding whitespace dropped, the scheme and host lowercased, an
    international host written as punycode, a default port omitted. On top of
    the parse, the one local rule is that the URL is an origin: credentials, a
    query, a fragment (a bare ``?`` or ``#`` included), and a path other than
    ``/`` are refused, because a client joins its own routes to the origin, so a
    path would become a prefix of every route. The normalized origin is what a
    storefront hands its site client.

    One guard precedes the parse: an ASCII control character anywhere in the
    value is refused, because the standard would rewrite the URL rather than
    refuse it -- it drops a tab or newline inside it, so ``http://si<TAB>te``
    would bind to ``http://site``, and C0 controls at its ends.

    The parser decides syntax, not existence: a host the standard accepts but no
    resolver will (``-``, say) is accepted here and fails as unreachable at the
    first poll. Empty credentials (``http://@a``, ``http://:@a``) are dropped by
    the parser, so they are accepted as ``http://a``; nothing is lost.
    """

    if not isinstance(value, str):
        raise ValueError("must be a string")
    if _ASCII_CONTROL.search(value.strip()):
        raise ValueError(f"{_NOT_AN_ORIGIN} without control characters")
    url, reason = _parsed(value)
    if url is None:
        raise ValueError(reason)
    if url.username is not None or url.password is not None:
        raise ValueError(f"{_NOT_AN_ORIGIN} without credentials")
    if url.query is not None or url.fragment is not None:
        raise ValueError(f"{_NOT_AN_ORIGIN} without a query or fragment")
    if url.path not in (None, "", "/"):
        raise ValueError(f"{_NOT_AN_ORIGIN} without a path")
    return str(url).rstrip("/")


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
