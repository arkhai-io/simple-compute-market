"""A control party's time: the status section and the time control over its source.

Each double and the sample app reads the time of the world from one source, the
time component's: wall time, or an injected instant that only the time control
moves. Under injected time due state is evaluated lazily at each read against
that instant, so setting it past a notice, a funding boundary or a hold's release
makes the outcome visible at the next read, with nothing running in the
background. The control answers and refuses as the time component's route
service does, its refusals carried as ``ControlError`` so every control route has
one refusal body.
"""

from __future__ import annotations

from injected_time import TimeRouteError, TimeRouteService, TimeSource

from lane_double_controls.models import ControlError, TimeView


class TimeControl:
    """The time section and, under injected time, the time control of ``source``."""

    def __init__(self, source: TimeSource) -> None:
        self.source = source
        self._routes = TimeRouteService(source)

    @property
    def settable(self) -> bool:
        """Whether the time route is served: the source is injected."""
        return self._routes.settable

    def view(self) -> TimeView:
        """``{"source": "injected", "now": …}``, or ``{"source": "wall"}``."""
        return TimeView.model_validate(self._routes.status())

    def set_time(self, body: bytes) -> TimeView:
        """Set the injected source to the instant the raw ``body`` carries, and answer it.

        Refuses ``422 invalid_time`` for a body that is not exactly
        ``{"now": <instant>}`` and ``409 time_moves_forward`` for an earlier
        instant, changing nothing. Served only where ``settable`` holds.
        """
        try:
            return TimeView.model_validate(self._routes.set_time(body))
        except TimeRouteError as error:
            raise ControlError(error.status_code, error.code, error.detail) from None


__all__ = ["TimeControl"]
