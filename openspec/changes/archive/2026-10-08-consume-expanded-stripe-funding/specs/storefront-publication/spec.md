## ADDED Requirements

### Requirement: Hosted publication separates ready funding alternatives

For each VM resource, the storefront MUST build one distinct hosted option for each complete configured clause whose exact funding profile is ready. `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1` MUST remain separate alternatives even when rate, currency, and condition are equal. Deterministic option identity and the accepted plan MUST bind profile, rate, currency, account reference, funds flow, parties, expiry policy, and condition. One profile's blocker MUST NOT suppress another ready hosted profile or Alkahest.

#### Scenario: Three hosted profiles are ready

- **WHEN** one VM listing has complete ready clauses for card, US bank transfer, and ACH
- **THEN** it publishes three distinct hosted options in configured order, each projecting one exact profile

#### Scenario: Push transfer is unready

- **WHEN** bank-transfer readiness fails while card and ACH remain ready
- **THEN** only the push-transfer option is suppressed and the safe blocker identifies its profile without provider data

### Requirement: Hosted accepted plan carries authorization safely

The accepted hosted obligation MUST pin the exact funding profile and deterministic marketplace operation ID. Before materialization the buyer MUST obtain one exact hosted `funding_authorization_ref`; storefront start MAY accept only negotiation ID, obligation ID, and that safe reference. The storefront MUST reload amount, currency, parties, destination account, profile, expiry, and condition from accepted seller state, verify the reference through the hosted client during ordinary materialization, and persist only the safe reference and fingerprint.

Stable payer-profile or instrument refs, Customer/PaymentMethod/mandate data, provider identifiers, raw actions, and buyer automation policy MUST NOT enter negotiation, accepted terms, start requests, storefront SQLite, logs, or evidence.

#### Scenario: Authorization covers another profile

- **WHEN** a start request supplies a funding authorization that does not bind the accepted profile and obligation
- **THEN** materialization fails without creating another authorization or selecting another profile

#### Scenario: Start is retried after acknowledgement loss

- **WHEN** the buyer repeats the exact negotiation, obligation, and funding-authorization reference
- **THEN** storefront and hosted authority converge on the same settlement and operation identities

### Requirement: Legacy hosted card decoding is recovery-only

Already accepted hosted card plans and in-flight marketplace settlement rows MUST retain their immutable option, obligation, operation, and hosted settlement identities through upgrade. A recovery-only decoder MAY interpret their historical `payment_method_types=("card",)` representation, but publication, negotiation, config migration, start, and new plan validation MUST accept only `card.v1` and MUST NOT advertise the legacy representation as an alias.

#### Scenario: Existing card obligation resumes

- **WHEN** restart loads an accepted legacy card plan with a nonterminal hosted operation
- **THEN** it resumes the same settlement and operation identity without republishing, reauthorizing, or rewriting it as a new `card.v1` purchase

#### Scenario: New listing uses legacy card fields

- **WHEN** publication input contains `payment_method_types` or the recovery-only legacy value
- **THEN** validation rejects it and identifies the exact `funding_profile` replacement

### Requirement: Delayed funding does not authorize VM fulfillment

Storefront status MAY project awaiting-payment reason, safe deadline, and transient action metadata for card, push transfer, or ACH. It MUST NOT reserve capacity fulfillment, provision a VM, publish fulfillment evidence, or collect until the hosted authority authoritatively reports the accepted profile funded. Expiry/reclaim MUST re-retrieve current hosted state under the same operation before releasing or refunding.

#### Scenario: ACH is processing

- **WHEN** hosted status reports the accepted ACH obligation pending availability
- **THEN** the storefront persists only safe pending metadata and performs no VM fulfillment or collection

#### Scenario: Funding succeeds at expiry boundary

- **WHEN** a reclaim attempt reaches expiry while provider funding may have completed
- **THEN** authoritative status under the same operation decides funding versus reclaim before capacity or financial action

## MODIFIED Requirements

### Requirement: Preflighted hosted VM publication

A VM storefront with hosted settlement enabled MUST preflight the exact signed client/manifest/schema, payer/profile/authorization capabilities, listing account, selected condition resolver, currency/country policy, and each configured funding profile before publishing deterministic separate-charge/transfer options. Each ready clause MUST produce one option containing only account reference, `funds_flow="separate_charges_transfers"`, exact `funding_profile`, lowercase currency/rate, interaction capability, and typed condition descriptor. Failure MUST suppress only the affected hosted profile and MUST NOT prevent ready hosted peers or valid Alkahest publication.

#### Scenario: Hosted preflight fails

- **WHEN** readiness, manifest, account, condition, or selected profile capability cannot be verified
- **THEN** the storefront emits a sanitized profile-specific diagnostic and publishes all independently ready hosted and Alkahest choices

#### Scenario: One bank profile is unsupported

- **WHEN** the verified authority release or policy does not admit one configured bank profile/currency/country combination
- **THEN** that clause publishes no option while ready card or other exact profiles remain

### Requirement: Dedicated hosted settlement routes

Hosted start, status, and reclaim MUST use `/api/v1/settlements`; the legacy `/api/v1/settle/{escrow_uid}` carrier and behavior remain Alkahest-only. Hosted start accepts accepted negotiation and obligation identifiers plus one safe operation-scoped `funding_authorization_ref` only, and reloads buyer, claimant, money, account, exact funding profile, expiry, condition, and provision input from persisted seller state. Status and reclaim MUST never return or accept stable payer/instrument refs or provider data.

#### Scenario: Buyer starts accepted hosted settlement

- **WHEN** the accepted buyer signs a start request containing the two accepted IDs and exact authorization reference
- **THEN** the storefront idempotently registers/materializes that exact plan and returns only opaque state plus optional transient action

### Requirement: Server-authoritative settlement start

`POST /api/v1/settlements` MUST accept only negotiation ID, obligation ID, and one safe funding-authorization reference, reload the accepted plan, and resolve payer, claimant, account, money, profile, expiry, and condition server-side. `GET /api/v1/settlements/{settlement_ref}` MUST return public provider-neutral status, safe reason/deadline, and an optional transient buyer action. Buyer-authorized `POST .../{settlement_ref}/reclaim` MUST enter the shared reclaim lifecycle; internal collection MUST run through the shared claims engine. These routes MUST NOT alias or change `/api/v1/settle/{escrow_uid}`.

#### Scenario: Start request supplies provider or money fields

- **WHEN** a caller attempts to override payer profile, instrument, account, amount, currency, funding profile, condition, or provider parameters
- **THEN** the storefront rejects the request and creates no hosted settlement

#### Scenario: Existing Alkahest settle route is called

- **WHEN** a legacy buyer calls `/api/v1/settle/{escrow_uid}`
- **THEN** response shape, authorization, persistence, and side effects remain unchanged

#### Scenario: Funding authorization is absent

- **WHEN** a new hosted start request omits the operation-scoped authorization reference
- **THEN** the storefront rejects it before materialization rather than asking the seller or authority to choose a payer instrument

## REMOVED Requirements

### Requirement: Preflighted VM fiat option publication

**Reason**: The requirement duplicated hosted VM preflight while hard-coding `payment_method_types=("card",)`. `Preflighted hosted VM publication` now owns exact per-profile readiness and publication.

**Migration**: New publication uses one option per exact `funding_profile`. Existing accepted card plans retain recovery-only decoding and immutable identities; the removed field is not accepted for new config, publication, or negotiation.
