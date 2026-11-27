"""The storefront's capacity sites as configured, and the one runtime over them."""

from __future__ import annotations

import pytest
from market_identity import Ed25519Signer

from arkhai_api_selling.capacity import QuotaCapacity, read_capacity_sites

# Deterministic development keys for these tests only; never used on any network.
AUTHORITY = Ed25519Signer(bytes(range(4, 36))).identity
SELLER = Ed25519Signer(bytes(range(5, 37)))

SITES = {
    "quota": {
        "url": "http://quota.invalid:8082/",
        "expected_authorities": {"identities": [AUTHORITY.model_dump(mode="json")]},
    }
}


def test_configured_sites_are_read_with_their_trusted_authorities():
    sites, placement = read_capacity_sites(SITES, None, sites_key="quota.sites")

    assert placement == "fill_first"
    assert sites["quota"].url == "http://quota.invalid:8082"
    assert sites["quota"].expected_authorities.identities == (AUTHORITY,)


@pytest.mark.parametrize(
    ("sites", "refusal"),
    [
        (None, r"\[quota.sites\] must define"),
        ({"quota": {"url": "http://quota.invalid"}}, "capacity site 'quota' is incomplete"),
        (
            {"quota": {"url": "http://quota.invalid", "expected_authorities": {"identities": ["x"]}}},
            r"\[quota.sites.quota.expected_authorities\] must list",
        ),
    ],
)
def test_an_unreadable_site_is_refused_by_its_key(sites, refusal):
    with pytest.raises(RuntimeError, match=refusal):
        read_capacity_sites(sites, "fill_first", sites_key="quota.sites")


class _Store:
    def __init__(self, path: str) -> None:
        self.db_path = path


def _capacity(signer=SELLER, placement="fill_first") -> QuotaCapacity:
    return QuotaCapacity(
        sites=lambda: read_capacity_sites(SITES, placement, sites_key="quota.sites"),
        signer=lambda: signer,
        reconciler=lambda _factory: None,
    )


def test_one_runtime_serves_every_caller_until_its_database_changes():
    capacity = _capacity()
    first = capacity.runtime(lambda: _Store("a.db"))

    assert capacity.runtime(lambda: _Store("a.db")) is first
    assert capacity.runtime(lambda: _Store("b.db")) is not first
    assert capacity.configured_site_ids() == ("quota",)


def test_no_runtime_is_built_without_a_signer_or_with_an_unknown_placement():
    with pytest.raises(RuntimeError, match="signer"):
        _capacity(signer=None).runtime(lambda: _Store("a.db"))
    with pytest.raises(RuntimeError, match="placement policy 'nearest'"):
        _capacity(placement="nearest").runtime(lambda: _Store("a.db"))
