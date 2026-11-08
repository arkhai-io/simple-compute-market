## ADDED Requirements

### Requirement: Lanes run a mediation double that answers from programmed rules

Every lane MUST run a mediation double, recommended by the lane's registries, that reproduces the dispute authority's API mechanics — authentication, idempotency, signed per-agreement records and cursors, the respondent listing, the closed-case refusal, extensions at the payments double and execution of a ruling's effects — and takes every ruling from a scenario-programmed rule. It MUST NOT compute a ruling, and with no matching rule it MUST rule nothing.

#### Scenario: A case is filed with no rule installed

- **WHEN** a party files a case and no rule matches it
- **THEN** the double accepts the filing, sends `extend` for each part to the payments double as the authority's own account, and reports each part `held` with its reference or `not_held` with the payments refusal's reason
- **AND** the case stays open and unruled

#### Scenario: A programmed ruling is applied

- **WHEN** a rule supplies a ruling's basis, delivery end and per-part effects for a matching case
- **THEN** the double records the ruling in the signed per-agreement record, applies each effect at the payments double with a stable effect key and the case reference, and then lifts only that case's extensions

#### Scenario: Payments fails between two effects

- **WHEN** the payments double refuses or drops a ruling's second effect after the first committed
- **THEN** the ruling is recorded as incompletely applied, and resuming applies the remaining effect without applying the first twice

#### Scenario: Appends follow the contract

- **WHEN** either party appends evidence to an open case, or the payer appends concurrence, or anyone appends to a closed case
- **THEN** the evidence is recorded under its actor and idempotency key, the payer's concurrence is refused because only `mandate.to` may concur, and the closed case refuses the append

#### Scenario: A party reads after an absence

- **WHEN** a party reads an agreement's record from its retained cursor
- **THEN** it receives the signed entries after that cursor in sequence, an authorized party reading an agreement with no cases receives an empty signed page, and an unknown agreement or unauthorized reader receives the contract's refusal

#### Scenario: The double's deviation is stated

- **WHEN** a payee files, or concurs in, a `delivery_end` claim that the dispute authority would rule mechanically
- **THEN** the double rules it only when a rule says so, and its README and this specification state that deviation from its producer

### Requirement: Lane double controls are typed deterministic steps

Both doubles MUST offer controls through one typed contract and client, shared with the end-to-end harness: when→then rules with refusals and transport faults, the mediation double's filing overrides, rulings, effects gate, operator decisions, closes and case listing, the payments double's funding and receipt-signer rotation, and rule listings. Controls MUST be lane-private, authenticated by a fixture token, and each MUST act only when the scenario advances it.

#### Scenario: A response is lost after commit

- **WHEN** a drop-after-commit rule matches a request
- **THEN** the double commits the request and abandons its response, the caller sees a transport error, and a retry under the same key returns the original result without a second effect

#### Scenario: A double is unavailable

- **WHEN** an unavailable rule is installed on a double
- **THEN** every connection to it closes unanswered and its callers see a transport error until the rule is removed

#### Scenario: A scenario leaves a rule behind

- **WHEN** a module ends with a rule still installed
- **THEN** the rule listing shows it with its matched and waiting counts

### Requirement: Each lane double reads a perceived clock the scenario advances

Each double MUST evaluate time from a perceived clock, wall time plus an offset that only a control moves, and only forward; one harness helper MUST advance both doubles together, and each double's status MUST report its perceived now. Due authority state MUST become visible at the next read, with no background work.

#### Scenario: A once part's hold is passed

- **WHEN** a scenario advances both doubles' clocks past a once part's release instant
- **THEN** the next read shows the part paid out, and a case filed afterwards reports that part `not_held`

### Requirement: A lane-owned mediation target fails rather than skips

Each lane's runner MUST read its mediation target, CA bundle path, the buyer's mediation token and the control token from its committed lane profile, and the buyer MUST receive its token under the variable its dispute credential names. An unready lane-owned mediation target MUST fail setup by name; an unready external one MUST report a blocked skip.

#### Scenario: The lane's mediation double is not ready

- **WHEN** a lane's mediation target is marked its own and does not report itself ready
- **THEN** setup fails naming it, before any scenario stage

### Requirement: A controls scenario proves each control kind in the VM lane

The VM lane MUST run a module of once-only deals that proves, end to end through the storefront's dispute servicing, a programmed ruling with a delivery end, an operator decision without one, a lost filing response, an unavailable mediation double, payments failing between ruling effects, and a clock advance past a hold, with the clock advance last.

#### Scenario: A programmed ruling ends delivery

- **WHEN** a rule rules a filed case with a delivery end and a reverse effect
- **THEN** the payments double shows the reverse and the storefront ends delivery after observing the ruling

#### Scenario: An operator discount leaves the deal running

- **WHEN** an operator decision reverses part of the held money with no delivery end
- **THEN** the reverse lands and the deal keeps running

#### Scenario: A filing response is lost

- **WHEN** the response to the storefront's filing is dropped after commit
- **THEN** the dispute adapter adopts the one filed case and no second case exists

### Requirement: The in-lane payments double mirrors the service and proves its engine's surface

