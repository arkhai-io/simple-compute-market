"""The framework-free route service of a process's time controls.

A service exposes two things about its time: the status section, which it serves
whatever its source, and the setting route, which it mounts only when its source
is injected, so a wall-time instance offers no way to change its time. This class
validates and performs both and shapes their answers; the HTTP binding — the
path, the authentication in front of it, turning `TimeRouteError` into a
response — is each service's own.

A setting request's body is the time document, `{"now": <instant>}`, read by the
one rule (`injected_time.value`); the answer is
`{"source": "injected", "now": <instant>}`. A body the rule refuses is answered
422 `invalid_time` and an instant earlier than the current one 409
`time_moves_forward`, and neither changes anything.
"""

from __future__ import annotations

from typing import Any, cast

from injected_time.source import INJECTED, WALL, InjectedTime, TimeMovesForward, TimeSource
from injected_time.value import InvalidTime, parse_time

INVALID_TIME_STATUS = 422
TIME_MOVES_FORWARD_STATUS = 409


class TimeRouteError(Exception):
    """A refused setting request: the HTTP status, a stable code and a detail."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class TimeRouteService:
    """The status section of `source`, and the setting route of an injected one."""

    def __init__(self, source: TimeSource) -> None:
        self._source = source

    @property
    def settable(self) -> bool:
        """Whether the setting route is mounted: the source is injected and set here."""
        return isinstance(self._source, InjectedTime)

    def status(self) -> dict[str, Any]:
        """`{"source": "injected", "now": <instant>}`, or `{"source": "wall"}`."""
        if self._source.name == WALL:
            return {"source": WALL}
        return {"source": INJECTED, "now": self._source.now()}

    def set_time(self, body: str | bytes | bytearray) -> dict[str, Any]:
        """Set the injected source to the instant `body` carries, and answer it.

        Bound only where `settable` holds, as the setting route exists only on an
        injected instance.
        """
        source = cast(InjectedTime, self._source)
        try:
            instant = parse_time(body)
        except InvalidTime as error:
            raise TimeRouteError(INVALID_TIME_STATUS, InvalidTime.code, str(error)) from error
        try:
            source.set(instant)
        except TimeMovesForward as error:
            raise TimeRouteError(
                TIME_MOVES_FORWARD_STATUS, TimeMovesForward.code, str(error)) from error
        return {"source": INJECTED, "now": instant}
