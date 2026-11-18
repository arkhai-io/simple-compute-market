"""The seller's dispute policy: what it reads of each registry, and again.

The registries are a double of the cross-registry client the policy's factory
builds, recording each selection it is asked to read; each registry answers a
descriptor carrying its recommended dispute authorities, or nothing, as a
registry whose read failed does. The policy's clock is injected, so each
failure is recorded at an instant the test chose.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from market_deal_lifecycle.configuration import NO_DISPUTE_AUTHORITIES, dispute_config

from market_storefront_kit.dispute_configuration import (
    DISPUTE_AUTHORITIES_UNREAD,
    RegistryDisputePolicy,
    UnreadRegistry,
)

_A = "https://registry-a.example"
_B = "https://registry-b.example"
_START = datetime(2026, 1, 1, tzinfo=UTC)


def _authority(account: str) -> dict:
    """A recommended authority, in reserved example data."""
    return {
        "interface": "example.dispute.v1",
        "origin": "https://dispute.example",
        "account": account,
        "record_key": "example-public-record-key",
        "params": {},
        "advertisement": {
            "mechanisms": ["example.payment.v1"],
            "minimum_dispute_window_seconds": 60,
            "minimum_case_hold_seconds": 3600,
        },
    }


class _Registries:
    """The registries behind the client: each URL's account, and which fail.

    Every client it builds records the selection each read named in
    ``selections``, and ``built`` counts the clients built.
    """

    def __init__(self, accounts: dict[str, str], *, failing: set[str] = frozenset()):
        self.accounts = accounts
        self.failing = set(failing)
        self.selections: list[list[str]] = []
        self.built = 0

    def factory(self) -> _Client:
        self.built += 1
        return _Client(self)


class _Client:
    def __init__(self, registries: _Registries):
        self._registries = registries
        self.urls = list(registries.accounts)

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def get_descriptors(self, registries=None):
        selected = self.urls if registries is None else [u for u in self.urls if u in registries]
        self._registries.selections.append(selected)
        return {
            url: None if url in self._registries.failing else SimpleNamespace(
                recommended_dispute_authorities=[_authority(self._registries.accounts[url])]
            )
            for url in selected
        }


class _Clock:
    def __init__(self) -> None:
        self.instant = _START

    def __call__(self) -> datetime:
        return self.instant


def _policy(clock: _Clock, document: dict | None = None) -> RegistryDisputePolicy:
    # A seller uses its registries' recommendations unless it opts out.
    return RegistryDisputePolicy(dispute_config(document or {}, role="seller"), clock=clock)


def _accounts(policy: RegistryDisputePolicy, url: str) -> list[str]:
    return [entry.account for entry in policy.authorities[url]]


@pytest.mark.asyncio
async def test_a_reread_reads_only_the_failed_registry_and_keeps_the_other():
    clock = _Clock()
    registries = _Registries({_A: "account-a", _B: "account-b"}, failing={_B})
    policy = _policy(clock)

    await policy.refresh(registries.factory)

    assert _accounts(policy, _A) == ["account-a"]
    assert _accounts(policy, _B) == []
    assert policy.unread_registries() == (UnreadRegistry(_B, _START),)

    registries.failing.clear()
    clock.instant = _START + timedelta(minutes=5)
    await policy.reread(registries.factory)

    assert registries.selections == [[_A, _B], [_B]]
    assert _accounts(policy, _A) == ["account-a"]
    assert _accounts(policy, _B) == ["account-b"]
    assert policy.unread_registries() == ()
    assert policy.readiness_resources() == {}


@pytest.mark.asyncio
async def test_a_reread_after_every_read_succeeded_reads_nothing():
    registries = _Registries({_A: "account-a", _B: "account-b"})
    policy = _policy(_Clock())
    await policy.refresh(registries.factory)

    await policy.reread(registries.factory)

    assert registries.built == 1
    assert registries.selections == [[_A, _B]]
    assert _accounts(policy, _A) == ["account-a"]


@pytest.mark.asyncio
async def test_an_unread_registry_is_reported_with_its_last_failure_until_read(caplog):
    clock = _Clock()
    registries = _Registries({_A: "account-a", _B: "account-b"}, failing={_B})
    policy = _policy(clock)
    await policy.refresh(registries.factory)

    later = _START + timedelta(minutes=10)
    clock.instant = later
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await policy.reread(registries.factory)

    assert policy.unread_registries() == (UnreadRegistry(_B, later),)
    assert policy.readiness_resources() == {
        DISPUTE_AUTHORITIES_UNREAD: [
            {"registry": _B, "last_failed_at": "2026-01-01T00:10:00+00:00"}
        ]
    }
    assert _accounts(policy, _A) == ["account-a"]
    # A read that failed again changes nothing, so it repeats no warning that
    # the registry offers no authority.
    assert not [r for r in caplog.records if NO_DISPUTE_AUTHORITIES in r.getMessage()]

    registries.failing.clear()
    await policy.reread(registries.factory)

    assert policy.unread_registries() == ()
    assert policy.readiness_resources() == {}


@pytest.mark.asyncio
async def test_a_client_that_cannot_be_opened_leaves_every_registry_unread():
    class _Unopenable(_Client):
        async def __aenter__(self) -> _Client:
            raise OSError("connection refused")

    registries = _Registries({_A: "account-a", _B: "account-b"})
    policy = _policy(_Clock())

    await policy.refresh(lambda: _Unopenable(registries))

    assert policy.unread_registries() == (UnreadRegistry(_A, _START), UnreadRegistry(_B, _START))
    assert _accounts(policy, _A) == [] and _accounts(policy, _B) == []


@pytest.mark.asyncio
async def test_a_seller_not_using_recommendations_reads_and_reports_nothing():
    registries = _Registries({_A: "account-a"}, failing={_A})
    policy = _policy(_Clock(), {"use_registry_dispute_authorities": False})

    await policy.refresh(registries.factory)
    await policy.reread(registries.factory)

    assert registries.selections == []
    assert policy.unread_registries() == ()
    assert policy.readiness_resources() == {}
