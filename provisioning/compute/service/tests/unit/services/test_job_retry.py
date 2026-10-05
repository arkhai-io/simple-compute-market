"""The deployment's job retry policy, read from the service's settings."""

from __future__ import annotations

from types import SimpleNamespace

from compute_provisioning_service.services.job_retry import retry_policy_from


def _policy(**overrides):
    settings = SimpleNamespace(
        default_max_retries=3,
        retry_backoff_initial_seconds=60,
        retry_backoff_multiplier=2.0,
        retry_backoff_max_seconds=3600,
    )
    for name, value in overrides.items():
        setattr(settings, name, value)
    return retry_policy_from(settings)


def test_delays_grow_by_the_multiplier():
    policy = _policy(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
    assert [policy.delay_seconds(n) for n in range(3)] == [60, 120, 240]


def test_delays_are_capped_at_the_maximum():
    policy = _policy(retry_backoff_max_seconds=200)
    assert policy.delay_seconds(2) == 200


def test_the_default_retry_count_is_the_deployment_s():
    assert _policy(default_max_retries=5).default_max_retries == 5
