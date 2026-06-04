"""Domain-agnostic shared schemas.

These models are intentionally minimal and stable. Both the policy
engine (market-policy) and the storefront/buyer runtimes import from
here, so any change is a cross-package break.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    SerializeAsAny,
    field_serializer,
    field_validator,
)

from service.clients.token import ERC20TokenMetadata  # noqa: F401


# ---------------------------------------------------------------------------
# Identity: scheme-tagged seller / signer identity
# ---------------------------------------------------------------------------
# Replaces the prior "wallet address everywhere" convention. The protocol
# layer treats every signed-request signer and every listings-registry
# agent as a (scheme, identifier) pair. ``eip191`` is the default and the
# only built-in scheme; the registry pattern (service.identity) lets other
# schemes register their own verifier so the wire shape remains pluggable.


class Identity(BaseModel):
    """A scheme-tagged identity.

    ``scheme`` names a verifier registered in :mod:`service.identity.registry`
    (e.g. ``"eip191"``). ``identifier`` is the scheme-specific principal —
    for ``eip191`` that's the lowercase 0x hex wallet address; other
    schemes may carry DIDs, OIDC ``sub`` claims, etc.

    Equality and hashing are case-sensitive on both fields. Callers that
    want EIP-191-style case-insensitive matching should lowercase
    ``identifier`` themselves before constructing the model — for the
    ``eip191`` scheme this happens automatically via the field validator
    here.
    """

    scheme: str = Field(
        description=(
            "Name of the identity scheme. Must match a verifier registered "
            "via :func:`service.identity.registry.register_identity_scheme`."
        ),
    )
    identifier: str = Field(
        description=(
            "Scheme-specific principal. For ``eip191`` this is the lowercase "
            "0x-prefixed hex wallet address; for other schemes the value is "
            "scheme-defined (DID URI, OIDC sub claim, ...)."
        ),
    )

    @field_validator("identifier", mode="after")
    @classmethod
    def _normalize_identifier(cls, v: str, info: Any) -> str:
        # Per-scheme normalization: for EIP-191, lowercase the hex address
        # so identities are comparable byte-wise. Other schemes pass through.
        scheme = info.data.get("scheme") if hasattr(info, "data") else None
        if scheme == "eip191":
            return v.lower()
        return v


# ---------------------------------------------------------------------------
# uint256 wire helpers
# ---------------------------------------------------------------------------
# Amounts (token amount, price-per-hour) live in the uint256 domain on chain
# and routinely exceed 2^53 for 18-decimal tokens. JSON numbers can't carry
# uint256 safely (most non-Python parsers treat them as IEEE-754 doubles),
# and SQLite INTEGER is int64 — both lossy past ~9.2e18 base units.
# Pattern: keep Python ``int`` internally (arbitrary precision) and emit
# decimal-digit strings on serialization. Validators accept either form so
# already-stored Python-int data round-trips without a migration.


def _parse_uint256_str(v: Any, field_name: str) -> int | None:
    """Coerce a wire value (int|str|None) into a Python int.

    Accepts:
      * ``None`` — passes through (used for tristate "no advertised value").
      * ``int`` — passes through (back-compat with existing Python callers).
      * decimal-digit ``str`` — parses to int (the canonical wire form).

    Rejects floats, negative values, and anything that doesn't look like a
    non-negative decimal integer.
    """
    if v is None:
        return None
    if isinstance(v, bool):  # bool is a subclass of int — exclude explicitly
        raise ValueError(f"{field_name}: expected non-negative decimal, got bool")
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f"{field_name}: must be non-negative, got {v}")
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if not s.isdigit():
            raise ValueError(
                f"{field_name}: must be a non-negative decimal-digit string, "
                f"got {v!r}"
            )
        return int(s)
    raise ValueError(
        f"{field_name}: must be int, decimal string, or None — got "
        f"{type(v).__name__}"
    )


def _serialize_uint256_str(v: int | None) -> str | None:
    return None if v is None else str(v)


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
            "Non-negative amount in base units (token amount × 10**decimals). "
            "0 = free; null = hidden reserve (negotiate); >0 = public price. "
            "On the wire as a decimal-digit string (uint256-safe); Python int "
            "internally."
        ),
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, v: Any) -> int | None:
        return _parse_uint256_str(v, "amount")

    @field_serializer("amount")
    def _serialize_amount(self, v: int | None) -> str | None:
        return _serialize_uint256_str(v)


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


# ---------------------------------------------------------------------------
# Rate slots: per-unit-time (or per-unit-anything) rates on obligation fields.
# A rate carries the field path on the obligation data plus the unit it
# scales by; the value is in the payment token's base units (uint256 domain).
# At settlement time both sides compute the final field value as
# ``value * duration_quantum // PER_UNIT_QUANTUM[per]`` (integer division;
# sub-unit fractions truncate, matching the prior single-rate semantics).
# ---------------------------------------------------------------------------

# Allowed values for ``RateValue.per`` and the seconds-per-unit divisor used
# at settlement. ``hour`` is the only one wired end-to-end today;
# ``request`` / ``kWh`` etc. are reserved for the design's "non-time rate
# units" open question — adding one is a single dict entry plus negotiated
# quantity (request_count, energy_kwh) carried on the deal.
PER_UNIT_SECONDS: dict[str, int] = {
    "hour": 3600,
}


class RateValue(BaseModel):
    """One rate-bearing slot on an accepted escrow / proposal.

    ``field`` is the dotted/indexed path into the obligation data
    (``"amount"`` for ERC-20 escrows; ``"erc20Amounts[0]"``,
    ``"nativeAmount"`` etc. for TokenBundle). ``per`` is the unit the
    rate scales by — ``"hour"`` for the time-rate case. ``value`` is
    the rate itself in base units, uint256-domain (decimal-digit string
    on the wire, Python int internally).

    Negotiation pressure points at ``value``; ``field`` and ``per``
    come from the seller's escrow template and are non-negotiable.
    """

    field: str = Field(description="Obligation-data field path the rate populates.")
    per: str = Field(default="hour", description="Unit the rate scales by.")
    value: int = Field(description="Rate amount in payment-token base units (uint256).")

    @field_validator("value", mode="before")
    @classmethod
    def _parse_value(cls, v: Any) -> int:
        parsed = _parse_uint256_str(v, "value")
        if parsed is None:
            raise ValueError("RateValue.value must not be null")
        return parsed

    @field_serializer("value")
    def _serialize_value(self, v: int) -> str:
        return _serialize_uint256_str(v) or "0"


def compute_rate_total(rate: RateValue, duration_seconds: int) -> int:
    """Multiply a rate by the negotiated duration.

    Returns the final on-chain field value for ``rate.field``. Uses
    integer division so sub-unit fractions truncate (i.e. for ERC20:
    ``rate × duration_seconds // 3600``).
    """
    divisor = PER_UNIT_SECONDS.get(rate.per)
    if divisor is None:
        raise ValueError(f"unknown rate.per unit: {rate.per!r}")
    return rate.value * duration_seconds // divisor


# ---------------------------------------------------------------------------
# AcceptedEscrow / EscrowProposal accessors
# ---------------------------------------------------------------------------
# Most consumers treat an accepted_escrows entry as a JSON dict (after a
# round-trip through SQLite or the wire); these accessors operate on
# either a Pydantic model OR a dict so the only change at the call site
# is the accessor name.


def primary_rate_value(accepted_or_proposal: Any) -> int | None:
    """Return the headline rate's value for negotiation/display.

    Today's negotiation engine treats every escrow as having a single
    rate — that's true for ERC-20 (the ``amount`` rate) and ``None`` for
    pure-attestation escrows. Multi-rate templates (TokenBundle) return
    the *first* rate; vector negotiation is a deferred extension.

    Returns ``None`` when the escrow advertises no rates (hidden-reserve
    listings, attestation one-shots). Callers translate ``None`` into
    either a hidden-reserve fallback (negotiation strategies) or a
    "no scaling" path (settlement of pure-literal escrows).
    """
    rates = _rates_of(accepted_or_proposal)
    if not rates:
        return None
    first = rates[0]
    if isinstance(first, dict):
        v = first.get("value")
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        return None
    v = getattr(first, "value", None)
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return None


def accepted_token_address(accepted_or_proposal: Any) -> str | None:
    """Return the payment-token address from an ERC-20-style entry.

    Reads ``literal_fields["token"]`` — the canonical place ERC-20 and
    ERC-1155 escrows pin their payment-token. Returns ``None`` for
    escrow kinds (NativeToken, TokenBundle, attestation) that don't
    have a single ``token`` literal.
    """
    literals = _literal_fields_of(accepted_or_proposal)
    val = literals.get("token") if isinstance(literals, dict) else None
    return val if isinstance(val, str) and val else None


def accepted_recipient_address(accepted_or_proposal: Any) -> str | None:
    """Return the escrow demand recipient from an accepted/proposed escrow.

    Preferred source is ``demands[].demand_data.recipient`` on the
    RecipientArbiter demand. ``literal_fields["recipient"]`` remains a
    legacy fallback for transitional data.
    """
    for demand in accepted_demands(accepted_or_proposal):
        data = demand.get("demand_data")
        if isinstance(data, dict):
            val = data.get("recipient")
            if isinstance(val, str) and val:
                return val
    literals = _literal_fields_of(accepted_or_proposal)
    val = literals.get("recipient") if isinstance(literals, dict) else None
    return val if isinstance(val, str) and val else None


def accepted_demands(accepted_or_proposal: Any) -> list[dict[str, Any]]:
    """Return arbiter demands advertised/negotiated for this escrow shape."""
    if isinstance(accepted_or_proposal, dict):
        raw = accepted_or_proposal.get("demands")
    else:
        raw = getattr(accepted_or_proposal, "demands", None)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
        else:
            dumped = item.model_dump() if hasattr(item, "model_dump") else None
            if isinstance(dumped, dict):
                out.append(dumped)
    return out


def _rates_of(entry: Any) -> list[Any]:
    if isinstance(entry, dict):
        out = entry.get("rates")
        return out if isinstance(out, list) else []
    return list(getattr(entry, "rates", []) or [])


def _literal_fields_of(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        out = entry.get("literal_fields")
        return out if isinstance(out, dict) else {}
    return dict(getattr(entry, "literal_fields", {}) or {})


class EscrowDemand(BaseModel):
    """One arbiter demand paired with an escrow obligation.

    ``arbiter`` is the deployed arbiter contract address. ``demand_data``
    is the JSON-shaped input for that arbiter's codec; settlement codecs
    own encoding it into on-chain demand bytes.
    """

    chain_name: str | None = Field(
        default=None,
        description=(
            "Optional chain identifier for listings that advertise demands "
            "across multiple chains."
        ),
    )
    arbiter: str = Field(
        description="Deployed arbiter contract address for this demand.",
    )
    demand_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Codec-specific arbiter demand data.",
    )


class AcceptedEscrow(BaseModel):
    """One escrow shape the seller will accept for this listing.

    Each entry pins the (chain, escrow contract) tuple plus the
    obligation literals + rates the seller has fixed. The buyer's
    proposal references one of these entries by
    ``(chain_name, escrow_address)`` and inherits its ``literal_fields``.

    ``literal_fields`` is escrow-data-only: keys present advertise a seller-
    preferred value; keys absent are open. Never includes a rate-bearing
    field directly — those live in ``rates`` so duration scaling stays
    explicit. Arbiter release criteria live in the listing/proposal-level
    ``demands`` list.

    ``rates`` carries every rate-bearing field on the obligation. For
    ERC20 escrows that's a single ``{"field": "amount", "per": "hour",
    "value": …}`` entry; multi-rate templates (TokenBundle) carry one
    per rate-bearing field. Empty list = hidden reserve (seller did not
    publish a rate; negotiation establishes one via the strategy's
    ``default_min_price``). Readers use the ``primary_rate_value`` /
    ``accepted_token_address`` helpers in this module.
    """

    chain_name: str = Field(
        description=(
            "Alkahest chain identifier (e.g. ``base_sepolia``, ``anvil``). "
            "Combined with ``escrow_address`` to look up the SDK codec via "
            "``service.clients.alkahest.get_escrow_codec_for``."
        ),
    )
    escrow_address: str = Field(
        description=(
            "Deployed escrow obligation contract address on ``chain_name``. "
            "The (chain, address) pair determines the EscrowData ABI."
        ),
    )
    literal_fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Literal obligation-data keys the seller has fixed (e.g. "
            "``token``). Keys present = seller-preferred "
            "value; keys absent = open. Never includes a rate-bearing "
            "field — those live in ``rates``. Arbiter demand criteria "
            "live in ``demands``."
        ),
    )
    rates: list[RateValue] = Field(
        default_factory=list,
        description=(
            "Rate-bearing obligation fields. Each entry pins one field "
            "(``amount`` for ERC20, ``erc20Amounts[i]`` / ``nativeAmount`` "
            "for TokenBundle, …) plus its ``per`` unit and the rate "
            "``value`` in base units. Empty list = hidden reserve. "
            "Readers use ``primary_rate_value`` for the headline rate."
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
            "token, …). Excludes ``amount`` and arbiter demand bytes, "
            "which are derived at settlement."
        ),
    )
    literal_fields: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Forward-looking sibling of ``fields`` for the generic-escrow "
            "migration. When set, mirrors ``fields`` (literal obligation-"
            "data keys the buyer commits to). Readers should prefer the "
            "canonical accessor ``accepted_token_address`` which handles "
            "either shape."
        ),
    )
    rates: list[RateValue] | None = Field(
        default=None,
        description=(
            "Forward-looking sibling for multi-rate templates. Today "
            "negotiation produces a single scalar amount that becomes the "
            "primary rate-bearing field at settlement; future TokenBundle "
            "proposals carry one ``RateValue`` per rate-bearing field."
        ),
    )
    demands: list[EscrowDemand] | None = Field(
        default=None,
        description=(
            "Arbiter demand criteria inherited from the accepted escrow "
            "entry and committed during negotiation."
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
