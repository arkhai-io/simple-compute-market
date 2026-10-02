"""The values the job authority and its executors exchange."""

from __future__ import annotations

import pytest

from compute_provisioning.hosts import (
    ConnectionCodecs,
    ConnectionEnvelope,
    ExecutionHost,
    ProtectedValue,
)
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


def test_a_connection_cannot_be_changed_through_the_envelope() -> None:
    source = {"address": "192.0.2.10"}
    envelope = ConnectionEnvelope(kind="ssh", version=1, public=source)
    source["address"] = "198.51.100.1"

    assert envelope.public["address"] == "192.0.2.10"
    with pytest.raises(TypeError):
        envelope.public["address"] = "203.0.113.1"  # type: ignore[index]


def test_a_protected_value_never_shows_its_ciphertext() -> None:
    value = ProtectedValue(scheme="fernet-v1", ciphertext="gAAAA-secret")
    envelope = ConnectionEnvelope(
        kind="ssh", version=1, public={}, protected={"private_key": value}
    )

    for rendering in (repr(value), str(value), repr(envelope), str(envelope)):
        assert "gAAAA-secret" not in rendering
    assert envelope.protected_schemes() == {"private_key": "fernet-v1"}
    assert ProtectedValue.from_stored(value.to_stored()) == value


def test_an_envelope_holds_only_protected_values_as_secrets() -> None:
    with pytest.raises(TypeError):
        ConnectionEnvelope(kind="ssh", version=1, protected={"private_key": "plain"})  # type: ignore[dict-item]


def test_codecs_refuse_an_unsupported_kind_or_version() -> None:
    class _Codec:
        kind, version = "ssh", 1

        def build(self, public, secrets, *, previous=None):
            return ConnectionEnvelope(kind="ssh", version=1, public=public)

        def validate(self, envelope):
            return envelope

    codecs = ConnectionCodecs([_Codec()])

    assert codecs.build("ssh", 1, {"a": 1}, {}).public["a"] == 1
    with pytest.raises(ValueError, match="not supported"):
        codecs.build("cloud_api", 1, {}, {})
    with pytest.raises(ValueError, match="version"):
        codecs.build("ssh", 2, {}, {})
    with pytest.raises(ValueError, match="duplicate"):
        ConnectionCodecs([_Codec(), _Codec()])


@pytest.mark.parametrize("kind,version", [("", 1), ("  ", 1), ("ssh", 0)])
def test_a_connection_needs_a_kind_and_a_positive_version(kind, version) -> None:
    with pytest.raises(ValueError):
        ConnectionEnvelope(kind=kind, version=version)


def test_an_execution_host_needs_an_identity() -> None:
    connection = ConnectionEnvelope(kind="ssh", version=1)

    assert ExecutionHost("kvm1", "default", connection).host_id == "kvm1"
    with pytest.raises(ValueError):
        ExecutionHost(" ", "default", connection)
