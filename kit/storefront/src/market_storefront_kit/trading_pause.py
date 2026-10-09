"""A storefront's trading pause: whether it opens new negotiations.

The pause is process-local: a restarted storefront trades again. It is used while
an operator corrects something, and a restart in the middle of that is noticed and
handled by the operator. It is separate from the loop controller's lifecycle pause,
which holds a storefront's timer loops and leaves trading open; pausing one leaves
the other alone. See openspec/specs/market-composition/spec.md, "The trading pause
is one process-local kit mechanism".

Each storefront binds :class:`TradingPauseRouteService` at its pause and resume
routes behind its own administrator authentication, so the paths and responses are
the same for every storefront and one typed client drives them all.
"""

from __future__ import annotations

from core_storefront.models.system_models import AdminPauseResponse


class TradingPause:
    """Whether this process refuses new negotiations."""

    def __init__(self) -> None:
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False


class TradingPauseRouteService:
    """Set and clear one storefront's trading pause."""

    def __init__(self, pause: TradingPause) -> None:
        self._pause = pause

    def pause(self) -> AdminPauseResponse:
        self._pause.pause()
        return AdminPauseResponse(
            paused=True, message="Storefront paused. New negotiations will receive 503."
        )

    def resume(self) -> AdminPauseResponse:
        self._pause.resume()
        return AdminPauseResponse(paused=False, message="Storefront resumed.")


__all__ = ["TradingPause", "TradingPauseRouteService"]
