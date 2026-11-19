## MODIFIED Requirements

### Requirement: An external-topology scenario extends a locally verifiable scenario

An end-to-end scenario that makes a deal against services or hosts this repository does
not deploy — a hosted payments target, a real host — MUST extend a locally verifiable
scenario that runs against this repository's own stack. It MUST share that scenario's
stages wherever their bodies agree and add only the stages its external parts require.
It MAY take the complete scenario's form, running the shared stages to the scenario's
end, or the live verification form, which runs the shared stages only until the
external producer's output and compares that output with the locally verifiable
scenario's expectation ("A live verification scenario compares a producer's outputs
with a lane's expectations"). An external-topology scenario that makes no deal,
observing state that such deal scenarios left on the same stack, extends no scenario
and MUST name the scenarios whose state it reads. Setup or teardown that needs
knowledge this repository lacks, such as funding a payer account, MUST be left to the
deployment and MUST NOT be performed by the scenario.

#### Scenario: An external-topology scenario is added

- **WHEN** a scenario making a deal against a real host or a hosted payments target is
  added
- **THEN** a locally verifiable scenario running the same shared stages runs in a
  pipeline lane, and the external scenario adds only the stages its external parts need

#### Scenario: A live verification scenario stops at the producer's output

- **WHEN** an external-topology scenario takes the live verification form
- **THEN** it runs the shared stages until the producer's output, compares that output
  with the locally verifiable scenario's expectation, and runs none of the stages that
  scenario runs after it

#### Scenario: An external-topology follow-up makes no deal

- **WHEN** an external-topology scenario reads and changes only state the deal scenarios
  left on the same stack
- **THEN** it extends no locally verifiable scenario, and it names the scenarios it
  follows

#### Scenario: The deployment has not funded the payer

- **WHEN** an external-topology payment scenario runs and the payer cannot approve
- **THEN** the scenario fails or skips naming the payer, and performs no funding itself

### Requirement: Lanes run a mediation double that answers from programmed rules

Every lane MUST run a mediation double, recommended by the lane's registries, that reproduces the dispute authority's API mechanics — authentication, idempotency, the filing's admission checks, signed per-agreement records and cursors, the respondent listing, the closed-case refusal, extensions at the payments double, execution of a ruling's per-part `reverse`, `stop` and `penalty` effects and the record of its delivery end — and takes every ruling from a scenario-programmed rule or operator decision. A `stop` MUST be applied as one stop event from the double's own account through the part's `chosen` stop entry, carrying the partial-period treatment the ruling names. A `penalty` MUST be applied as reversals of earned amounts still held, across the transaction's parts in mandate order, up to the penalty and no further than what is held. It MUST NOT compute a ruling, and with no matching rule it MUST rule nothing. It MUST refuse at install, and install nothing for, a rule or decision whose ruling carries an `award`, which the contract makes unexecutable on `arkhai.payments.v1`.

#### Scenario: A case is filed with no rule installed

- **WHEN** a party files a case and no rule matches it
- **THEN** the double accepts the filing, sends `extend` for each part to the payments double as the authority's own account, and reports each part `held` with its reference, or, when payments refuses it as nothing held, `not_held` with a reason classified from the part's signed amounts: `paid_out` when any money was released, otherwise `reversed` when any was reversed or refunded, otherwise `nothing_held`
- **AND** the case stays open and unruled, unless every part is `not_held`, when the contract's automatic dismissal closes it with nothing held

#### Scenario: A filing's Agreement is not the payment's

- **WHEN** a party files a case whose Agreement's JCS SHA-256 differs from the `deal` in the transaction's signed payment receipt
- **THEN** the double rejects the filing with `agreement_hash_mismatch`, reserves no case, and extends no part

#### Scenario: Protection cannot be established

- **WHEN** the payments double refuses an extend for any reason but nothing held, or cannot be reached
- **THEN** the filing is answered `error` with `protection_incomplete`, no part is reported `not_held`, and a retry under the same key completes the filing once payments answers

