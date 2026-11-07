"""The process-local trading pause and the route service every storefront binds."""

from __future__ import annotations

from market_storefront_kit import TradingPause, TradingPauseRouteService


def test_a_new_process_is_trading() -> None:
    assert TradingPause().paused is False


def test_pause_and_resume_set_and_clear_it() -> None:
    pause = TradingPause()
    routes = TradingPauseRouteService(pause)

    paused = routes.pause()
    assert (paused.paused, pause.paused) == (True, True)

    resumed = routes.resume()
    assert (resumed.paused, pause.paused) == (False, False)


def test_each_pause_is_its_own() -> None:
    first, second = TradingPause(), TradingPause()
    first.pause()
    assert second.paused is False
