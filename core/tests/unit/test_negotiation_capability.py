"""The optional negotiation capability on the market-domain contract.

The capability declares one thing: this domain offers policies a role's
configuration may name. A domain that composes its middlewares as values and
exposes no names does not declare it, and must not be required to supply a
placeholder to stay composable.
"""

from __future__ import annotations

import pytest
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainContractValidationError,
    DomainIdentity,
    ImmutableNegotiationCapability,
    MarketDomainContract,
    NegotiationCapability,
    validate_domain_contract,
)


class _Codecs:
    """Minimal codec set; this module tests the negotiation capability only."""

    @staticmethod
    def _identity(value):
        return value

    listing = message = terms = materialization = receipt = result = _identity


def _contract(**overrides) -> MarketDomainContract:
    base = {
        "identity": DomainIdentity("widgets"),
        "contract_version": MARKET_DOMAIN_CONTRACT_VERSION,
        "codecs": _Codecs(),
    }
    base.update(overrides)
    return MarketDomainContract(**base)


def test_immutable_capability_satisfies_the_protocol() -> None:
    capability = ImmutableNegotiationCapability(policy_sources=lambda: ())

    assert isinstance(capability, NegotiationCapability)


def test_a_declared_capability_is_reachable_by_enum() -> None:
    capability = ImmutableNegotiationCapability(policy_sources=lambda: ("source",))
    contract = _contract(
        declared_capabilities=frozenset({DomainCapability.NEGOTIATION}),
        negotiation=capability,
    )

    assert contract.has_capability(DomainCapability.NEGOTIATION)
    assert contract.capability(DomainCapability.NEGOTIATION) is capability
    assert validate_domain_contract(contract) is not None


def test_declaring_the_capability_without_the_hook_fails_validation() -> None:
    class _MissingHook:
        pass

    contract = _contract(
        declared_capabilities=frozenset({DomainCapability.NEGOTIATION}),
        negotiation=_MissingHook(),
    )

    with pytest.raises(DomainContractValidationError) as caught:
        validate_domain_contract(contract)

    message = str(caught.value)
    assert "widgets" in message
    assert "policy_sources" in message


def test_declaring_the_capability_without_supplying_it_fails_validation() -> None:
    contract = _contract(
        declared_capabilities=frozenset({DomainCapability.NEGOTIATION}),
    )

    with pytest.raises(DomainContractValidationError):
        validate_domain_contract(contract)


def test_a_domain_may_omit_the_capability_entirely() -> None:
    """A domain composing its chain directly needs no placeholder hook."""
    contract = _contract()

    assert not contract.has_capability(DomainCapability.NEGOTIATION)
    assert contract.capability(DomainCapability.NEGOTIATION) is None
    assert validate_domain_contract(contract) is not None
