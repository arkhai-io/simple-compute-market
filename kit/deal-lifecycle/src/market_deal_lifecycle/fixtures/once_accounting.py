"""Contract fixtures for the optional private TEST once-accounting read.

The neutral port owns this shape. Concrete adapter tests validate real reads;
servicing tests build their inputs here without importing a payment mechanism.
These assertions establish a test contract, never signature or return authority.
"""

from __future__ import annotations

import re
from typing import Literal

from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, PaymentEvent, PaymentPartObservation,
)
from pydantic import JsonValue

from ..adapters import OnceAccountingProjection, OnceAccountingRead


def build_once_accounting_read(
    *,
    negotiation_id: str = "deal",
    commitment_ref: str = "commitment",
    seller_account: str = "seller-account",
    minimum_sequence: int = 0,
    latest_event_sequence: int = 1,
    provider_observed_at: int = 150,
    verified_signature_sha256: str = "a" * 64,
    financial_facts_sha256: str = "b" * 64,
    part_count: int = 1,
    livemode: Literal[False] = False,
    all_parts_terminal: bool = True,
    accounting: dict[str, JsonValue] | None = None,
    view: AuthorityView | None = None,
) -> OnceAccountingRead:
    """A minimal complete read; overrides can express consumer refusal cases."""
    if view is None:
        stop = PaymentEvent(
            negotiation_id=negotiation_id, commitment_ref=commitment_ref, part="0", kind="stop",
            actor="fixture-payer", at=140, cause="payer", sequence=latest_event_sequence,
            authority_record_ref="fixture-stop", settles_through="started_period",
        )
        view = AuthorityView(outcome=Accepted(), state="ended", events=[stop], parts=[
            PaymentPartObservation(part="0", started_at=100, final_stop=stop,
                                   evidence_ref="fixture-payment-observation"),
        ])
    return OnceAccountingRead(view, OnceAccountingProjection(
        negotiation_id=negotiation_id, commitment_ref=commitment_ref, seller_account=seller_account,
        minimum_sequence=minimum_sequence, latest_event_sequence=latest_event_sequence,
        provider_observed_at=provider_observed_at, verified_signature_sha256=verified_signature_sha256,
        financial_facts_sha256=financial_facts_sha256, part_count=part_count,
        livemode=livemode, all_parts_terminal=all_parts_terminal,
        accounting=dict(accounting) if accounting is not None else {
            "classification": "ACCOUNTING_TERMINAL", "returnAdmitted": False,
        },
    ))


def validate_once_accounting_read(
    read: OnceAccountingRead, *, negotiation_id: str, commitment_ref: str,
    seller_account: str, minimum_sequence: int,
) -> None:
    """Assert the present projection satisfies servicing's capture contract.

    An absent optional projection or a read below its requested floor cannot
    provide a capture. Producer tests assert those refusals separately.
    """
    assert type(read) is OnceAccountingRead
    assert isinstance(read.view, AuthorityView) and isinstance(read.view.outcome, Accepted)
    projection = read.projection
    assert type(projection) is OnceAccountingProjection
    assert projection.negotiation_id == negotiation_id
    assert projection.commitment_ref == commitment_ref
    assert projection.seller_account == seller_account
    assert type(projection.minimum_sequence) is int and projection.minimum_sequence >= minimum_sequence >= 0
    assert type(projection.latest_event_sequence) is int
    assert projection.minimum_sequence <= projection.latest_event_sequence <= 128
    assert type(projection.provider_observed_at) is int and projection.provider_observed_at >= 0
    assert type(projection.part_count) is int and 1 <= projection.part_count <= 32
    assert projection.livemode is False
    assert type(projection.all_parts_terminal) is bool
    for digest in (projection.verified_signature_sha256, projection.financial_facts_sha256):
        assert type(digest) is str and re.fullmatch(r"[a-f0-9]{64}", digest)
    assert isinstance(projection.accounting, dict)
    assert projection.accounting.get("returnAdmitted") is False
    assert projection.accounting.get("classification") in {"UNKNOWN", "ACCOUNTING_TERMINAL"}
    if projection.accounting["classification"] == "ACCOUNTING_TERMINAL":
        assert projection.all_parts_terminal is True
    for event in read.view.events:
        assert event.negotiation_id == negotiation_id and event.commitment_ref == commitment_ref
        assert 0 <= event.sequence <= projection.latest_event_sequence
