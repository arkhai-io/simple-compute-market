"""The time value and the one rule that reads it.

An instant is an integer of Unix seconds from 0 to 253402300799, the last second
of the year 9999 and the latest instant a UTC `datetime` holds. A document
carrying one is exactly `{"now": <instant>}`. Integer seconds suit a signing
protocol whose timestamps are integers, which would truncate a finer instant on
every signed hop, and let two parties compare instants exactly.

Every reader of a time value — a setting request, a status, a time file — reads
it here, so no reader admits what another refuses.
"""

from __future__ import annotations

import json
from typing import Any

MIN_INSTANT = 0
MAX_INSTANT = 253402300799


class InvalidTime(ValueError):
    """A time value or document breaks the rule; `code` is `invalid_time`."""

    code = "invalid_time"


def check_instant(value: object) -> int:
    """`value` as an instant, or `InvalidTime`.

    A boolean is refused although Python counts it an integer, and so is a float
    with a whole value: the rule admits JSON integers alone.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidTime(f"an instant is an integer of Unix seconds, not {value!r}")
    if not MIN_INSTANT <= value <= MAX_INSTANT:
        raise InvalidTime(
            f"an instant is between {MIN_INSTANT} and {MAX_INSTANT}, not {value}")
    return value


def read_time(document: object) -> int:
    """The instant a parsed document carries, or `InvalidTime`."""
    if not isinstance(document, dict):
        raise InvalidTime(f'a time document is an object {{"now": <instant>}}, not {document!r}')
    if "now" not in document:
        raise InvalidTime('a time document carries "now"')
    others = sorted(str(key) for key in document if key != "now")
    if others:
        raise InvalidTime(f'a time document carries only "now", not {", ".join(others)}')
    return check_instant(document["now"])


def _refuse_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # The json module keeps the last of two equal keys, which would let
    # {"now": 1, "now": 2} read as one instant here and another elsewhere.
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise InvalidTime(f"a time document states {key!r} twice")
        document[key] = value
    return document


def parse_time(raw: str | bytes | bytearray) -> int:
    """The instant a JSON time document carries, or `InvalidTime`.

    Bytes are read as UTF-8 alone: the json module would otherwise detect UTF-16
    and UTF-32 too, and one reader would admit a body another refuses.
    """
    try:
        text = raw if isinstance(raw, str) else bytes(raw).decode("utf-8")
        document = json.loads(text, object_pairs_hook=_refuse_duplicate_members)
    except InvalidTime:
        raise
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidTime(f"a time document is JSON: {error}") from error
    return read_time(document)


def time_document(instant: int) -> dict[str, int]:
    """The document carrying `instant`, which `read_time` reads back."""
    return {"now": check_instant(instant)}
