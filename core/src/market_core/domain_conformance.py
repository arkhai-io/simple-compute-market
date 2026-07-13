"""Reusable black-box conformance checks for market-domain implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .domain_contract import (
    DomainCapability,
    MarketDomainContract,
    validate_domain_contract,
)


@dataclass(frozen=True)
class DomainCodecExample:
    """One input and the expected normalized value for a domain codec."""

    input: Any
    expected: Any


@dataclass(frozen=True)
class DomainConformanceCase:
    """Examples and advertised capabilities for one external domain."""

    contract: MarketDomainContract
    listing: DomainCodecExample
    message: DomainCodecExample
    terms: DomainCodecExample
    materialization: DomainCodecExample
    receipt: DomainCodecExample
    result: DomainCodecExample
    capabilities: frozenset[DomainCapability]


def assert_domain_conformance(case: DomainConformanceCase) -> None:
    """Exercise the stable contract without assuming a repository layout."""

    contract = validate_domain_contract(case.contract)
    if contract.declared_capabilities != case.capabilities:
        raise AssertionError(
            f"{contract.identity}: declared capabilities "
            f"{contract.declared_capabilities!r} != expected {case.capabilities!r}"
        )

    examples = (
        ("listing", case.listing),
        ("message", case.message),
        ("terms", case.terms),
        ("materialization", case.materialization),
        ("receipt", case.receipt),
        ("result", case.result),
    )
    for codec_name, example in examples:
        normalized = getattr(contract.codecs, codec_name)(example.input)
        if normalized != example.expected:
            raise AssertionError(
                f"{contract.identity}: {codec_name} codec returned "
                f"{normalized!r}, expected {example.expected!r}"
            )

    for capability in DomainCapability:
        present = contract.capability(capability) is not None
        if present != (capability in case.capabilities):
            raise AssertionError(
                f"{contract.identity}: capability {capability.value!r} "
                f"presence does not match its declaration"
            )
