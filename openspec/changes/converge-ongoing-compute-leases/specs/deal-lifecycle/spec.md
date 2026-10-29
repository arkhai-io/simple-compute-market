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

Financial completion MUST require terminal required parts, resolved end work and no pending/unknown operation. Terminal means a verified authority stop/end, not payout; once parts use their own term end or earlier stop, and unstarted rates still require stop/end. Completion MUST bind the earliest request and relevant correction/case revisions. Watches/retention MUST continue; earlier evidence or case changes MUST reopen financial work with history. Once-only deals MUST use these facts.

#### Scenario: Earlier evidence follows completion

- **WHEN** an earlier end arrives after both facts were recorded
- **THEN** a new end revision reopens financial work without resurrecting a resource or deleting prior completion history

#### Scenario: A once-only deal has no financial work

- **WHEN** delivery has ended and its once parts have verified authority ends with no end-related case or pending effect
- **THEN** financial completion is true even if an ordinary dispute-window hold has not paid out

### Requirement: Lifecycle completion diagnostics are explicit

Seller read/list MUST expose both facts and evidence references, end revision, gap ages, pending operations/cases, repair reason and manual provenance. A due end with either fact false MUST be ending; both true MUST be ended. Permanent refusal or missing required evidence/credentials MUST show repair required without erasing facts. Pending cooperative stops and billing after delivery end MUST be named. Warning thresholds MUST NOT disable servicing.

#### Scenario: Priced notice leaves a financial gap

- **WHEN** physical recovery is proven while a cooperative billing stop with priced payer notice or a case remains outstanding
- **THEN** diagnostics identify that work without labelling the entire gap overcharge or claiming a reserve-ahead billing cap

#### Scenario: Delivery is still running

- **WHEN** a committed deal has no due final request
- **THEN** its unstarted/running state remains and neither completion is inferred from successful observation alone

### Requirement: Manual physical acknowledgement is an audited command

Seller submit MUST dispatch acknowledge_physical_recovery locally to end service only for an authenticated administrator. Its payload MUST bind deal, resource/end revision and reason under a stable key; at MUST be the observed recovery instant, never future. Changed reuse MUST be rejected. Acceptance MUST name a local audit record, manual principal/provenance and updated physical fact, never site evidence or financial completion. Contracts and typed client MUST carry this local result.

#### Scenario: An operator confirms recovery without site evidence

- **WHEN** an administrator submits a reasoned physical acknowledgement
- **THEN** read/list retain the audit provenance and change only physical completion

#### Scenario: A buyer attempts acknowledgement

- **WHEN** a buyer submits acknowledge_physical_recovery
- **THEN** authorization refuses it without changing either fact

### Requirement: Funding deadlines remain renewable timers

Rate servicing MUST keep verified funded-through as a replaceable timer, never speculative lease truncation. Expiry MUST first attempt a bounded payment read. Renewal MUST replace the timer; verified exhaustion MUST supply an authority end without classification. Only unreachable/unverifiable authority MUST cause a bare-timer end with pending classification. Future stops MUST keep their effective times. Invalid/stale/mismatched/regressed evidence MUST establish no timer or financial fact.

#### Scenario: A last-poll top-up is reachable

- **WHEN** funding advances within one polling interval before expiry and the expiry read verifies it
- **THEN** the timer is replaced without ending delivery or creating seller self-correction

#### Scenario: Exhaustion is verified at expiry

- **WHEN** the expiry read verifies the authority's exhaustion stop
- **THEN** its effective time supplies the final request and no pending classification is created

#### Scenario: An outage concealed a top-up

- **WHEN** a bare timer ended service at T during an outage and verified recovery shows billing continued past T
- **THEN** foundation resolve_correction atomically journals SCM exceptional_end(T); the adapter maps it to authorized stop/reverse messages only, and financial work stays unresolved until verified effects complete

#### Scenario: Classification cannot be verified

- **WHEN** no trustworthy payment record resolves a bare-timer end
- **THEN** foundation's pending classification remains durable without blocking physical recovery or fabricating an exhaustion stop

### Requirement: Both storefronts compose the rate delivery adapter

Both compositions MUST bind foundation's neutral authorization and billing-start contracts to spot's payment adapter and unified delivery's ports. End service MUST drive the shared journaled start effect from its loop. Composition MUST consume foundation's admission, start identity, evidence and correction contracts. Activation validation MUST accept the Agreement end or a verified earlier end recorded by end service, but MUST suppress start on activation failure or unexplained mismatch.

