## MODIFIED Requirements

### Requirement: Profile-specific reclaim and loss remain authority-owned

The marketplace MUST request reclaim through the same opaque hosted settlement and operation identities and project provider-neutral pending/success/manual outcomes. It MUST NOT select a Stripe cancellation, return, refund, reversal, or dispute operation. A pre-fulfillment funding return MUST block fulfillment and collection and follow hosted reclaim/recovery. A return after fulfillment starts but before collection MUST preserve the immutable fulfillment record, block collection, order domain-owned VM teardown and capacity cleanup to convergence, and delegate financial return/reclaim entirely to the hosted authority. A post-collection loss MUST project an incident/manual status without rewriting completed marketplace fulfillment or attempting local reclaim.

Where the hosted authority raises an incident, the marketplace MUST project that incident's own reference, kind, and evidence digest alongside the obligation's status, and MUST NOT re-derive, rename, or summarize them. An incident is the authority's provider-neutral vocabulary, so a consumer distinguishes a parked dispute from a parked operator review without provider access. Where the authority raises no incident, the projection MUST report its absence rather than omitting the field.

A post-collection loss MUST leave capacity service running. No domain adopting the hosted mechanism may end a lease, tear down a Physical Resource, or release a Capacity Reservation because funding was reversed after collection succeeded, and a domain whose cleanup path refuses a collected lifecycle MUST NOT be asked to run it. The delivered service is recovered, if at all, by the authority's own operator recovery, not by the marketplace.

#### Scenario: ACH returns before fulfillment

- **WHEN** hosted authority reports the accepted debit returned before the marketplace committed fulfillment
- **THEN** the runtime performs no fulfillment or collection and follows the eligible reclaim/recovery state

#### Scenario: Funding returns after VM fulfillment

- **WHEN** authoritative funding returns after VM fulfillment committed but before collection reserved or succeeded
- **THEN** collection remains blocked, the immutable fulfillment record remains attributable, VM teardown and capacity cleanup converge, and hosted financial recovery proceeds without marketplace-selected provider action

#### Scenario: ACH return appears after collection

- **WHEN** hosted status reports a post-collection loss incident
- **THEN** marketplace keeps completed fulfillment and collection identities and exposes safe operator-required state

#### Scenario: An operator distinguishes two parked obligations

- **WHEN** one obligation is parked by an authority incident and another by operator review with no incident raised
- **THEN** the first projects the incident's reference, kind, and evidence digest, the second projects their absence, and neither exposes a provider identifier, message, or payload

#### Scenario: A delivered machine survives a post-collection dispute

- **WHEN** funding is reversed after collection succeeded on an obligation whose Capacity Reservation is serving a delivered Physical Resource
- **THEN** the lease runs to its accepted end, no teardown or capacity cleanup is ordered in any adopting domain, and the obligation reports the loss instead

#### Scenario: A domain whose cleanup refuses a collected lifecycle

- **WHEN** a post-collection loss drives a bare-metal obligation terminal
- **THEN** no physical cleanup is requested, so no lifecycle error is raised and discarded, and the loss is reported through the same projection every other domain uses

### Requirement: Hosted adapter validation and state projection

The `fiat.stripe.v1` adapter MUST accept only buyer-funded, seller-claimed obligations with a positive integer minor-unit amount, lowercase ISO 4217 currency, immutable account reference, exact supported funding profile, operation-scoped funding authorization reference, expiry, and supported typed condition. It MUST verify exact client/manifest/schema/profile capability before use. Provider-neutral awaiting-payment, action-required, deadline, return, and loss states MUST map monotonically into the shared lifecycle. Hosted `operator_review` or post-collection loss MUST project as `manual_required` without inventing a successful outcome or provider detail.

A hosted operation refused by the authority with a non-retryable error MUST
retain the authority's own stable error code. The released client's message,
identifiers, and payloads MUST NOT reach marketplace persistence or any
marketplace response; the code MUST, because it is the authority's own
vocabulary rather than provider detail.

An obligation the marketplace parks as `manual_required` MUST project a stable
reason alongside its status, in the same field a consumer reads for a funding
reason, and every domain adopting the hosted mechanism MUST project it
identically. A `manual_required` projection carrying no reason MUST NOT occur.

Every hosted obligation MUST project whether delivery survived the loss that ended it. That projection MUST be true exactly when the obligation reached a terminal state in which capacity service was withheld or taken back — fulfillment never committed, or committed and was then torn down to convergence — and false otherwise, including for an obligation parked by a post-collection loss whose service continues. It MUST NOT assert that fulfillment was prevented, because the runtime begins fulfillment on authoritative funding and a loss ordinarily arrives afterwards. Every adopting domain MUST project it from one shared surface, so no storefront can report a status whose delivery consequence is unstated.

#### Scenario: Condition is not currently satisfied

- **WHEN** the hosted authority returns an authoritative false evaluation before expiry
- **THEN** the shared worker retains a pending condition and may check again without collecting or marking terminal failure

#### Scenario: Hosted authority requires operator review

- **WHEN** status reports `operator_review`
- **THEN** marketplace state reports manual intervention and does not collect, reclaim, or guess provider outcome

#### Scenario: Profile is unsupported by the release

- **WHEN** an accepted new-format obligation names a profile absent from the verified client/manifest capability set
- **THEN** adapter admission fails closed before materialization

#### Scenario: Hosted authority refuses an operation outright

- **WHEN** the authority answers a hosted operation with a non-retryable error carrying its own error code
- **THEN** the obligation is parked as `manual_required` recording that code, and neither the authority's message nor any provider identifier or payload is persisted

#### Scenario: An operator reads a parked obligation

- **WHEN** an obligation is projected while parked as `manual_required`
- **THEN** the projection names a stable reason for the parking, so the operator can distinguish a refused condition, an unsupported profile, and an account that lost a capability without provider access

#### Scenario: Two domains park the same obligation shape

- **WHEN** the VM, API-credit, and bare-metal storefronts each project an obligation their authority refused for the same reason
- **THEN** all three carry the same stable reason in the same field, because the projection is built from one shared surface

#### Scenario: A loss takes back a delivered machine

- **WHEN** funding returns after fulfillment committed but before collection, and domain teardown and capacity cleanup converge
- **THEN** the obligation projects delivery as not surviving the loss, even though fulfillment had committed and its record remains attributable

#### Scenario: A loss leaves the machine serving

- **WHEN** funding is reversed after collection succeeded and the lease continues
- **THEN** the obligation projects delivery as surviving, so a consumer reading the same terminal `manual_required` status can tell the two losses apart
