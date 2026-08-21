## MODIFIED Requirements

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, and disburse a recorded disposition. Evaluation MUST produce a disposition stating how much of the obligation is owed to the claimant, the remainder being owed to the payer; a satisfied condition is the whole-to-claimant disposition and an unsatisfied one the whole-to-payer disposition. Where the obligation states a scalar lifecycle amount, a disposition MUST express the claimant's share in that amount's own minor units. Where the obligation's value is not scalar, the split MUST remain mechanism-shaped and opaque to the runtime, and conservation MUST be the mechanism's responsibility, because the runtime cannot divide a value it does not interpret. The contract MUST NOT expose separate collection and reclaim operations, because a mechanism that received the two independently could execute them against different splits of one obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MAY contain one exact public funding profile and operation-scoped authorization reference but MUST NOT expose a stable payer/instrument or provider model to the runtime.

An obligation carrying no amount MUST have exactly one disposition available to it, and its mechanism MUST NOT be asked to disburse a split.

#### Scenario: Hosted materialization requires buyer action

- **WHEN** `fiat.stripe.v1` materialization or confirmation creates a hosted action
- **THEN** the runtime persists the opaque hosted reference and public action kind/expiry while the URL/client secret remains transient and service-owned

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

#### Scenario: An evaluation answers with a partial split

- **WHEN** a mechanism's condition evaluation reports part of the obligation owed to the claimant
- **THEN** the runtime records one disposition whose claimant and payer legs sum to the obligation's scalar amount, and disburses that disposition rather than deriving an amount of its own

#### Scenario: A non-financial obligation is disbursed

- **WHEN** a `contact-exchange.v1` obligation with no amount is satisfied
- **THEN** its disposition is the degenerate whole-to-claimant one, no split is offered to the mechanism, and no funding or return machinery is invoked

### Requirement: Durable independent obligation lifecycle
Settlement servicing MUST derive stable repository identity for every ordered
plan obligation and MUST persist materialization, condition evaluation,
disposition, claimant-leg and payer-leg effect state, attempt,
uncertain-acknowledgement, and receipt state independently. Equivalent retries
MUST reuse one operation identity; changed reuse MUST fail closed.

Exactly one disposition MUST be recorded for an obligation, by one compare-and-swap
winner, before any mechanism disbursement I/O. A recorded disposition MUST NOT be
replaced. Each leg MUST be executed at most once, so that an obligation cannot pay out the same
leg twice. Where the obligation states a scalar lifecycle amount, its claimant and payer
legs MUST sum to that amount, so it cannot pay out more than it holds; where the value is
not scalar, the runtime MUST record the mechanism's disposition without arithmetic on it.

#### Scenario: Plan contains obligations in both directions
- **WHEN** an accepted plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized by its payer and collected by its claimant without interpreting list position as direction

#### Scenario: One obligation fails after a sibling completes
- **WHEN** a plan operation requires retry or manual repair after another obligation reached a terminal effect
- **THEN** the completed sibling remains terminal and operator status identifies the affected obligation without replaying the completed effect

#### Scenario: Acknowledgement is uncertain across restart
- **WHEN** a mechanism mutation may have succeeded before its acknowledgement was lost
- **THEN** the operation journal records uncertainty and retry uses the same obligation and operation identity

#### Scenario: Collection races reclaim
- **WHEN** claimant collection and payer reclaim concurrently target one obligation
- **THEN** exactly one disposition reservation may invoke the mechanism and the other observes a busy or terminal outcome

#### Scenario: A mechanism splits a value the runtime cannot divide

- **WHEN** an obligation whose lifecycle amount is absent because its value is a bundle rather than a scalar is evaluated to a partial disposition
- **THEN** the runtime records and disburses the mechanism's own disposition, performs no arithmetic against it, and holds the mechanism to conservation

#### Scenario: A second disposition is offered for a recorded obligation
- **WHEN** an evaluation reports a split for an obligation whose disposition was already recorded
- **THEN** the recorded disposition stands, the obligation is not re-split, and the disagreement is surfaced rather than resolved by overwriting

#### Scenario: One leg succeeds and the other needs repair
- **WHEN** a disposition's claimant leg completes and its payer leg requires retry or manual repair
- **THEN** the completed leg remains terminal and is never replayed, and operator status names the outstanding leg under the same obligation and disposition

