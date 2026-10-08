## ADDED Requirements

### Requirement: Bare-metal buyer selects an exact hosted whole-host option

The runnable bare-metal buyer MUST display and select one exact compatible settlement alternative and hosted funding profile from a trusted `bare_metal.v1` listing, then sign demand and authorization derived from the selected option. It MUST preserve agreement, listing, site/resource constraint, seller/claimant, amount/currency, condition, offer/funding/fulfillment deadlines, and accepted-term digests through run-log resume. Buyer overrides MUST be limited to legitimate buyer-owned inputs such as profile choice, payer authorization, access public material/reference, and bounded off-session policy; they MUST NOT select provider/executor internals or rewrite seller/resource facts.

#### Scenario: Buyer chooses US bank transfer

- **WHEN** `us_bank_transfer.v1` is advertised and the buyer selects it
- **THEN** the signed authorization preserves that exact profile and accepted whole-host binding through funding and resume

#### Scenario: Buyer requests a nonadvertised profile

- **WHEN** the buyer asks for ACH Direct Debit on a card-only listing
- **THEN** selection fails locally before negotiation or hosted creation

### Requirement: Bare-metal buyer handles transient funding without capacity assumptions

The buyer MUST expose safe card, bank-transfer, and ACH transient actions through the shared hosted action contract, wait for authoritative hosted state, and resume exactly after restart. `requires_action`, bank instructions, pending ACH, authentication fallback, user decline, or delayed funding MUST NOT be reported as host reservation, allocation, provisioning, lease readiness, or access.

#### Scenario: Off-session card requires interaction

- **WHEN** bounded opt-in automation returns a safe `requires_action`
- **THEN** the buyer presents the interactive action, preserves the same operation, and does not claim that physical work has begun

#### Scenario: Buyer restarts during bank funding

- **WHEN** the run log contains an accepted obligation and safe bank instructions but no authoritative funded state
- **THEN** resume reuses the same obligation/operation and queries shared status without creating another payment or capacity request

### Requirement: Bare-metal success requires portable real-access evidence

The buyer MUST report purchase success only after it verifies the hosted result and signed portable bare-metal evidence binding the accepted agreement/obligation, exact selected Physical Resource where applicable, committed allocation/lease and fulfillment references, canonical buyer/claimant, access method, access readiness, and lease expiry. Evidence MUST remain credential-free; access secret retrieval MUST use the existing domain-owned, authenticated, one-use or otherwise bounded delivery contract.

#### Scenario: No-op or synthetic fulfillment is returned

- **WHEN** the result lacks an authoritative allocation/lease reference or real access-ready evidence
- **THEN** the buyer rejects success and follows ordinary pending/failure/recovery behavior

#### Scenario: Real host access is ready

- **WHEN** signed evidence verifies and the domain access-delivery seam returns buyer-authorized access material
- **THEN** the buyer reports the host lease ready without persisting private SSH keys, bearer credentials, or provider topology in the run log

### Requirement: Bare-metal buyer distinguishes reclaim from teardown

Before collection, the buyer MAY request reclaim only when shared servicing declares the obligation eligible after authoritative expiry or terminal pre-fulfillment failure. After collection/transfer, the buyer MUST NOT request financial reclaim to end a lease; lease expiry, revocation, and teardown remain physical lifecycle operations observable through the domain result/status seam.

#### Scenario: Provisioning fails before access readiness

- **WHEN** funding is authoritative but capacity or provisioning fails terminally before valid evidence/collection
- **THEN** the buyer can observe reclaim eligibility and the final financial outcome without receiving access

#### Scenario: Buyer lease reaches its end after collection

- **WHEN** the collected lease expires
- **THEN** the buyer observes revocation/teardown separately and no financial reclaim is inferred
