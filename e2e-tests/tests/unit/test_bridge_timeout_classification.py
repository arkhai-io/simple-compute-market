"""A storefront that never answered has not rejected anything."""

from __future__ import annotations

from src.hosted_real_stripe.lifecycle_bridge import _caused_by_timeout


def test_direct_timeout_is_a_timeout() -> None:
    assert _caused_by_timeout(TimeoutError("timed out")) is True


def test_rewrapped_timeout_is_still_a_timeout() -> None:
    """The signed transport raises RuntimeError from the underlying deadline."""

    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError as cause:
            raise RuntimeError("POST /api/v1/settlements failed: timed out") from cause
    except RuntimeError as exc:
        assert _caused_by_timeout(exc) is True


def test_implicit_context_timeout_is_still_a_timeout() -> None:
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError:
            raise RuntimeError("wrapped without from")
    except RuntimeError as exc:
        assert _caused_by_timeout(exc) is True


def test_ordinary_failure_is_not_a_timeout() -> None:
    assert _caused_by_timeout(ValueError("contract violated")) is False


def test_cycle_does_not_hang() -> None:
    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first

    assert _caused_by_timeout(first) is False
