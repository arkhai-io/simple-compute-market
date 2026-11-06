"""The Alkahest once-only payment adapter: evidence-gated delivery, no payments.

Phase authorization and billing start are ``OnceDeliveryPolicy``'s; these tests
hold the adapter to them over its own binding check and injected validator.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle.adapters import (
    PaymentAdapterTable,
    PaymentBinding,
    PaymentSelector,
    submit_payment,
)
from market_deal_lifecycle.delivery import (
    ActivatedDeliveryRef,
    DeliveryEvidence,
    DeliveryPhase,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import LifecycleCommand

from market_alkahest.payment_adapter import AlkahestOnceAdapter
from market_alkahest.settlement_config import ALKAHEST_MECHANISM_ID

NEGOTIATION = "neg-4c1e"
ESCROW = "0x" + "ab" * 32
ACTIVATION = ActivatedDeliveryRef(record_ref="reservation-1", activated_at=1_700_000_000)


def _evidence(**fields) -> DeliveryEvidence:
    return DeliveryEvidence(
        **{"negotiation_id": NEGOTIATION, "commitment_ref": ESCROW, **fields}
    )


def _adapter(valid: bool = True) -> tuple[AlkahestOnceAdapter, AsyncMock]:
    validator = AsyncMock(return_value=valid)
    return (
        AlkahestOnceAdapter(
            negotiation_id=NEGOTIATION,
            commitment_ref=ESCROW,
            validate_commitment=validator,
        ),
        validator,
    )


@pytest.mark.parametrize("phase", list(DeliveryPhase))
async def test_valid_commitment_evidence_allows_each_delivery_phase(phase):
    adapter, validator = _adapter(valid=True)
    evidence = _evidence()

    authorization = await adapter.authorize(phase, evidence)

    assert authorization.status == "allow"
    assert authorization.operation_id == f"{NEGOTIATION}:{phase.value}"
    assert authorization.evidence_refs == [ESCROW]
    validator.assert_awaited_once_with(evidence)


async def test_evidence_the_validator_refuses_refuses_delivery():
    adapter, _ = _adapter(valid=False)

    authorization = await adapter.authorize(DeliveryPhase.DISPATCH, _evidence())

    assert authorization.status == "refuse"


@pytest.mark.parametrize(
    "fields",
    [{"negotiation_id": "neg-other"}, {"commitment_ref": "0x" + "cd" * 32}],
    ids=["another deal", "another commitment"],
)
async def test_evidence_for_another_deal_or_commitment_is_refused_unvalidated(fields):
    adapter, validator = _adapter(valid=True)

    authorization = await adapter.authorize(DeliveryPhase.COMMIT, _evidence(**fields))

    assert authorization.status == "refuse"
    validator.assert_not_awaited()


async def test_billing_start_with_activation_evidence_is_a_no_op():
    adapter, _ = _adapter(valid=True)

    result = await adapter.start_billing(
        "neg-4c1e:start", _evidence(activated_delivery=ACTIVATION),
    )

    assert result.outcome.status == "accepted"
    assert result.no_op is True


async def test_billing_start_without_activation_evidence_is_refused():
    adapter, validator = _adapter(valid=True)

    result = await adapter.start_billing("neg-4c1e:start", _evidence())

    assert result.outcome.status == "rejected"
    assert result.no_op is False
    validator.assert_not_awaited()


async def test_billing_start_on_invalid_commitment_evidence_is_refused():
    adapter, _ = _adapter(valid=False)

    result = await adapter.start_billing(
        "neg-4c1e:start", _evidence(activated_delivery=ACTIVATION),
    )

    assert result.outcome.status == "rejected"


@pytest.mark.parametrize("kind", ["start", "stop", "reverse"])
async def test_every_payment_command_is_refused_before_any_operation_is_recorded(kind):
    adapter, _ = _adapter()
    selector = PaymentSelector(mechanism=ALKAHEST_MECHANISM_ID)
    table = PaymentAdapterTable([(selector, lambda binding: adapter)])
    store = AsyncMock()
    command = LifecycleCommand(
        negotiation_id=NEGOTIATION, kind=kind, operation_key="op-1",
    )
    binding = PaymentBinding(NEGOTIATION, selector)
    assert table.resolve(binding) is adapter

    outcome = await submit_payment(command, binding, table, store)

    assert outcome.status == "rejected"
    store.check_and_record.assert_not_awaited()
    assert adapter.validate(command).status == "rejected"
    direct = await adapter.submit(command, OperationKeys(NEGOTIATION, "op-1"))
    assert direct.status == "rejected"


async def test_the_authority_view_is_rejected_naming_the_mechanism():
    adapter, _ = _adapter()

    view = await adapter.read()

    assert view.outcome.status == "rejected"
    assert ALKAHEST_MECHANISM_ID in view.outcome.reason
    assert view.events == []
