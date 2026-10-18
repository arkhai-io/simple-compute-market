"""Setting types storefronts share: a usable duration and a site authority's origin.

Each rule is a plain function that returns the value as the storefront uses it
or raises ``ValueError`` with a reason naming no configured value, and a Pydantic
annotated type over that function. A typed settings model declares a field with
the type, and a loader reading untyped settings validates through a
``TypeAdapter`` of it. A caller reporting a refusal prefixes the reason with its
key.

A refusal is raised outside any ``except`` block, so it carries no exception
context either: a parsing error's message can quote the value it failed on.
"""

from __future__ import annotations

import ipaddress
import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import PlainValidator, WithJsonSchema

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

#: One DNS label: letters, digits, and hyphens, not starting or ending with one.
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _is_valid_host(netloc: str, hostname: str) -> bool:
    """A DNS name, an IPv4 address, or a bracketed IPv6 literal."""
    if netloc.startswith("["):
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return False
        return True
    try:
        ipaddress.IPv4Address(hostname)
    except ValueError:
        pass
    else:
        return True
    return len(hostname) <= 253 and all(
        _DNS_LABEL.fullmatch(label) for label in hostname.split(".")
    )


_NOT_AN_ORIGIN = "must be an HTTP(S) origin"


def _origin(text: str) -> tuple[str | None, str]:
    """``text``'s origin and ``""``, or ``None`` and why it is not one."""
    if any(char.isspace() or unicodedata.category(char).startswith("C") for char in text):
        # urlsplit drops tabs and newlines silently, so they are refused first.
        return None, f"{_NOT_AN_ORIGIN} without whitespace or control characters"
    try:
        parsed = urlsplit(text)
    except ValueError:
        parsed = None
    if parsed is None:
        return None, _NOT_AN_ORIGIN
    if parsed.scheme not in {"http", "https"}:
        return None, f"{_NOT_AN_ORIGIN}: its scheme is http or https"
    if parsed.username is not None or parsed.password is not None:
        return None, f"{_NOT_AN_ORIGIN} without credentials"
    if parsed.query or parsed.fragment or "?" in text or "#" in text:
        return None, f"{_NOT_AN_ORIGIN} without a query or fragment"
    if parsed.path not in {"", "/"}:
        return None, f"{_NOT_AN_ORIGIN} without a path"
    hostname = parsed.hostname
    if not hostname or not _is_valid_host(parsed.netloc, hostname):
        return None, (
            f"{_NOT_AN_ORIGIN} naming a host: a DNS name or an IP address, an IPv6 "
            "address bracketed"
        )
    try:
        port = parsed.port
    except ValueError:
        port = 0
    if port == 0 or parsed.netloc.endswith(":"):
        return None, f"{_NOT_AN_ORIGIN} with a port, if stated, from 1 to 65535"
    return f"{parsed.scheme}://{parsed.netloc}", ""


def site_authority_url(value: Any) -> str:
    """A site authority's HTTP(S) origin, as ``<scheme>://<host>[:<port>]``.

    The origin is all a site's URL may state: an ``http`` or ``https`` scheme
    (read in any case), a host that is a DNS name or an IP address, and
    optionally a port from 1 to 65535. Credentials, a query, a fragment, a path
    other than ``/``, and whitespace or control characters inside the value are
    refused, because a client joins its own routes to the origin, so a path
    would become a prefix of every route. Surrounding whitespace and a trailing
    ``/`` are dropped.
    """

    if not isinstance(value, str):
        raise ValueError("must be a string")
    origin, reason = _origin(value.strip())
    if origin is None:
        raise ValueError(reason)
    return origin


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