### Requirement: Fulfillment and reclaim exclusion

Hosted servicing MUST use the shared obligation identity, exact profile and authorization, operation journal, work leases, and compare-and-set transitions. A payer leg MAY reserve only after re-retrieving current hosted state and only when no authoritative funded state, fulfillment lease or success, submitted claimant leg or provider transfer, or reserved satisfied evaluation exists that the recorded disposition does not account for. A payer leg MUST NOT be refused for the sole reason that the obligation has not reached its stored expiry: expiry is one mechanism's release condition, not a precondition the runtime imposes on every mechanism. A mechanism that cannot return value before expiry MUST refuse the disbursement as its own answer under its own rules. Authoritative funded state MAY begin fulfillment; fulfillment success MUST permanently remove marketplace authority to dispose the whole obligation to the payer and MUST resume check and disbursement after restart even when expiry subsequently passes.

#### Scenario: Fulfillment succeeds immediately before expiry

- **WHEN** immutable VM fulfillment commits before the disposition compare-and-set
- **THEN** a whole-to-payer disposition is rejected and restart resumes hosted condition check and disbursement

#### Scenario: Pending condition reaches expiry without fulfillment success

- **WHEN** no authoritative funding/fulfillment lease or success, claimant-leg reservation, or satisfied evaluation exists at expiry after current hosted status retrieval
- **THEN** the whole-to-payer disposition may reserve and the shared lifecycle prevents a later claimant-leg reservation

#### Scenario: Funding wins at expiry

- **WHEN** re-retrieval proves the accepted bank operation funded before the payer leg reserved
- **THEN** the runtime proceeds toward fulfillment under the same obligation rather than returning or releasing it as unpaid

#### Scenario: An arbiter answers before expiry and funds are unsubmitted

- **WHEN** a mechanism's evaluation records a disposition owing value to the payer while no claimant leg or provider transfer has been submitted and the obligation has not reached its stored expiry
- **THEN** the runtime offers the payer leg to the mechanism rather than refusing it locally, and a mechanism whose release is time-locked refuses it and says so

### Requirement: Profile-specific reclaim and loss remain authority-owned

The marketplace MUST request every payer-directed disbursement through the same opaque hosted settlement and operation identities and project provider-neutral pending/success/manual outcomes. It MUST NOT select a Stripe cancellation, return, refund, reversal, or dispute operation. A pre-fulfillment funding return MUST block fulfillment and claimant disbursement and follow hosted reclaim/recovery. A return after fulfillment starts but before the claimant leg is submitted MUST preserve the immutable fulfillment record, block the claimant leg, order domain-owned VM teardown and capacity cleanup to convergence, and delegate financial return/reclaim entirely to the hosted authority. A post-collection loss MUST project an incident/manual status without rewriting completed marketplace fulfillment or attempting local recovery.

A disposition that splits an obligation MUST be refused unless the bound hosted release declares the capability to execute one. The refusal MUST name the bound release as the reason and MUST NOT be reported as a mechanism failure, and the marketplace MUST NOT approximate a split by issuing a whole-to-claimant disbursement followed by a separately chosen provider refund.

#### Scenario: ACH returns before fulfillment

- **WHEN** hosted authority reports the accepted debit returned before the marketplace committed fulfillment
- **THEN** the runtime performs no fulfillment or claimant disbursement and follows the eligible reclaim/recovery state

#### Scenario: Funding returns after VM fulfillment

- **WHEN** authoritative funding returns after VM fulfillment committed but before the claimant leg reserved or succeeded
- **THEN** the claimant leg remains blocked, the immutable fulfillment record remains attributable, VM teardown and capacity cleanup converge, and hosted financial recovery proceeds without marketplace-selected provider action

#### Scenario: ACH return appears after collection

- **WHEN** hosted status reports a post-collection loss incident
- **THEN** marketplace keeps completed fulfillment and disbursement identities and exposes safe operator-required state

#### Scenario: A split is disbursed against a release that cannot execute one

- **WHEN** an evaluation records a partial disposition for a hosted obligation whose bound release declares no partial-disposition capability
- **THEN** the disbursement is refused as unavailable under the bound release, the obligation retains its identities, and no whole disbursement or marketplace-selected refund is issued in its place
