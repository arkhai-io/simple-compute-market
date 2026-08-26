## MODIFIED Requirements

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
