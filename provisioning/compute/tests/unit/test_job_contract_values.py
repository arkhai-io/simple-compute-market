"""The values the job authority and its executors exchange."""

from __future__ import annotations

import pytest

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobRetryPolicy


def test_retry_delay_grows_by_the_multiplier_and_stops_at_the_cap() -> None:
    policy = JobRetryPolicy(
        backoff_initial_seconds=60, backoff_multiplier=2.0, backoff_max_seconds=200
    )

    assert [policy.delay_seconds(n) for n in range(4)] == [60, 120, 200, 200]


@pytest.mark.parametrize(
    "values",
    [
        {"default_max_retries": -1},
        {"backoff_initial_seconds": -1},
        {"backoff_max_seconds": -1},
        {"backoff_multiplier": 0.5},
    ],
)
def test_a_retry_policy_refuses_an_impossible_value(values) -> None:
    with pytest.raises(ValueError):
        JobRetryPolicy(**values)


def test_a_connection_payload_cannot_be_changed_through_the_envelope() -> None:
    source = {"address": "192.0.2.10"}
    envelope = ConnectionEnvelope(kind="ssh", version=1, payload=source)
    source["address"] = "198.51.100.1"

    assert envelope.payload["address"] == "192.0.2.10"
    with pytest.raises(TypeError):
        envelope.payload["address"] = "203.0.113.1"  # type: ignore[index]


@pytest.mark.parametrize("kind,version", [("", 1), ("  ", 1), ("ssh", 0)])
def test_a_connection_needs_a_kind_and_a_positive_version(kind, version) -> None:
    with pytest.raises(ValueError):
        ConnectionEnvelope(kind=kind, version=version)


def test_an_execution_host_needs_an_identity() -> None:
    connection = ConnectionEnvelope(kind="ssh", version=1)

    assert ExecutionHost("kvm1", "default", connection).host_id == "kvm1"
    with pytest.raises(ValueError):
        ExecutionHost(" ", "default", connection)
