## ADDED Requirements

### Requirement: Hosted obligation pins profile and authorization

Every newly accepted `fiat.stripe.v1` obligation MUST carry one exact `funding_profile`, deterministic marketplace operation ID, and operation-scoped `funding_authorization_ref` whose hosted materialization fingerprint agrees with accepted amount, currency, payer, claimant, destination account, expiry, and condition. The mechanism-neutral runtime MUST treat the profile and safe authorization reference as immutable mechanism parameters and MUST reject changed reuse.

Marketplace persistence MUST NOT contain a stable hosted payer/instrument ref, Customer, PaymentMethod, mandate, bank/card detail, provider ID/payload, client secret, or raw action. New operations MUST accept only `card.v1`, `us_bank_transfer.v1`, or `us_ach_debit.v1`; legacy card representation is recovery-only.

#### Scenario: Authorization and plan profiles differ

- **WHEN** hosted materialization reports that the authorization does not bind the accepted obligation/profile
- **THEN** servicing fails before funding and does not request another authorization or profile

#### Scenario: Exact materialization is retried

- **WHEN** the same obligation, profile, authorization reference, and operation ID are retried after uncertain acknowledgement
- **THEN** the runtime and adapter reuse one hosted settlement and operation identity

### Requirement: Authoritative profile funding precedes every domain effect

For hosted obligations, only the authority's provider-neutral `funded` state after the exact profile's success and availability gate MAY transition the shared runtime into fulfillment. Setup/payment redirects, confirmation, bank instructions, Checkout completion, webhook-derived local hints, and pending/deferred status MUST NOT authorize fulfillment, evidence, or collection. Status MAY persist only safe reason, deadline, and action metadata.

#### Scenario: ACH reports processing

- **WHEN** authoritative hosted status remains awaiting payment or availability
- **THEN** no domain fulfillment lease, fulfillment side effect, condition evidence, or collect operation is reserved

#### Scenario: Push-transfer instructions were displayed

- **WHEN** the buyer received bank instructions but attributable funds are not authoritatively funded
- **THEN** servicing remains pending and does not treat interaction as payment

### Requirement: Profile-specific reclaim and loss remain authority-owned

The marketplace MUST request reclaim through the same opaque hosted settlement and operation identities and project provider-neutral pending/success/manual outcomes. It MUST NOT select a Stripe cancellation, return, refund, reversal, or dispute operation. A pre-collection funding return MUST block fulfillment/collection and follow hosted reclaim/recovery. A post-collection loss MUST project an incident/manual status without rewriting completed marketplace fulfillment or attempting local reclaim.

#### Scenario: ACH returns before fulfillment

- **WHEN** hosted authority reports the accepted debit returned before the marketplace committed fulfillment
- **THEN** the runtime performs no fulfillment or collection and follows the eligible reclaim/recovery state

#### Scenario: ACH return appears after collection

- **WHEN** hosted status reports a post-collection loss incident
- **THEN** marketplace keeps completed fulfillment and collection identities and exposes safe operator-required state

### Requirement: Legacy card obligations recover without public alias

A migrated marketplace row whose accepted plan used the historical card-only shape MUST continue status, fulfillment, collection, and reclaim recovery with its original option, obligation, hosted settlement, and operation identities. The legacy decoder MUST be selected only from persisted historical state and MUST NOT be used by publication, negotiation, new materialization, or configuration.

#### Scenario: Legacy card row is pending at upgrade

- **WHEN** the shared runtime loads a nonterminal historical card obligation
- **THEN** it resumes the exact legacy hosted operation without requiring a new payer profile, funding authorization, or `card.v1` relabel

## MODIFIED Requirements

### Requirement: Hosted financial authority lifecycle

`fiat.stripe.v1` MUST use the shared obligation journal and conditional-escrow port while the separately operated hosted service remains the sole payer-profile and financial authority. Marketplace rows MUST contain only exact funding profile, operation-scoped funding authorization and settlement references, public lifecycle/reason/deadline/action metadata, condition anchors, canonical fulfillment references, and opaque receipts; they MUST NOT persist stable payer/instrument refs, provider identifiers, Checkout/setup/confirmation/bank-instruction URLs, payment/bank/card/mandate data, credentials, or raw evidence/provider payloads.

#### Scenario: Hosted funding becomes authoritative