#### Scenario: A programmed ruling is applied

- **WHEN** a rule supplies a ruling's basis, delivery end and per-part effects for a matching case
- **THEN** the double records the ruling in the signed per-agreement record, applies each effect at the payments double with a stable effect key and the case reference, and then lifts only that case's extensions

#### Scenario: A programmed ruling stops a rate part

- **WHEN** a rule or operator decision rules `stop` with `returned` on a running rate part
- **THEN** the double sends one stop event as its own account through the part's `chosen` entry with `returned`, the payments double records the part stopped with cause `authority`, and a repeated application sends the same event

#### Scenario: A programmed penalty exceeds what is held

- **WHEN** a ruling's `penalty` exceeds the earned amounts still held across the transaction's parts
- **THEN** the double reverses what is held, part by part in mandate order, and nothing beyond it

#### Scenario: A rule programs an award

- **WHEN** a scenario installs a rule or decision whose ruling carries an `award`
- **THEN** the double refuses it with a typed code and installs nothing

#### Scenario: A ruling waits at its gate

- **WHEN** a rule's ruling with a delivery end and a reverse is held at its gate
- **THEN** the double records the ruled entry with the delivery end and the reverse `prepared`, sends nothing to payments, and applies both, lifts the case's extensions and closes the case only once the rule is resumed

#### Scenario: Payments fails between two effects

- **WHEN** the payments double refuses or drops a ruling's second effect after the first committed
- **THEN** the ruling is recorded as incompletely applied, and resuming applies the remaining effect without applying the first twice

#### Scenario: Closing a case still applying its ruling is refused

- **WHEN** a scenario closes a case whose ruling has an effect payments has not applied
- **THEN** the double refuses the close, lifts nothing, and the case stays applying with its effect prepared

#### Scenario: Appends follow the contract

- **WHEN** either party appends evidence to an open case, or the payer appends concurrence, or anyone appends to a closed case
- **THEN** the evidence is recorded under its actor and idempotency key, the payer's concurrence is refused because only `mandate.to` may concur, and the closed case refuses the append

#### Scenario: A party reads after an absence

- **WHEN** a party reads an agreement's record from its retained cursor
- **THEN** it receives the signed entries after that cursor in sequence, an authorized party reading an agreement with no cases receives an empty signed page, and an unknown agreement or unauthorized reader receives the contract's refusal

#### Scenario: The double's deviation is stated

- **WHEN** a payee files, or concurs in, a `delivery_end` claim that the dispute authority would rule mechanically
- **THEN** the double rules it only when a rule says so, and its README and this specification state that deviation from its producer

## ADDED Requirements

### Requirement: A live verification scenario compares a producer's outputs with a lane's expectations

The minimum expectation for a live verification scenario is that it verifies the
interactions between this repository's services and external systems that the locally
verifiable scenarios could not exercise. A live verification scenario MUST give the
live producer the inputs its locally verifiable scenario gave the producer's double,
produced by this repository's own client code, and MUST check that the producer emits
the outputs that scenario expected. It need test nothing else. The comparison MUST be
one assertion shared by both scenarios, stating which output fields it compares exactly,
which by relation, and which it ignores. The scenario MUST run on wall time, reach an
instant only where its own data fixes it or an authority recorded it as an effect of the
scenario's own request, and read an asynchronous output by polling the producer, bounded.
A producer output that differs from the expectation MUST fail the observation, never
skip it. A decision a person makes reaches the scenario only through a policy the
topology applies or through the scenario itself.

#### Scenario: The producer emits what the double emitted

- **WHEN** a live verification scenario sends the live producer the input its lane twin
  sent the double, and the producer's output agrees with the shared assertion
- **THEN** the observation is made, and no stage after the producer's output runs

#### Scenario: The producer emits something else

- **WHEN** the live producer's output differs from the shared assertion's expectation
- **THEN** the observation fails naming the field and both values

#### Scenario: The producer acts asynchronously

- **WHEN** the producer's output follows the scenario's request on the producer's own
  schedule