#### Scenario: Notice shortens the lease before activation

- **WHEN** an entitled future stop shortens the lease before provisioning completes
- **THEN** activation to that verified earlier end is valid and start may proceed while the end is still future

#### Scenario: Activation response is lost before truncation

- **WHEN** activation succeeded but its response was lost and end service then recorded a verified earlier end
- **THEN** retry consumes unified delivery's current-end evidence rather than restoring the old end or refusing valid activation

### Requirement: Offline authority recovery has no storefront writer

Recovery MUST use a seller export, original authority-bound credentials and a durable immutable command envelope written before I/O. It MUST fix key, kind/time/payload, authority, evidence references, principal/reason and per-part descriptors. Replay MUST read first and reuse identical descriptors without opening storefront persistence. Results MUST be retained separately. Foundation/spot's correction contract MUST govern adoption, semantic effect identities and overlapping revisions.

#### Scenario: A seller prepares recovery evidence

- **WHEN** an authenticated seller exports a committed deal through lifecycle read-only export and its typed client/CLI
- **THEN** the bundle contains exact Agreement, mandate/commitment, authority bindings and kept signed evidence/effect references, without credentials; missing required bytes refuses recovery

#### Scenario: Recovery is interrupted before result export

- **WHEN** an entitled notice or exceptional_end may have succeeded but no result was saved
- **THEN** the runner consumes the retained envelope and resolves its original effects by read/same-key retry without reconstructing time or payload

#### Scenario: Recovery overlaps online replay

- **WHEN** the runner corrected an end whose journaled intent is replayed after storefront restart
- **THEN** watch discovers the payment effects, matching semantic identities are adopted and no effect is duplicated under a different caller key
- **AND** different correction bases use qualified overlapping/revision reconciliation or remain repair required, never a speculative extra reversal or duplicate exceptional-end case

#### Scenario: On-demand restitution uses explicit authority

- **WHEN** an operator requests emergency recovery for an on-demand deal
- **THEN** the adapter sends stop per part under the buyer-checked seller PT0S/returned entry and reverse per part/amount under existing reverse authority, with no exceptional-end payments field or implicit role-based permission
- **AND** the mandate does not enforce non-preemption; a buyer case over held money and the bond supplies the remedy

#### Scenario: Spot immediate stop support is gated

- **WHEN** payments cannot represent several stop entries per account per part
- **THEN** spot's seller immediate-stop dependency stays gated and emergency exit waits out seller notice, rather than inventing an immediate entitlement

#### Scenario: Cooperative stop lacks authorization

- **WHEN** end_delivery reaches the storefront but no entry authorizes its dispute-free stop using the buyer's treatment
- **THEN** delivery ends at signed receipt time but the buyer half must stop payments; the storefront neither waives payer notice nor substitutes the seller restitution entry

### Requirement: Rotation evidence has a durable servicing consumer

During identity overlap the loop MUST request spot's verified re-anchoring evidence for running rate deals and persist it in the evidence store before retiring dependence on the old key. Seller read/list MUST expose unanchored rate deals and once-only must-drain dependencies as retirement repair reasons. Spot MUST remain the owner of verification and rotation policy.

#### Scenario: A retiring key still anchors a running deal

- **WHEN** overlap begins and no current verified snapshot has re-anchored the rate deal
- **THEN** servicing requests and persists re-anchoring evidence and read/list report the remaining dependency until it is resolved

## MODIFIED Requirements

### Requirement: The seller half lists deals

The seller half MUST offer submit, read, bounded paginated list with a continuation token and watch. Each listed deal MUST carry negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state, current deadline, open-extension status and open cases, plus the completion diagnostics and rotation dependencies defined here. Once-only deals MUST run from verified commitment until delivery ends. Lifecycle states MUST be unstarted, running, ending, ended or repair required.

#### Scenario: A seller lists its deals

- **WHEN** the seller has no committed deals
- **THEN** list returns an empty page, not an error

#### Scenario: An ended deal receives earlier evidence

- **WHEN** earlier evidence reopens financial work after physical completion
- **THEN** list returns ending with the new revision and preserved physical fact unless a permanent repair reason requires repair required