- **WHEN** the hosted authority reports the accepted obligation and exact profile funded
- **THEN** the storefront provisions once, binds one immutable condition evidence reference, and only then reports the settlement ready and resumes check/collect through the shared worker

#### Scenario: Reclaim races fulfillment

- **WHEN** the buyer reclaims at expiry while fulfillment, satisfied evaluation, or collection is reserved or complete
- **THEN** the repository compare-and-set rejects reclaim; pending or false evaluation alone does not prevent an otherwise eligible reclaim

#### Scenario: Hosted funding remains delayed

- **WHEN** a bank profile reports a safe pending state or future availability deadline
- **THEN** the shared runtime retains the same obligation and operation without fulfillment, collection, or mechanism fallback

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MAY contain one exact public funding profile and operation-scoped authorization reference but MUST NOT expose a stable payer/instrument or provider model to the runtime.

#### Scenario: Hosted materialization requires buyer action

- **WHEN** `fiat.stripe.v1` materialization or confirmation creates a hosted action
- **THEN** the runtime persists the opaque hosted reference and public action kind/expiry while the URL/client secret remains transient and service-owned

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

### Requirement: Hosted adapter validation and state projection

The `fiat.stripe.v1` adapter MUST accept only buyer-funded, seller-claimed obligations with a positive integer minor-unit amount, lowercase ISO 4217 currency, immutable account reference, exact supported funding profile, operation-scoped funding authorization reference, expiry, and supported typed condition. It MUST verify exact client/manifest/schema/profile capability before use. Provider-neutral awaiting-payment, action-required, deadline, return, and loss states MUST map monotonically into the shared lifecycle. Hosted `operator_review` or post-collection loss MUST project as `manual_required` without inventing a successful outcome or provider detail.

#### Scenario: Condition is not currently satisfied

- **WHEN** the hosted authority returns an authoritative false evaluation before expiry
- **THEN** the shared worker retains a pending condition and may check again without collecting or marking terminal failure

#### Scenario: Hosted authority requires operator review

- **WHEN** status reports `operator_review`
- **THEN** marketplace state reports manual intervention and does not collect, reclaim, or guess provider outcome

#### Scenario: Profile is unsupported by the release

- **WHEN** an accepted new-format obligation names a profile absent from the verified client/manifest capability set
- **THEN** adapter admission fails closed before materialization

### Requirement: Fulfillment and reclaim exclusion

Hosted servicing MUST use the shared obligation identity, exact profile and authorization, operation journal, work leases, and compare-and-set transitions. At stored expiry, reclaim MAY reserve only after re-retrieving current hosted state and only when no authoritative funded state, fulfillment lease or success, submitted collect/provider transfer, or reserved satisfied evaluation exists. Authoritative funded state MAY begin fulfillment; fulfillment success MUST permanently remove marketplace reclaim authority and MUST resume check and collect after restart even when expiry subsequently passes.

#### Scenario: Fulfillment succeeds immediately before expiry

- **WHEN** immutable VM fulfillment commits before the reclaim compare-and-set
- **THEN** reclaim is rejected and restart resumes hosted condition check and collection

#### Scenario: Pending condition reaches expiry without fulfillment success

- **WHEN** no authoritative funding/fulfillment lease or success, collect reservation, or satisfied evaluation exists at expiry after current hosted status retrieval
- **THEN** reclaim may reserve and the shared lifecycle prevents a later collect reservation

#### Scenario: Funding wins at expiry

- **WHEN** re-retrieval proves the accepted bank operation funded before reclaim reservation
- **THEN** the runtime proceeds toward fulfillment under the same obligation rather than reclaiming or releasing it as unpaid

### Requirement: Hosted client owns hosted identity wire

The hosted settlement adapter and payer/authorization consumer MUST pass the selected or recorded persistent marketplace signer through the exact manifest-pinned hosted client identity interface and MUST NOT duplicate hosted canonicalization, headers, scheme implementations, response verification, payer/profile models, authorization encoding, setup/confirmation behavior, or provider models.

#### Scenario: Hosted release lacks the required identity capability

- **WHEN** buyer/storefront startup or publication preflight sees a hosted manifest that does not advertise the configured principal, payer, authorization, and funding-profile contract versions
- **THEN** hosted settlement remains unavailable and no fiat option or funding authorization is created
