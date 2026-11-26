from __future__ import annotations

import pytest

from request_replay import Outcome, Policy, Resolution

from tests.support import ManualClock, MemoryStore, guard


@pytest.mark.parametrize("field", ["skew_seconds", "retention_seconds", "lease_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_every_bound_is_a_positive_integer(field: str, value: object) -> None:
    values: dict[str, object] = {"skew_seconds": 300, "retention_seconds": 86_400, "lease_seconds": 30}
    values[field] = value

    with pytest.raises(ValueError, match=field):
        Policy(**values)  # type: ignore[arg-type]


def test_a_rerun_bound_is_twice_the_skew_past_the_origin() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)

    assert policy.bound(Resolution.RERUN, 1_000) == 1_600


def test_a_recorded_bound_is_the_retention_and_a_skew_past_the_origin() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)

    assert policy.bound(Resolution.RECORDED, 1_000) == 1_000 + 86_400 + 300


def test_a_recorded_bound_is_never_shorter_than_a_replay_needs() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=60, lease_seconds=30)

    assert policy.bound(Resolution.RECORDED, 1_000) == 1_600


def test_the_expiry_is_the_later_of_the_bound_and_the_lease_end() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)

    assert policy.expires_at(Resolution.RERUN, 1_000, lease_until=1_030) == 1_600
    assert policy.expires_at(Resolution.RERUN, 1_000, lease_until=9_000) == 9_000


def test_a_first_use_needs_an_origin_within_the_skew() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)

    assert policy.admits_first_use(700, now=1_000)
    assert not policy.admits_first_use(699, now=1_000)


def test_the_retention_passes_once_the_origin_is_older_than_it() -> None:
    policy = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)

    assert not policy.retention_passed(1_000, now=1_000 + 86_400)
    assert policy.retention_passed(1_000, now=1_000 + 86_401)


@pytest.mark.parametrize("status", [99, 600, True])
def test_an_outcome_holds_an_http_status(status: object) -> None:
    with pytest.raises(ValueError):
        Outcome(status=status, headers=(), body=b"")  # type: ignore[arg-type]


def test_an_outcome_keeps_its_headers_in_order_through_json() -> None:
    outcome = Outcome(status=200, headers=(("b", "2"), ("a", "1"), ("b", "3")), body=b"")

    assert Outcome.headers_from_json(outcome.headers_json()) == outcome.headers


def test_a_sweep_batch_is_positive() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        guard(MemoryStore(), ManualClock()).sweep(batch_size=0)
