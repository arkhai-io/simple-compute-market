## MODIFIED Requirements

### Requirement: Accepted-deal delivery priority

The storefront MUST retry and report failed checkpoints without abandoning an otherwise deliverable VM solely for local persistence failure. Protected effects MUST wait for durable admission and intents. Recovery MUST reconcile authoritative state and adopt existing resources rather than replace them.

#### Scenario: Local checkpoint failure does not abandon delivery

- **WHEN** an accepted VM can deliver but a required decision or intent write fails
- **THEN** the storefront reports and retries persistence without discarding the VM
- **AND** defers the protected effect until the write succeeds

### Requirement: Full settlement convergence ownership

The VM storefront MUST own reservation, fulfillment, access and delivery progress through the shared compute path. It MUST hold/commit capacity under deal_ref.negotiation_id without a settlement reference and commit the deal's reservation before fulfillment begins, which begins the lease. Afterwards only end service writes to the lease, except journaled activation before billing/availability. Ends MUST use end service. Selected stages MUST own attestation/readiness/claim binding; the claims engine owns submission/collection, not physical recovery. Common delivery MUST consume evidence, not compare mechanism IDs.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an Alkahest VM's site reservation is looked up
- **THEN** it is found by negotiation, not escrow identity

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches ready evidence
- **THEN** shared delivery activates, completes billing start and records availability without storing credentials
- **AND** selected Alkahest continuation reconciles evidence, readiness and claims when applicable
- **AND** every interrupted step is safe to revisit

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces a ready VM
- **THEN** common delivery uses the same path without an escrow claim or mechanism-ID branch

#### Scenario: Terminal settlement ends a lease

- **WHEN** settlement reaches a terminal state before lease end
- **THEN** end service drives truncation or termination

#### Scenario: An Alkahest delivery activates

- **WHEN** Alkahest delivery reaches ready evidence with local admission
- **THEN** the shared path activates its reservation before availability without issuing hosted billing start

### Requirement: A step after physical fulfillment defers a VM deal, never fails it

Recoverable bookkeeping or evidence-publication failures after provisioning MUST defer delivery and resume the same fulfillment. They MUST NOT alone mark delivery failed. Journaled activation MAY write the lease after physical readiness; lease endings MUST use end service. Terminal start refusal, activation expiry and other genuine delivery failures MUST use the classified end handoff before reporting failed.

#### Scenario: Evidence publication fails after provisioning

- **WHEN** a VM is running and evidence publication fails
- **THEN** delivery is deferred and recovery publishes evidence without another fulfillment

#### Scenario: Restart convergence recovers a reservation never committed

- **WHEN** recovery finds an uncommitted reservation
- **THEN** it commits the exact accepted window before dispatch
- **AND** earlier commits retain their window and identity

#### Scenario: Activation loses to expiry

- **WHEN** a physically ready VM cannot activate because expiry claimed it
- **THEN** delivery enters the classified lifecycle handoff rather than deferring forever as bookkeeping failure

### Requirement: Physical fulfillment resumption

When fulfillment identity exists, recovery MUST query it directly, never schedule or begin a replacement. Nonterminal state MUST remain pending with an identified retry owner; active results MUST yield readiness/resource identities, not persisted credentials. Provider failures MUST use the classified lifecycle handoff. Without identity, recovery MUST reuse the exact request and idempotent reserve/schedule/begin contracts. Selected-stage evidence MUST be revalidated before protected effects.

#### Scenario: Recovery before fulfillment acceptance

- **WHEN** unfinished delivery has persisted context but no fulfillment ID
- **THEN** recovery reuses the exact stored request and target
- **AND** reconciles reservation, scheduling and begin through their idempotent contracts

#### Scenario: Recovery after fulfillment acceptance

- **WHEN** unfinished delivery has a durable fulfillment ID
- **THEN** recovery polls that fulfillment directly
- **AND** does not schedule a replacement or begin another fulfillment

### Requirement: A VM deal records only how to reach its VM

The VM storefront MUST persist readiness and resource identities, not access material. Settle and settle-status MUST obtain buyer-facing connection details live through compute delivery's admission guard. Missing buyer-facing host MUST remain omitted. Authenticated replay storage MUST retain no credential-capable response bodies; exact retries MUST recheck eligibility without weakening signing or changed-request rejection.

#### Scenario: A VM becomes ready

- **WHEN** fulfillment becomes ready
- **THEN** the storefront records readiness and resource identities
- **AND** its authenticated settlement response fetches eligible access material live

#### Scenario: A former access response is retried

- **WHEN** exact retry arrives after a locally admitted end
- **THEN** it is refused without replaying stored connection material

### Requirement: VM evidence and delivery progress are not payment escrows

Evidence MUST remain negotiation-scoped, not a sentinel escrow. Shared delivery MUST own protected progress; legacy domain rows MAY be read-only projections. Additive cutover MUST adopt verified exact requests/identities, defer ambiguous rows for repair, purge access material and enforce the mandatory bridge writer-floor gate. Unknown or conflicting evidence MUST fail closed; real Alkahest state MAY stay with its owner.

#### Scenario: Payment delivery is pending

- **WHEN** verified payment awaits fulfillment
- **THEN** evidence, immutable context and shared delivery progress are recoverable without a payment escrow row

#### Scenario: Evidence is reused for another accepted state

- **WHEN** an evidence write changes established mechanism, Agreement digest or settlement reference
- **THEN** storage rejects it before protected delivery

#### Scenario: A legacy row is adopted

- **WHEN** cutover reconciles an in-flight VM's exact request, window and resource identities
- **THEN** the shared record adopts that resource and legacy progress becomes a read-only projection
- **AND** provider-active or stored credentials alone never imply activation, billing start or availability

#### Scenario: An old binary attempts downgrade

- **WHEN** the actual supported pre-cutover bridge binary opens the migrated database
- **THEN** its writer-floor check refuses before any recovery or foreground writer starts

#### Scenario: A fresh VM schema boots

- **WHEN** introducing migrations bootstrap and rerun
- **THEN** tables exist idempotently with no legacy rows required

#### Scenario: Verified VM evidence is malformed

- **WHEN** proposed verified evidence lacks SHA-256 Agreement digest, authoritative source or supported validated vm.delivery-facts version 1 payload
- **THEN** storage refuses before freezing evidence or delivery progress
