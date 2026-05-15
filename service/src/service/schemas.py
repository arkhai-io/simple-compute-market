"""Domain-agnostic shared schemas.

These models are intentionally minimal and stable. Both the policy
engine (market-policy) and the storefront/buyer runtimes import from
here, so any change is a cross-package break.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

UTC = timezone.utc

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from service.clients.token import ERC20TokenMetadata  # noqa: F401


class ActionType(str, Enum):
    """The full vocabulary of actions the policy engine can emit.

    Lives here (next to DomainAction / DecisionContext) rather than in
    the engine package because both the engine and the runtimes that
    execute actions need to agree on the values.
    """

    # Market entry
    RESPOND_TO_ORDER = "respond_to_order"
    IGNORE_ORDER = "ignore_order"
    MAKE_OFFER = "make_offer"

    # Negotiation
    ACCEPT_OFFER = "accept_offer"
    REJECT_OFFER = "reject_offer"
    COUNTER_OFFER = "counter_offer"
    EXIT_NEGOTIATION = "exit_negotiation"
    CLOSE_ORDER = "close_order"

    # Resource management
    RESOLVE_INTERNALLY = "resolve_internally"
    OUTSOURCE = "outsource"

    # No-op
    NOOP = "noop"


class Resource(BaseModel):
    """Domain-agnostic base resource model."""

    @classmethod
    def parse_from_dict(cls, data: Any) -> "Resource":
        """Parse core-known resource shapes.

        Core only understands universally valid resources. Domain-specific
        resources should be parsed by domain adapters that extend this method.
        """
        if isinstance(data, Resource):
            return data
        if not isinstance(data, dict):
            return data
        if "token" in data:
            return TokenResource(**data)
        raise ValueError("Unsupported resource payload for core Resource parser")


class TokenResource(Resource):
    """Describes a given value and amount of a token used for trade/payment.

    ``amount`` is tristate:
      * positive integer — the public price (the seller advertises this
        floor and uses it as the negotiation anchor).
      * ``0`` — free / public-test offering (the seller advertises zero
        cost; strategy accepts any non-negative offer).
      * ``None`` — hidden reserve (the seller publishes the listing without
        advertising a price; the negotiation strategy falls back to
        ``[seller.pricing].default_min_price`` for the floor; buyer must
        propose ``--initial-price`` and ``--max-price`` explicitly).
    """

    token: SerializeAsAny[ERC20TokenMetadata] = Field(
        description="Token metadata resolved from registry"
    )
    amount: int | None = Field(
        default=None,
        description=(
            "Integer amount in base units (token amount * 10**decimals). "
            "0 = free; null = hidden reserve (negotiate); >0 = public price."
        ),
    )


class ProvisionTerms(BaseModel):
    """What the seller commits to provision off-chain.

    Distinct from on-chain escrow terms (payment + arbiter): those gate
    payment release; these describe the actual resource the seller
    delivers. The two are independent — an escrow's arbiter may enforce
    none, some, or all of the provision fields depending on its design
    (a ``RecipientArbiter`` enforces none; a ``TrustedOracleArbiter``
    could attest delivery against a hash of these terms).

    Materialized at negotiation agreement and read by the seller's
    settlement / provisioning pipeline as the single source of truth
    for what to deliver. The compute_resource field is opaque at this
    layer (carried as a dict) because the typed marketplace model
    (``ComputeResource``) lives in the storefront package; the seller
    parses it back into typed form when needed.
    """

    duration_seconds: int = Field(
        gt=0,
        description=(
            "Buyer's lease window. The seller commits to provisioning "
            "for at least this long once escrow is verified on-chain."
        ),
    )
    ssh_public_key: str = Field(
        description=(
            "Public key to inject into the provisioned VM/container "
            "for buyer access. Empty string allowed for non-VM modes."
        ),
    )
    compute_resource: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Snapshot of the listing's offer_resource at agreement "
            "time. None on the buyer's side before a specific match "
            "is selected; populated by the seller (or buyer post-match) "
            "and persisted on the negotiation thread."
        ),
    )


class EscrowTerms(BaseModel):
    """One on-chain escrow obligation in flat, self-describing form.

    Mirrors the call shape of any alkahest escrow contract's
    ``doObligation(data, expirationTime)`` entry point. The
    ``obligation_data`` dict is literally the ``ObligationData`` struct
    for whichever contract ``escrow_contract`` points to — different
    contracts have different shapes, but every one begins with
    ``(address arbiter, bytes demand, …)`` followed by payment fields
    specific to that contract (token+amount for ERC20, tokenId for
    ERC721, native amount, bundle arrays, attestation refs, etc.).

    Readers extract universal fields by key: ``obligation_data["arbiter"]``
    and ``obligation_data["demand"]`` are present on every escrow kind.
    The rest is contract-specific; consumers that need typed access
    parse the dict against whichever ``ObligationData`` shape goes with
    ``escrow_contract``.

    Stored flat (not wrapped in a kind+params discriminator) so that:
      * settlement verification is a byte-compare against the chain-read
        obligation, with no codec dispatch needed on the read path.
      * adding new escrow kinds (ERC721, native, bundle, attestation)
        does not change this type — only the keys present in
        ``obligation_data`` differ.

    A negotiation outcome carries ``list[EscrowTerms]`` so multi-escrow
    designs (e.g. payment + seller penalty deposit) are expressible
    without a separate plan wrapper. ``maker`` distinguishes who calls
    ``doObligation`` for each entry.
    """

    maker: Literal["buyer", "seller"] = Field(
        description=(
            "Which side calls ``doObligation`` for this escrow. ``buyer`` "
            "for the standard payment escrow; ``seller`` for cases like "
            "penalty deposits the seller posts as bond."
        ),
    )
    escrow_contract: str = Field(
        description=(
            "Address of the on-chain escrow obligation contract — e.g. "
            "ERC20EscrowObligation, ERC721EscrowObligation, "
            "NativeTokenEscrowObligation, TokenBundleEscrowObligation, "
            "AttestationEscrowObligation. The address determines the "
            "expected shape of ``obligation_data``."
        ),
    )
    obligation_data: dict[str, Any] = Field(
        description=(
            "The literal ``ObligationData`` struct passed to "
            "``escrow_contract.doObligation``. Always contains at least "
            "``arbiter`` (address) and ``demand`` (bytes, hex-encoded for "
            "transport); the remaining keys are payment fields specific "
            "to the escrow kind."
        ),
    )
    expiration_unix: int = Field(
        gt=0,
        description=(
            "Absolute UTC unix-time at which the escrow expires on-chain. "
            "Buyer commits to creating the escrow before this moment; "
            "seller verifies the on-chain attestation's ``expirationTime`` "
            "equals this value. Absolute (not relative-to-creation) so "
            "both sides have a single agreed timestamp with no clock-drift "
            "tolerance window."
        ),
    )


class AcceptedEscrow(BaseModel):
    """One escrow shape the seller will accept for this listing.

    Each entry pins the (chain, escrow contract) tuple plus a partial
    EscrowData advertisement. The buyer's proposal must reference one
    of the listing's accepted entries by (chain_name, escrow_address)
    and supply the buyer-committable EscrowData keys in ``fields``.

    ``fields`` is shape-only: keys present advertise a seller-preferred
    value; keys absent are open. Whether a set field is a hard constraint
    or a negotiable default is the seller's negotiation policy's concern,
    not protocol infrastructure.

    ``amount`` is intentionally never present in ``fields`` — the
    on-chain ObligationData.amount is a per-deal total derived at
    settlement from ``price_per_hour * duration_seconds / 3600``. The
    advertised per-hour rate lives in the sibling ``price_per_hour``
    field so ``fields`` stays a pure Partial<ObligationData>.
    """

    chain_name: str = Field(
        description=(
            "Alkahest chain identifier (e.g. ``base_sepolia``, ``anvil``). "
            "Combined with ``escrow_address`` to look up the SDK codec via "
            "``service.clients.alkahest.address_to_slot``."
        ),
    )
    escrow_address: str = Field(
        description=(
            "Deployed escrow obligation contract address on ``chain_name``. "
            "The (chain, address) pair determines the EscrowData ABI."
        ),
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Partial EscrowData advertised by the seller. Keys present = "
            "seller-preferred values; keys absent = open. Never includes "
            "``amount`` (derived at settlement from ``price_per_hour`` × "
            "duration / 3600)."
        ),
    )
    price_per_hour: float | None = Field(
        default=None,
        description=(
            "Advertised per-hour rate in the escrow's payment token, in "
            "base units (token-amount × 10^decimals). Float so the rate "
            "stays precise when duration is sub-hour and the integer-base-"
            "unit amount comes from ``int(price_per_hour × duration_seconds "
            "/ 3600)``. ``None`` = hidden reserve (seller did not publish a "
            "rate; negotiation must establish one via the strategy's "
            "``default_min_price``). Drives the total amount that gets "
            "populated into ObligationData.amount at settlement."
        ),
    )


class EscrowProposal(BaseModel):
    """Buyer's escrow proposal at negotiation round 0.

    References one of the listing's ``accepted_escrows`` entries by
    ``(chain_name, escrow_address)`` and supplies the buyer-committable
    EscrowData fields. ``amount`` is intentionally not on the proposal —
    it's derived at settlement from the agreed price + duration. The
    seller echoes back the accepted proposal verbatim on the negotiation
    outcome so settlement code reconstructs the same on-chain
    obligation_data on both sides.
    """

    chain_name: str = Field(
        description=(
            "Chain identifier; must match the picked accepted_escrows entry."
        ),
    )
    escrow_address: str = Field(
        description=(
            "Escrow contract address; must match the picked "
            "accepted_escrows entry."
        ),
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Complete buyer-committable EscrowData fields (arbiter, "
            "token, …). Excludes ``amount`` and ``demand``, "
            "which are derived at settlement."
        ),
    )
    expiration_unix: int = Field(
        gt=0,
        description=(
            "Absolute UTC unix-time the on-chain escrow attestation "
            "expires. Both sides commit to this single timestamp; no "
            "clock-drift tolerance window."
        ),
    )


class DomainEvent(BaseModel):
    """Generic domain event transported through core orchestration."""

    model_config = ConfigDict(use_enum_values=False)

    event_id: str = Field(description="Unique event identifier")
    event_type: Any = Field(description="Event type identifier")
    source: str = Field(description="Source identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class DomainAction(BaseModel):
    """Generic domain action selected by policy and executed by action handlers."""

    action_type: Any = Field(description="Action type identifier")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Decision(BaseModel):
    """A policy decision and its execution outcome."""

    decision_id: str = Field(description="Unique decision identifier")
    agent_id: str = Field(description="Agent who made the decision")
    context: "DecisionContext" = Field(description="Context that led to the decision")
    action: DomainAction = Field(description="Chosen action")
    policy_used: str = Field(description="Policy that produced the decision")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the decision was made",
    )
    outcome: dict[str, Any] | None = Field(
        default=None,
        description="Outcome of executing this decision",
    )

    def record_outcome(self, outcome: dict[str, Any]) -> None:
        self.outcome = outcome


class DecisionContext(BaseModel):
    """Domain-neutral policy evaluation context."""

    event: DomainEvent
    agent_id: str
    available_resources: dict[str, Any] = Field(default_factory=dict)
    past_experiences: list[dict[str, Any]] = Field(default_factory=list)
    market_state: dict[str, Any] = Field(default_factory=dict)
    negotiation_history: list[dict[str, Any]] = Field(default_factory=list)

    def get_event_type(self) -> str:
        et = self.event.event_type
        return et.value if hasattr(et, "value") else str(et)

    def has_negotiation_context(self) -> bool:
        return len(self.negotiation_history) > 0
