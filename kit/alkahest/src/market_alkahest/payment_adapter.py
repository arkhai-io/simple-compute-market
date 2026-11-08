"""Alkahest's once-only payment adapter for the delivery order.

Alkahest has no lifecycle adapter in the deal lifecycle's sense: its options carry
no lifecycle terms, and an escrow is released or reclaimed through its own
obligation servicing, never through a payment command. An Alkahest deal's delivery
is still authorized and its billing start still passes end service, so it follows
the same protected order as a hosted payment deal, and a missing adapter can never
be read as permission. This adapter is that explicit composition: it allows a
delivery phase only when the composition's validator accepts the selected stage's
commitment evidence, makes billing start a no-op that requires activation evidence
and starts nothing, supports no payment command, and reports its authority view
rejected, naming the mechanism.

See openspec/specs/deal-lifecycle/spec.md, "Delivery phases use a shared
evidence-gated protocol".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from market_deal_lifecycle.delivery import (
    BillingStartResult,
    DeliveryAuthorization,
    DeliveryEvidence,
    DeliveryPhase,
    OnceDeliveryPolicy,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import (
    AuthorityView,
    LifecycleCommand,
    LifecycleOutcome,
    Rejected,
)

from .settlement_config import ALKAHEST_MECHANISM_ID

#: Checks delivery evidence against the selected Alkahest stage's typed,
#: versioned commitment evidence, which the composition holds. A reference
#: being present is not proof; the validator decides.
CommitmentValidator = Callable[[DeliveryEvidence], Awaitable[bool]]

_NO_PAYMENT_COMMAND = f"{ALKAHEST_MECHANISM_ID} supports no payment command"


class AlkahestOnceAdapter:
    """One accepted Alkahest commitment, as the delivery order's payment adapter.

    ``commitment_ref`` is the reference the selected stage committed under; a
    delivery evidence bundle naming another deal or commitment is refused before
    the validator runs.
    """

    supported_commands: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        negotiation_id: str,
        commitment_ref: str,
        validate_commitment: CommitmentValidator,
    ) -> None:
        self.negotiation_id = negotiation_id
        self.commitment_ref = commitment_ref
        self._validate_commitment = validate_commitment
        self._delivery = OnceDeliveryPolicy(self._commitment_matches)

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        return Rejected(reason=_NO_PAYMENT_COMMAND)

    async def submit(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome:
        return Rejected(reason=_NO_PAYMENT_COMMAND)

    async def read(self) -> AuthorityView:
        return AuthorityView(
            outcome=Rejected(reason=f"{ALKAHEST_MECHANISM_ID} has no lifecycle adapter"),
        )

    async def authorize(
        self, phase: DeliveryPhase, evidence: DeliveryEvidence,
    ) -> DeliveryAuthorization:
        return await self._delivery.authorize(phase, evidence)

    async def start_billing(
        self, operation_key: str, evidence: DeliveryEvidence,
    ) -> BillingStartResult:
        return await self._delivery.start_billing(operation_key, evidence)

    async def _commitment_matches(self, evidence: DeliveryEvidence) -> bool:
        if (evidence.negotiation_id, evidence.commitment_ref) != (
            self.negotiation_id, self.commitment_ref,
        ):
            return False
        return await self._validate_commitment(evidence)
