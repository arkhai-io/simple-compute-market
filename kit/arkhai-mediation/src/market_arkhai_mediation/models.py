from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)


class Model(RootModel[Any]):
    root: Any


class AccountId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            description='Arkhai account UUID.',
            pattern='^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ),
    ]


class RecordKey(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            description="ed25519: followed by the canonical unpadded base64url public key. Mediation's own key, not the payments key.",
            pattern='^ed25519:[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$',
        ),
    ]


class MediationValue(RootModel[Any]):
    root: Annotated[
        Any,
        Field(description='Opaque JSON value; interpretation belongs to its producer.'),
    ]


class Sha256Hex(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern='^[0-9a-f]{64}$')]


class Cause(StrEnum):
    payee = 'payee'
    payer = 'payer'


class MediationTime(RootModel[StrictInt]):
    root: Annotated[
        StrictInt, Field(description='Integer Unix seconds.', ge=0, le=9007199254740991)
    ]


class PartIndex(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0, le=63)]


class Amount(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern='^[1-9][0-9]{0,37}$')]


class PartialPeriod(StrEnum):
    charged = 'charged'
    returned = 'returned'
    prorated = 'prorated'


class EndDeliveryEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['end_delivery']
    at: MediationTime


class PenaltyEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['penalty']
    amount: Amount


class AwardEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['award']
    part: PartIndex
    amount: Amount


