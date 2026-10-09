## MODIFIED Requirements

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, and disburse a recorded disposition. Evaluation MUST produce a disposition stating how much of the obligation is owed to the claimant, the remainder being owed to the payer; a satisfied condition is the whole-to-claimant disposition and an unsatisfied one the whole-to-payer disposition. A disposition that is not degenerate MUST be over an obligation stating a scalar lifecycle amount and MUST express the claimant's share in that amount's own minor units. An obligation whose value is not scalar MUST have only the two degenerate dispositions available to it, and a split offered over one MUST be refused: the runtime cannot conserve a value it does not interpret, and no mechanism arbiter that divides value operates on a non-scalar one. The contract MUST NOT expose separate collection and reclaim operations, because a mechanism that received the two independently could execute them against different splits of one obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MAY contain one exact public funding profile and operation-scoped authorization reference but MUST NOT expose a stable payer/instrument or provider model to the runtime.

An obligation carrying no amount MUST have exactly one disposition available to it, and its mechanism MUST NOT be asked to disburse a split.

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged

#### Scenario: An evaluation answers with a partial split

- **WHEN** a mechanism's condition evaluation reports part of the obligation owed to the claimant
- **THEN** the runtime records one disposition whose claimant and payer legs sum to the obligation's scalar amount, and disburses that disposition rather than deriving an amount of its own

#### Scenario: A non-financial obligation is disbursed

- **WHEN** a `contact-exchange.v1` obligation with no amount is satisfied
- **THEN** its disposition is the degenerate whole-to-claimant one, no split is offered to the mechanism, and no funding or return machinery is invoked

#### Scenario: A reclaim carries mechanism-scoped options

- **WHEN** a payer requests reclaim supplying options the selected mechanism understands
- **THEN** the runtime dispatches them to that mechanism's client unread and unstored, and the obligation's durable state gains no field naming them

#### Scenario: A second reclaim names different options

- **WHEN** a reclaim is requested for an obligation whose earlier reclaim reservation bound different options
- **THEN** the reservation is refused, and the refusal names a conflicting request rather than reaching the mechanism

#### Scenario: A mechanism that needs no options is unaffected

- **WHEN** a reclaim supplies no options, or supplies options to a mechanism that reads none
- **THEN** the operation proceeds exactly as it does today with no additional mechanism input

### Requirement: Durable independent obligation lifecycle
Settlement servicing MUST derive stable repository identity for every ordered
plan obligation and MUST persist materialization, condition evaluation,
disposition, claimant-leg and payer-leg effect state, attempt,
uncertain-acknowledgement, and receipt state independently. Equivalent retries
MUST reuse one operation identity; changed reuse MUST fail closed.

Exactly one disposition MUST be recorded for an obligation, by one compare-and-swap
winner, before any mechanism disbursement I/O. A recorded disposition MUST NOT be
replaced. Its claimant and payer legs MUST sum to the obligation's scalar amount, and each leg MUST
be executed at most once, so that an obligation can neither pay out more than it holds nor
pay out the same leg twice.

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

#### Scenario: A split is offered over a value that is not scalar

- **WHEN** an obligation whose lifecycle amount is absent because its value is a bundle rather than a scalar is evaluated to a partial disposition
- **THEN** the split is refused, the obligation keeps only its two degenerate dispositions, and the refusal names the obligation's value as indivisible rather than the mechanism as failed

#### Scenario: A second disposition is offered for a recorded obligation
- **WHEN** an evaluation reports a split for an obligation whose disposition was already recorded
- **THEN** the recorded disposition stands, the obligation is not re-split, and the disagreement is surfaced rather than resolved by overwriting

#### Scenario: One leg succeeds and the other needs repair
- **WHEN** a disposition's claimant leg completes and its payer leg requires retry or manual repair
- **THEN** the completed leg remains terminal and is never replayed, and operator status names the outstanding leg under the same obligation and disposition
