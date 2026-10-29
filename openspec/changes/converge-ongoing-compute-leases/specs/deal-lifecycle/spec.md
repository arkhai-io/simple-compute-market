## ADDED Requirements

### Requirement: End-service queues have independent progress

End service MUST register one controller loop whose step runs physical work, bounded authority work, then physical work for newly due ends. Each pass MUST handle failures independently. Physical recovery MUST require no authority call. The step MUST use the foundation's journal, cursor and unknown-outcome contracts.

#### Scenario: Authorities fail during teardown

- **WHEN** a final request is due and neither authority answers
- **THEN** physical work proceeds and authority work remains unresolved without fabricated financial completion

#### Scenario: Authority work discovers a due end

- **WHEN** the authority pass journals a newly due end after the first physical pass
- **THEN** the second physical pass attempts that end in the same controller step without another polling interval

#### Scenario: Physical work fails during a ruling

- **WHEN** teardown fails while a verified ruling is available
- **THEN** authority work proceeds and teardown remains independently retryable

### Requirement: Physical completion requires proven recovery

End service MUST persist physical completion independently of money. It requires authenticated successful capacity-release evidence, proof of no dispatch, or labelled administrator acknowledgement. Unknown dispatch MUST be adopted and ended before automatic completion. Site lease_ended reports MUST remain end-intent evidence, never release proof.

#### Scenario: Initial end intent is received

- **WHEN** a site-signed lease_ended report is kept before teardown finishes
- **THEN** the end and attribution are recorded but physical completion remains false

#### Scenario: Release fails

- **WHEN** a site reports release_failed and capacity has not returned
- **THEN** physical completion remains false even if every financial operation has completed

#### Scenario: Release is proven before the case finishes

- **WHEN** an authenticated capacity-released callback or verified released-lease observation proves recovery while a case is pending
- **THEN** physical completion is true and financial completion remains false

#### Scenario: Nothing was dispatched

- **WHEN** persisted delivery state proves the due end prevented every dispatch
- **THEN** physical completion is recorded without a teardown

### Requirement: Financial completion is end-revision scoped

Financial completion MUST require terminal required parts, resolved end-related cases/effects/corrections and no pending or unknown operation. It MUST be bound to the selected earliest request and relevant case/ruling revisions. Watches and retention MUST continue after completion; earlier evidence or relevant case changes MUST reopen financial work while preserving history. Once-only deals MUST use the same facts.

#### Scenario: Earlier evidence follows completion

- **WHEN** an earlier end arrives after both facts were recorded
- **THEN** a new end revision reopens financial work without resurrecting a resource or deleting prior completion history

#### Scenario: A once-only deal has no financial work

- **WHEN** delivery has ended and its once parts are terminal with no end-related case or pending effect
- **THEN** its financial completion is true without a rate-servicing special case

### Requirement: Lifecycle completion diagnostics are explicit

Seller read/list MUST expose both facts and evidence references, end revision, gap ages, pending operations/cases, repair reason and manual provenance. A due end with either fact false MUST be ending; both true MUST be ended. Permanent refusal or missing required evidence/credentials MUST show repair required without erasing facts. Warning thresholds MUST NOT disable servicing.

#### Scenario: Priced notice leaves a financial gap

- **WHEN** physical recovery is proven while priced notice or a case remains outstanding
- **THEN** diagnostics identify the outstanding work without labelling the entire gap overcharge or claiming a reserve-ahead billing cap

#### Scenario: Delivery is still running

- **WHEN** a committed deal has no due final request
- **THEN** its unstarted/running state remains and neither completion is inferred from successful observation alone

### Requirement: Manual physical acknowledgement is an audited command

Seller submit MUST support acknowledge_physical_recovery only for an authenticated storefront administrator. Its payload MUST bind the deal, resource/end revision and reason under a stable operation key. Changed reuse MUST be rejected. The acknowledgement MUST record principal and evidence provenance as manual, not site evidence or financial completion.

#### Scenario: An operator confirms recovery without site evidence

- **WHEN** an administrator submits a reasoned physical acknowledgement
- **THEN** read/list retain the audit provenance and change only physical completion

#### Scenario: A buyer attempts acknowledgement

- **WHEN** a buyer submits acknowledge_physical_recovery
- **THEN** authorization refuses it without changing either fact

### Requirement: Funding deadlines remain renewable timers

Rate servicing MUST keep verified funded-through as a replaceable local timer, never a speculative lease truncation. Expiry without verified renewal MUST journal a final request and pending authority classification. A future authority stop MUST retain its effective time. Invalid, stale, wrong-transaction or regressed observations MUST establish no new timer or financial fact.