The VM, bare-metal and API-credit lanes MUST each run a payments double that wraps the payments kit's `PaymentsAuthority` engine and mirrors the payments service's HTTP API: its routes, bearer authentication, approval admission, read authorization, idempotency and error codes. The double MUST always sign `livemode: false`, MUST be reached over HTTPS under a lane CA the lane's callers trust through their configured CA bundle paths, and MUST hold only labelled public development fixtures. Its suite MUST prove the rate and hold surface its engine serves through the kit's real client. A lane result MUST be labelled lane-double evidence, never hosted-ledger, funding or live evidence.

#### Scenario: A lane's once-only payment scenario runs

- **WHEN** the bare-metal or API-credit lane runs its payment scenario
- **THEN** the scenario approves, receives a verified receipt and is refunded through the double, and does not skip

#### Scenario: The VM payment scenario runs

- **WHEN** the VM lane runs its payment scenario
- **THEN** it approves, receives a verified receipt, delivers, replays the commit and reaches servicing through the double, and its operator-end case and refund stages run against the lane's mediation double, without skipping

#### Scenario: An approval is retried after its mandate expires

- **WHEN** a payer repeats an approval the double has already made, after the mandate's expiry
- **THEN** the double returns the original receipt rather than refusing the mandate as expired

#### Scenario: The double mirrors a refusal

- **WHEN** a caller approves a mandate it is not the payer of, or reads a transaction or balance it may not read
- **THEN** the double refuses it with the payments service's status and error code

#### Scenario: The rate and hold surface is proven

- **WHEN** the double's suite drives rate parts, stops with notice, per-part ends, exhaustion, `afterStop` holds, partial reverses and `extend` and `lift` through the payments kit's client over HTTP
- **THEN** each answer and refusal is the engine's, and the earliest pending stop takes effect when the perceived clock reaches it

#### Scenario: A result against the double is reported

- **WHEN** a lane's payment scenario passes against the doubles
- **THEN** it is labelled lane-double evidence with each double's installed contract hashes, and establishes SCM's use of the boundaries, not either service's ledger, funding, adjudication or availability

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane against the lane doubles

The VM and bare-metal lanes MUST each run a buyer purchase that discovers, negotiates and
pays through the shipped buyer CLI (`market buy`, `market bare-metal buy`) in
`arkhai.payments.v1` against the lane's payments double, delivers through mock
provisioning, and ends: the VM lease through back-dating and a stepped lease-watchdog
cycle, the bare-metal lease through the buyer's `market bare-metal teardown`. The
purchase stages MUST be defined once and shared by every scenario that buys this way,
and each stage MUST log the identifiers it reads. The bare-metal lane's purchase is its
qualified payment purchase, which runs the shared stages and inserts its own; the VM
lane's purchase lists a resource of its own on a registered host, since a listing's
binding to its resource outlives the listing.

#### Scenario: A VM lane purchase completes

- **WHEN** the VM lane runs its buyer purchase
- **THEN** `market buy` approves the payment, the seller delivers after a verified
  receipt, and back-dating the lease and stepping one watchdog cycle tears the guest down
  and releases its capacity

#### Scenario: A bare-metal lane purchase ends by the buyer

- **WHEN** the bare-metal lane runs its buyer purchase and the buyer runs
  `market bare-metal teardown`
- **THEN** the reclaim runs and the whole host's capacity is restored

#### Scenario: The bare-metal purchase's steps change

- **WHEN** a discovery, purchase, correlation, delivery or buyer-teardown step of the
  bare-metal lane's purchase changes
- **THEN** it changes in the shared stage, and the observation 4 and 5 module runs the
  changed stage without an edit of its own

#### Scenario: A purchase is checked against its payment records

- **WHEN** a buyer purchase completes
- **THEN** each transaction is bound to its Agreement, its receipt covers that mandate,
  its snapshot names the configured payer and payee with gross equal to the Agreement's
  price, and the payer's available balance fell by exactly the scenario's own debits

#### Scenario: The buyer's delivery-end filing reaches the mediation double

- **WHEN** the bare-metal buyer's teardown files a delivery-end case with the lane's
  mediation double and no rule matches it
- **THEN** the case is filed and each part reported held or not held, nothing is ruled,
  and the scenario does not read the filing as a ruling or refund

## REMOVED Requirements

### Requirement: The VM payment scenario's case stages need a mediation target

**Reason**: Every lane now runs a mediation double, so the VM payment scenario's case and refund stages run against it rather than skipping for want of a target.

**Migration**: "Lanes run a mediation double that answers from programmed rules" and "A lane-owned mediation target fails rather than skips" replace it; the VM stages' outcome is in "The in-lane payments double mirrors the service and proves its engine's surface".

### Requirement: Lanes run payment scenarios against an in-lane payments double

**Reason**: Its claim of only the once-only surface and its pinned unanswerable dispute authority no longer hold: the double's suite proves its engine's rate and hold surface, and the lanes pin the mediation double.

**Migration**: "The in-lane payments double mirrors the service and proves its engine's surface" carries its retained obligations; "Lanes run a mediation double that answers from programmed rules" replaces the pinned authority.

### Requirement: A compute buyer purchase settled through Arkhai payments runs in each compute lane

**Reason**: Its bare-metal buyer's delivery-end filing now reaches the lane's mediation double instead of no authority.

**Migration**: "A compute buyer purchase settled through Arkhai payments runs in each compute lane against the lane doubles" carries every retained obligation and replaces the filing scenario.
