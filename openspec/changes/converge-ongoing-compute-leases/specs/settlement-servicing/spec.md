## ADDED Requirements

### Requirement: Rate-part end service has independent queues

End service MUST service physical effects and authority work independently, physical first per cycle. Physical work MUST require no payment or dispute call. A failure in either queue MUST NOT suppress the other. Authority observations MUST be verified before use, and each record cursor MUST advance only after its effects are journaled. Newly observed due ends MUST schedule physical work without waiting another normal polling interval.

#### Scenario: Authorities are unavailable during teardown

- **WHEN** a due final request exists and neither authority answers
- **THEN** physical teardown proceeds, authority operations remain pending under stable keys, and no financial-completion fact is fabricated

#### Scenario: Teardown fails while a ruling arrives

- **WHEN** a domain physical effect fails and a verified ruling is available
- **THEN** authority work continues and the physical effect remains independently retryable

#### Scenario: A snapshot cannot be trusted

- **WHEN** a snapshot is invalid, stale under the adapter's verification rules, for another transaction, or regresses the verified record
- **THEN** it supplies no new financial or funding fact and existing physical work remains runnable

### Requirement: Rate-part completion distinguishes delivery from authority work

End service MUST persist physical and financial completion separately. Physical completion requires site end evidence, proof of no dispatch, or labelled authenticated manual recovery; unknown dispatched work MUST first be adopted and ended. Financial completion requires confirmed terminal parts and resolved end-related cases, effects and corrections with no pending or unknown operation. Neither physical completion nor filing acceptance alone proves financial completion.

#### Scenario: A lease ends before its case is ruled

- **WHEN** site-signed lease end evidence is kept but the exceptional-end case remains pending
- **THEN** physical completion is true, financial completion is false, and diagnostics identify the pending case and gap without calling priced notice an overcharge

#### Scenario: Delivery was never dispatched

- **WHEN** the earliest final request prevents dispatch and persisted delivery state proves no resource was dispatched
- **THEN** physical completion is recorded without a site teardown and required financial work continues

#### Scenario: Late evidence follows completion

- **WHEN** an earlier authenticated end or a relevant ruling arrives after both completion facts were recorded
- **THEN** watching and evidence retention have preserved it, financial work reopens for the new end revision, prior completion history remains, and no resource is resurrected

#### Scenario: Earlier evidence arrives after the case closed

- **WHEN** an earlier authenticated service end is learned after an end-related case closed and dispute protection still permits another case
- **THEN** the seller files exceptional_end for the new end revision under a stable filing key with prior effects as evidence, rather than appending to the closed case or applying a remedy itself

#### Scenario: An operator confirms physical recovery

- **WHEN** an authenticated operator records physical recovery with a reason because site evidence is unavailable
- **THEN** read/list identify the fact as manual, retain the audit record, and do not treat it as site evidence or financial completion

### Requirement: Funding timers are not lease ends

Rate-part servicing MUST maintain the latest verified funded-through deadline as a renewable local timer. A later verified funding observation MAY advance the timer without extending or truncating a lease. Expiry without renewal MUST enter end service as a final request. Pending stops MUST retain the payment authority's effective time and MUST NOT be converted to immediate effective stops merely because they were observed.

#### Scenario: Funding advances before expiry

- **WHEN** a verified observation advances funded-through before the local timer expires
- **THEN** the timer is replaced and no irreversible lease end was created from the old funding deadline

#### Scenario: Funding cannot be verified at expiry

- **WHEN** the previously verified timer expires without verified renewal
- **THEN** end service records a final request and, if no entitlement covers that local end, journals exceptional_end for the evidenced service end

#### Scenario: A seller notice is pending

- **WHEN** the payment authority records a future notice stop
- **THEN** service may continue to its effective time, end service records that future final request, and the payment stop does not depend on a surviving storefront timer

### Requirement: Rate-part admission composes one delivery path

Rate-part servicing MUST implement the unified delivery path's authorization phases through its injected payment adapter. It MUST provision before payee-only start, journal the start before I/O, resolve unknown outcomes under the same key, and serialize dispatch/disclosure with the earliest due final request. Refusal MUST enter the undelivered path. Already disclosed access MUST be revoked through physical recovery, not solely by refusing credential reads.

#### Scenario: An effective end races disclosure

- **WHEN** a local due final request is recorded before credentials are disclosed
- **THEN** disclosure is refused, any dispatched fulfillment is adopted and terminated, and the undelivered financial path is journaled

#### Scenario: Start acknowledgement is lost

- **WHEN** the payment authority may have applied start but its response is lost
- **THEN** the same operation is resolved by authority read/retry before disclosure and start is not issued under a fresh key

#### Scenario: A remote stop follows disclosure

- **WHEN** an effective payer stop is observed during healthy servicing after access was disclosed
- **THEN** it is incorporated within the configured polling interval and physical recovery runs within the declared watchdog/teardown budget, rather than promising instantaneous remote revocation

### Requirement: Unentitled rate-part ends are durably self-filed

An unentitled local delivery end MUST journal exceptional_end(at) with its final request and submit it through the dispute adapter. Failed or never-started delivery MUST use the deal's start as at. Case outcomes MUST be applied only by the dispute authority. End service MUST observe stop-now and reversals under afterStop holds and case extensions rather than backdate stops or require reverse-before-stop. Late evidence MUST be kept and journaled for append when relevant.

#### Scenario: Site withdrawal is learned after restart

- **WHEN** a site-signed lease_ended reports an earlier unentitled end
- **THEN** the seller keeps the signed bytes, makes them available to the buyer, and journals exceptional_end or an append to the existing case without inventing a backdated payee stop

#### Scenario: Crash follows final-request persistence

- **WHEN** the storefront crashes after recording an unentitled final request but before submitting its filing
- **THEN** restart replays the journaled filing under its original operation key and financial completion stays false until the required authority effects resolve

#### Scenario: Buyer ends while payment authority is down

- **WHEN** the buyer's authenticated end_delivery arrives without a confirmed payer stop
- **THEN** the storefront ends delivery and returns its signed acknowledgement without an authority read, makes no money-movement claim, and the buyer half can use that evidence for buyer_end(at)

### Requirement: Rate-part safety does not depend on a seller horizon

Servicing MUST NOT require payee vouch, a billing horizon, or site renewal as buyer protection. Its disclosures MUST distinguish the buyer's priced stop notice, seller reserve-ahead exposure on exhaustion, maximum-term stop and held-money dispute recovery. They MUST NOT claim reserve-ahead bounds charges after an unnoticed service end. Warning thresholds MUST NOT disable servicing.

#### Scenario: Storefront is absent after a site failure

- **WHEN** the site ends service and the storefront remains absent
- **THEN** the buyer can stop and file using its kept evidence, held earnings remain reversible under the agreed window and accepted extensions, and no automatic crash-to-stop or reserve-ahead billing cap is claimed