#### Scenario: Funding advances

- **WHEN** a verified observation advances funded-through before expiry
- **THEN** the timer is replaced without an irreversible end from the old deadline

#### Scenario: Exhaustion is confirmed after local expiry

- **WHEN** the verified payment record shows exhaustion stopped billing at or before the timer's end T
- **THEN** the pending classification resolves without exceptional_end

#### Scenario: An outage concealed a top-up

- **WHEN** the timer ended service at T but verified recovery shows billing continued past T
- **THEN** the seller journals exceptional_end(T) under a stable key and keeps financial completion false until its effects resolve

#### Scenario: Classification cannot be verified

- **WHEN** no trustworthy payment record resolves a timer-expiry end
- **THEN** classification stays pending without blocking physical recovery or fabricating an exhaustion stop

### Requirement: Rate admission uses a neutral adapter decision

Rate servicing MUST implement the foundation-owned delivery authorization protocol via the injected payment adapter's authorize operation, not hosted part-field interpretation. Refusal MUST supply classified evidence through unified delivery to the foundation end/filing policy. Local admission and credential revocation MUST use that shared path.

#### Scenario: Adapter evidence is unavailable

- **WHEN** the rate adapter cannot establish financial admission from verified authority evidence
- **THEN** the hook returns pending/refuse with reason and evidence references, not an invented allow

### Requirement: Billing start is one activation-following effect

Rate servicing MUST implement start_billing under the foundation's sole end-service intent/key and activated-delivery envelope. It MUST translate through the injected payment adapter, preserve delivery's intent reference, and resolve unknown rate start through authority read/same-key retry before disclosure. Refusal MUST enter the foundation's classified undelivered handoff.

#### Scenario: Activation fails

- **WHEN** the lease cannot activate to the agreed end
- **THEN** rate start is not issued and unified delivery supplies start/failure evidence to the foundation's filing-timing policy

#### Scenario: Start acknowledgement is lost

- **WHEN** an activated lease's rate start may have succeeded but the response is lost
- **THEN** disclosure waits for resolution of the same journaled operation, with no second owner or fresh start key

### Requirement: Revised end remedies are not discharged by append

Rate servicing MUST consume the foundation's revised-remedy filing/netting contract. Earlier evidence MUST remain unresolved financial work until a verified authority remedy covers its revision; neither an append nor skipped-closed append MUST count as completion. Qualification MUST exercise prior partial effects and append/close races without local remedy arithmetic.

#### Scenario: Earlier evidence arrives during partial ruling application

- **WHEN** a prior case is open with some applied effects and earlier end evidence arrives
- **THEN** prior effects remain tracked, unknown outcomes resolve under their original keys, and a revision-bound filing carries those records rather than assuming append changes the ruling

#### Scenario: Append races case closure

- **WHEN** an evidence append is skipped because the case closed
- **THEN** the new revision remains unresolved and uses its filing path rather than completing on the skipped append

#### Scenario: Repeated self-penalty cannot be safely qualified

- **WHEN** the authority contract does not establish netting prior returns and bond awards across revision filings
- **THEN** the deal remains repair required with kept evidence and no local substitute ruling or fabricated completion

### Requirement: Offline authority recovery has no storefront writer

Operator recovery MUST use injected adapters with the kept commitment bundle, original authority-bound seller credentials and caller-retained operation key. It MUST submit entitled notice or exceptional_end directly without opening storefront persistence, retaining exact results and principal/reason. Unknown outcomes MUST use authority read and same-key retry. Ordinary watch MUST discover those actions on restart.

#### Scenario: Operator acts while storefront is stopped

- **WHEN** the seller submits a permitted notice through the recovery runner
- **THEN** the authority hosts the notice and the storefront later observes it without a second database writer

#### Scenario: The option grants no payee entitlement

- **WHEN** an operator requests emergency recovery for an on-demand deal
- **THEN** the runner files exceptional_end, not an invented payee stop

## MODIFIED Requirements

### Requirement: The seller half lists deals

The seller half MUST offer submit, read, bounded paginated list and watch. Each listed deal MUST carry negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state, current deadline, open-extension status and open cases, plus the completion diagnostics defined here. Once-only deals MUST run from verified commitment until delivery ends. Lifecycle states MUST be unstarted, running, ending, ended or repair required.

#### Scenario: A seller lists its deals

- **WHEN** the seller has no committed deals
- **THEN** list returns an empty page, not an error

#### Scenario: An ended deal receives earlier evidence

- **WHEN** earlier evidence reopens financial work after physical completion
- **THEN** list returns ending with the new revision and preserved physical fact unless a permanent repair reason requires repair required