class MarketEd25519Identity(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['ed25519']
    identifier: Annotated[
        StrictStr, Field(pattern='^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$')
    ]


class MarketEip191Identity(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['eip191']
    identifier: Annotated[StrictStr, Field(pattern='^0x[0-9a-f]{40}$')]


class MarketEd25519SignatureProof(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['ed25519']
    value: Annotated[StrictStr, Field(pattern='^[A-Za-z0-9_-]{85}[AQgw]$')]


class MarketEip191SignatureProof(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['eip191']
    value: Annotated[StrictStr, Field(pattern='^0x[0-9a-f]{130}$')]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Annotated[StrictStr, Field(max_length=128, min_length=1)]
    producer: Annotated[StrictStr, Field(max_length=256, min_length=1)]
    at: MediationTime
    sha256: Sha256Hex
    bytes: Annotated[
        StrictStr,
        Field(
            pattern='^(?:[A-Za-z0-9_-]{4})*(?:[A-Za-z0-9_-]{2}[AEIMQUYcgkosw048]|[A-Za-z0-9_-][AQgw])?$'
        ),
    ]


class CaseRef(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            description='Opaque mediation case reference; not a credential.',
            max_length=128,
            min_length=1,
        ),
    ]


class State(StrEnum):
    open = 'open'
    applying = 'applying'
    closed = 'closed'


class HeldPart(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    part: PartIndex
    status: Literal['held']
    extension_ref: Annotated[StrictInt, Field(ge=1, le=9007199254740991)]
    until: MediationTime | None = None


class Reason(StrEnum):
    paid_out = 'paid_out'
    reversed = 'reversed'
    nothing_held = 'nothing_held'


class NotHeldPart(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    part: PartIndex
    status: Literal['not_held']
    reason: Reason


class FilingRefusalCode(StrEnum):
    not_listed_authority = 'not_listed_authority'
    filer_not_party = 'filer_not_party'
    storefront_not_approved = 'storefront_not_approved'
    agreement_hash_mismatch = 'agreement_hash_mismatch'


class FilingPending(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['pending']
    case_ref: CaseRef


class Code(StrEnum):
    protection_incomplete = 'protection_incomplete'
    temporarily_unavailable = 'temporarily_unavailable'
    invalid_request = 'invalid_request'
    idempotency_conflict = 'idempotency_conflict'


class MediationFailure(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['error']
    code: Code
    message: StrictStr


class RecordRef(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            description='Stable opaque reference to one immutable record entry.',
            max_length=128,
            min_length=1,
        ),
    ]


class Identity(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['ed25519']
    identifier: Annotated[
        StrictStr, Field(pattern='^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$')
    ]


class RulingBasis(StrEnum):
    payee_filed = 'payee_filed'
    payee_signed = 'payee_signed'
    operator = 'operator'


class State1(StrEnum):
    prepared = 'prepared'
    applied = 'applied'


class EffectId(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            description='Stable within the Agreement, including across application retries.',
            max_length=128,
            min_length=1,
        ),
    ]


class Reason1(StrEnum):
    ruled = 'ruled'
    dismissed = 'dismissed'


class SignatureProof(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scheme: Literal['ed25519']
    value: Annotated[StrictStr, Field(pattern='^[A-Za-z0-9_-]{85}[AQgw]$')]


class Reason2(StrEnum):
    case_not_found = 'case_not_found'
    case_closed = 'case_closed'
    actor_not_party = 'actor_not_party'


class AppendRefused(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['rejected']
    reason: Reason2
    message: StrictStr


class ReadAfter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    after: Annotated[StrictInt, Field(ge=0, le=9007199254740991)]
    limit: Annotated[StrictInt | None, Field(ge=1, le=1000)] = None


class RespondentAfter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    after: Annotated[StrictStr, Field(max_length=512)]
    limit: Annotated[StrictInt | None, Field(ge=1, le=100)] = None


class Filer(StrEnum):
    payer = 'payer'
    payee = 'payee'


class DisputeAuthority(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    interface: Literal['arkhai.mediation.v1']
    origin: Annotated[StrictStr, Field(pattern='^https?:\\/\\/[^/?#\\s]+(?::[0-9]+)?$')]
    account: AccountId
    record_key: RecordKey
    params: dict[StrictStr, MediationValue]


class DeliveryEndClaim(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['delivery_end']
    ended_at: MediationTime
    delivered: StrictBool
    cause: Cause


class ReverseEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['reverse']
    part: PartIndex
    amount: Amount


class StopEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['stop']
    part: PartIndex
    at: MediationTime
    partialPeriod: PartialPeriod


class MarketIdentity(RootModel[MarketEd25519Identity | MarketEip191Identity]):
    root: MarketEd25519Identity | MarketEip191Identity


class MarketSignatureProof(
    RootModel[MarketEd25519SignatureProof | MarketEip191SignatureProof]
):
    root: MarketEd25519SignatureProof | MarketEip191SignatureProof


class PartProtection(RootModel[HeldPart | NotHeldPart]):
    root: HeldPart | NotHeldPart


class FilingRefused(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['rejected']
    reason: FilingRefusalCode
    message: StrictStr


class Effect(
    RootModel[
        ReverseEffect
        | StopEffect
        | EndDeliveryEffect
        | PenaltyEffect
        | AwardEffect
    ]
):
    root: ReverseEffect | StopEffect | EndDeliveryEffect | PenaltyEffect | AwardEffect


class SignedDeliveryEndClaim(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    claim: DeliveryEndClaim
    signer: MarketIdentity
    proof: MarketSignatureProof


class EvidenceAppend(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    case_ref: CaseRef
    items: Annotated[list[EvidenceItem], Field(min_length=1)]
    concurrence: SignedDeliveryEndClaim | None = None


class ConcurrenceAppend(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    case_ref: CaseRef
    items: list[EvidenceItem] | None = None
    concurrence: SignedDeliveryEndClaim


class CaseAnswer(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    case_ref: CaseRef
    transaction: Sha256Hex
    agreement: Sha256Hex
    state: State
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]


class AppendedEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    transaction: Sha256Hex
    case_ref: CaseRef
    sequence: Annotated[
        StrictInt,
        Field(
            description='Per Agreement across ALL cases; starts at 1. Never a per-case cursor.',
            ge=1,
            le=9007199254740991,
        ),
    ]
    record_ref: RecordRef
    actor: AccountId
    at: MediationTime
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    issuer: Identity
    kind: Literal['appended']
    items: list[EvidenceItem]
    concurrence: SignedDeliveryEndClaim | None = None


class OutcomeEffect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: EffectId
    effect: Effect
    state: State1


class EffectsRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['effects']
    effects: Annotated[list[Effect], Field(min_length=1)]


class Append(RootModel[EvidenceAppend | ConcurrenceAppend]):
    root: Annotated[
        EvidenceAppend | ConcurrenceAppend,
        Field(
            description='Either party may append evidence to an open case; only the payee may append concurrence. At least nonempty items or concurrence is required. Idempotency-Key is required; retries return the same record. Omitted items are recorded as an empty array.'
        ),
    ]


class FilingAccepted(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['accepted']
    case: CaseAnswer


class Outcome(RootModel[list[OutcomeEffect]]):
    root: list[OutcomeEffect]


class NothingHeldClosedEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    transaction: Sha256Hex
    case_ref: CaseRef
    sequence: Annotated[
        StrictInt,
        Field(
            description='Per Agreement across ALL cases; starts at 1. Never a per-case cursor.',
            ge=1,
            le=9007199254740991,
        ),
    ]
    record_ref: RecordRef
    actor: AccountId
    at: MediationTime
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    issuer: Identity
    kind: Literal['closed']
    reason: Literal['dismissed']
    dismissal_reason: Literal['nothing_held']
    outcome: Outcome


class DecidedClosedEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    transaction: Sha256Hex
    case_ref: CaseRef
    sequence: Annotated[
        StrictInt,
        Field(
            description='Per Agreement across ALL cases; starts at 1. Never a per-case cursor.',
            ge=1,
            le=9007199254740991,
        ),
    ]
    record_ref: RecordRef
    actor: AccountId
    at: MediationTime
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    issuer: Identity
    kind: Literal['closed']
    reason: Reason1
    basis: RulingBasis
    outcome: Outcome


class Request(RootModel[DeliveryEndClaim | EffectsRequest]):
    root: DeliveryEndClaim | EffectsRequest


class FilingAnswer(
    RootModel[FilingAccepted | FilingRefused | FilingPending | MediationFailure]
):
    root: FilingAccepted | FilingRefused | FilingPending | MediationFailure


class RuledEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    transaction: Sha256Hex
    case_ref: CaseRef
    sequence: Annotated[
        StrictInt,
        Field(
            description='Per Agreement across ALL cases; starts at 1. Never a per-case cursor.',
            ge=1,
            le=9007199254740991,
        ),
    ]
    record_ref: RecordRef
    actor: AccountId
    at: MediationTime
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    issuer: Identity
    kind: Literal['ruled']
    basis: RulingBasis
    outcome: Outcome


class ClosedEntry(RootModel[NothingHeldClosedEntry | DecidedClosedEntry]):
    root: NothingHeldClosedEntry | DecidedClosedEntry


class PendingAnswer(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    case_ref: CaseRef
    transaction: Sha256Hex
    agreement: Sha256Hex
    filed_at: MediationTime
    filer: Filer
    request: Request
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    filed_record_ref: RecordRef


class Filing(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    transaction: Sha256Hex
    agreement: MediationValue
    request: Request
    concurrence: SignedDeliveryEndClaim | None = None
    claim: StrictStr
    items: list[EvidenceItem]


class FiledEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    transaction: Sha256Hex
    case_ref: CaseRef
    sequence: Annotated[
        StrictInt,
        Field(
            description='Per Agreement across ALL cases; starts at 1. Never a per-case cursor.',
            ge=1,
            le=9007199254740991,
        ),
    ]
    record_ref: RecordRef
    actor: AccountId
    at: MediationTime
    parts: Annotated[list[PartProtection], Field(max_length=64, min_length=1)]
    issuer: Identity
    kind: Literal['filed']
    filing: Filing


class RespondentPage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    cases: list[PendingAnswer]
    next_after: StrictStr
    has_more: StrictBool


class RecordEntry(RootModel[FiledEntry | AppendedEntry | RuledEntry | ClosedEntry]):
    root: FiledEntry | AppendedEntry | RuledEntry | ClosedEntry


class SignedRecordEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    entry: RecordEntry
    proof: SignatureProof


class RecordPage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    agreement: Sha256Hex
    entries: list[SignedRecordEntry]
    next_after: Annotated[StrictInt, Field(ge=0, le=9007199254740991)]
    has_more: StrictBool


class AppendAccepted(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['accepted']
    record: SignedRecordEntry


class AppendAnswer(RootModel[AppendAccepted | AppendRefused | MediationFailure]):
    root: AppendAccepted | AppendRefused | MediationFailure
