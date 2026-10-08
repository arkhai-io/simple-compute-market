"""Convergence's retry backoff: pure arithmetic over an injectable random source."""

from __future__ import annotations

from compute_provisioning_service.services.fulfillment_convergence import Backoff


def test_backoff_random_source_is_injectable_for_deterministic_tests():
    """``Backoff.random_source`` gives reproducible delay sequences without
    patching global randomness."""

    from random import Random

    backoff_a = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(42),
    )
    backoff_a_repeat = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(42),
    )
    backoff_b = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(1337),
    )

    sequence_a = [backoff_a.delay_seconds(n) for n in range(1, 6)]
    sequence_a_repeat = [backoff_a_repeat.delay_seconds(n) for n in range(1, 6)]
    sequence_b = [backoff_b.delay_seconds(n) for n in range(1, 6)]

    # Same seed -> identical sequence.
    assert sequence_a == sequence_a_repeat
    # Different seed -> a different sequence (jitter is actually applied).
    assert sequence_a != sequence_b
    # No jitter still follows the base exponential formula exactly.
    no_jitter = Backoff(initial_seconds=1.0, multiplier=2.0, max_seconds=60.0)
    assert [no_jitter.delay_seconds(n) for n in range(1, 5)] == [1.0, 2.0, 4.0, 8.0]
