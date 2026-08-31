## ADDED Requirements

### Requirement: API-credit hosted servicing orders financial and domain effects

One accepted hosted API-credit obligation MUST progress in this order: register immutable plan, materialize exact authorization, observe authoritative funded state, reserve and perform exact-once issuance, publish immutable signed issuance evidence, evaluate that exact condition, and collect. Each stage MUST use the shared obligation/operation journal, work lease, compare-and-set transition, and immutable domain fulfillment reference. No later stage may compensate for or imply an earlier stage that has not committed.

#### Scenario: Hosted funding becomes available

- **WHEN** the exact profile reaches authoritative funded state
- **THEN** one issuance lease may reserve the immutable fulfillment identity and no collection may reserve before its evidence is satisfied

#### Scenario: Issuance and collection worker overlap

- **WHEN** concurrent workers inspect the same funded obligation
- **THEN** leases and compare-and-set allow at most one issuance and prevent collection until committed evidence exists

### Requirement: API-credit issuance is the hosted fulfillment boundary

The credits authority's committed grant, not Checkout, provider funding object, or key-delivery attempt, MUST be the immutable domain fulfillment effect. The fulfillment reference MUST bind settlement obligation, service, quantity, key target/owner, grant, and issuance result while excluding bearer secret. Retry after uncertain acknowledgement MUST retrieve the same grant under the same identity; changed issuance input MUST conflict.

#### Scenario: Grant commits before acknowledgement loss

- **WHEN** the storefront times out after quota, key, and balance commit
- **THEN** restart retrieves the same grant and publishes one fulfillment/evidence record without another balance change

#### Scenario: Credential delivery is retried

- **WHEN** issuance succeeded but the buyer did not receive a new unused key secret
- **THEN** domain-owned credential retry follows the existing unused-key rotation rule without changing settlement fulfillment or collection identity

### Requirement: API-credit failure and reclaim are mutually exclusive with issuance

Before issuance success, terminal ownership/quota/key failure or accepted expiry MAY allow reclaim only after current hosted status retrieval and authoritative credits-service reconciliation proves that the exact issuance identity did not commit; an unknown acknowledgement or unavailable reconciliation MUST keep reclaim blocked. Reclaim is also forbidden while any issuance lease/success, satisfied evidence, or collection reservation exists. Funding that remains delayed MUST create no issuance. A successful issuance MUST permanently remove marketplace reclaim authority and continue evidence/collection recovery after expiry. A pre-issuance/pre-collection hosted return MUST block issuance and collection; post-collection financial loss MUST project manual incident state without reversing credits.

#### Scenario: Funded issuance fails terminally

- **WHEN** no credit grant commits and accepted expiry passes
- **THEN** the shared runtime may reserve reclaim and prevents a later issuance or collection reservation

#### Scenario: Issuance wins at expiry

- **WHEN** the exact grant commits before reclaim compare-and-set
- **THEN** reclaim is rejected and restart resumes evidence evaluation and collection

### Requirement: API-credit portable condition is authoritative and replay-safe

Condition evaluation MUST retrieve the signed portable issuance evidence by immutable reference; verify configured issuer/schema/capability, signature, timestamp not future/skewed, authoritative grant commit no later than accepted funding expiry, obligation, service, quantity, key ownership, canonical parties, and grant/fulfillment identity; then return pending, satisfied, failed, or manual-required without exposing the secret. Evidence bound to a timely committed grant remains durably valid for servicing after accepted funding expiry and restart; freshness MUST NOT be interpreted as a wall-clock-age limit on immutable fulfillment. Repeated evaluation MUST be side-effect free. Another obligation's otherwise valid evidence MUST fail.

#### Scenario: Evidence retrieval is temporarily unavailable

- **WHEN** the resolver cannot authoritatively retrieve the exact evidence before expiry
- **THEN** condition remains pending and no collection occurs

#### Scenario: Timely grant is recovered after expiry

- **WHEN** the credits grant committed before accepted expiry but acknowledgement or evidence publication completes after expiry or restart
- **THEN** authoritative reconciliation rejects reclaim, the immutable issuance evidence remains valid, and servicing resumes evidence evaluation and collection under the original identities

#### Scenario: Evidence digest changes

- **WHEN** the same reference resolves to a changed canonical body
- **THEN** evaluation fails or requires operator review and never collects

### Requirement: API-credit recovery stays mechanism and domain exact

Recovery MUST use accepted mechanism/profile/authorization, settlement obligation/operations, and API-credit fulfillment/grant/evidence identities regardless of current priority, readiness, buyer automation, listing state, quota snapshot, or credential-delivery status. It MUST NOT fall back between hosted and Alkahest, reissue credits because a secret is absent, or treat API consumption failure as financial reclaim authority.

#### Scenario: Hosted profile is disabled after issuance

- **WHEN** restart occurs before collection
- **THEN** servicing resumes evidence/collection under the accepted hosted obligation without republishing or selecting Alkahest

#### Scenario: Key is exhausted after completion

- **WHEN** API use consumes the purchased balance
- **THEN** settlement remains complete and ordinary 402/top-up behavior applies rather than reclaim or financial recovery