- **THEN** the scenario polls the producer's public read until the output appears or its
  bound passes, failing at the bound

### Requirement: Each live verification scenario states its topology requirements

Each live verification scenario MUST state, in prose beside its description in
`e2e-tests/README.md`, what a topology must provide for it, without naming any
infrastructure: what the scenario proves, its provisioning mode, the authorities it needs
and in which mode, its accounts and their starting balances, any ruling policy a person's
decision needs, the run settings it reads, and the cleanup and balance reset its caller
owes between runs. A requirement the topology does not meet MUST leave the observations
needing it unproven, naming the requirement.

#### Scenario: A topology lacks a ruling policy

- **WHEN** a scenario needing a ruling policy runs against a topology that applies none
- **THEN** its observation is unproven, naming the policy requirement, and its other
  stages' results stand

### Requirement: Rate deals and dispute filings are verified live against a prepared topology

The VM live verification scenarios MUST each extend their lane twin in the live
verification form, on a deal of their own, with mock provisioning, against Arkhai
payments in test mode and, where they file, a hosted mediation authority:

- the buyer's stop: a payer stop is recorded with cause `payer` and `charged`, and the
  started period is charged;
- funds running out: with the balance the topology funds for N periods, a `terms` stop
  falls at the funded boundary with N periods settled;
- a spot preemption: a payee stop with notice is pending, then final at the authority's
  receipt plus the notice, with `returned` and the unstarted remainder refunded;
- the term end: the part ends at the Agreement's end with `returned`;
- a seller's filing: the storefront's own `delivery_end` filing as the payee is accepted
  with each part protected, and the authority's ruling is read — an authority stop with
  `returned`, a reversal since the end, the capped penalty, its extensions lifted and the
  case closed;
- a buyer's contested case: the buyer's filing is contested by the storefront, and the
  ruling the topology's declared policy makes — an authority stop with `returned` and a
  reversal — is read.

Each MUST be labelled live evidence with public-safe provenance.

#### Scenario: Funds run out on a live target

- **WHEN** the funds-exhausted scenario runs against a topology that funded its payer for
  N periods
- **THEN** it reads the funded boundary from the signed snapshot, polls until the part's
  stop, and compares the stop's cause, instant and settled amount with its lane twin's
  assertion

#### Scenario: The seller's filing is ruled live

- **WHEN** the seller-filing scenario's storefront files as the payee on a running rate deal
- **THEN** it reads the authority's ruled entry and the payment snapshot through the public
  clients and compares the stop, the reversal, the penalty and the closed case with its
  lane twin's assertion

### Requirement: A dispute on a running rate deal is qualified in the VM lane

The VM lane MUST run, each on its own rate deal under the lane's `[charged, returned]`
declaration and labelled lane-double evidence, a seller's `delivery_end` filing ruled as
the dispute authority documents a mechanical ruling — a `stop` with `returned`, a reverse
of earnings since the end and a penalty — and a buyer's filing the storefront contests,
ruled by an operator decision with a `stop` with `returned` and a reverse. Each MUST show
the storefront recording the authority's stop as an end classified `ruling` with no
filing, the payer's returns, the teardown, and, once the case closes, the seller's list
reading the deal `ended` with no open extension.

#### Scenario: A seller's filing on a rate deal is ruled

- **WHEN** the storefront's administrator ends a running on-demand deal and the double's
  rule rules the payee's filing with a stop, a reverse and a penalty
- **THEN** the storefront records the authority's stop classified `ruling` with no
  further filing, the payer is returned the unstarted remainder and the reversed and
  penalised earnings, and after the case closes the seller's list reads the deal `ended`

#### Scenario: A buyer's contested case on a rate deal is ruled

- **WHEN** the buyer files on a rate deal, the storefront contests, and an operator
  decision rules a stop with `returned` and a reverse
- **THEN** the storefront records the ruled end, the payer is returned what the ruling
  reverses, and after the case closes the seller's list reads the deal `ended`
