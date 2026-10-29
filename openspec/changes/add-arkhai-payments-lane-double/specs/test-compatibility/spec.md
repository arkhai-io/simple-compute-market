## ADDED Requirements

### Requirement: Lanes use separate runnable authority doubles

Credential-free payment lanes MUST provide HTTP doubles of the payment and dispute boundaries, using the real clients and separate authority identities, records and availability. Test tooling MUST own both runnable doubles; production kits MUST own their contracts and signing fixtures without importing that tooling. The payment double MUST sign only test-mode records, and fixture authority trust MUST remain lane-only.

#### Scenario: Existing payment scenarios run in a lane

- **WHEN** the bare-metal or API-credit lane runs its existing payment deal with the default lane profile
- **THEN** it reaches the payment double through HTTP rather than skipping for an absent payments target
- **AND** receipt gating, retry and mock delivery observations are attributed to the marketplace boundary, not live ledger or provider behavior

#### Scenario: One authority is unavailable

- **WHEN** a scenario disables payments while mediation is ready, or disables mediation while payments is ready
- **THEN** the other authority remains independently reachable
- **AND** no storefront, adapter or double silently assumes the unavailable authority's identity or powers

### Requirement: Authority doubles declare a pinned contract mode

Each double MUST select `published` or `proposed` before scenario mutation. Published mode MUST implement the exact vendored publication and available conformance vectors. Proposed mode MUST pin and label its candidate and differences. Unsupported operations MUST fail explicitly. Contract metadata MUST be reported without altering signed wire frames, and a missing required publication or frame vector MUST preclude a published qualification claim for that surface.

#### Scenario: The vendored contract lacks a target feature

- **WHEN** a lane needs per-part lifecycle or mediation behavior absent from its vendored publication
- **THEN** it runs that behavior only against an explicitly pinned proposed contract or reports the missing prerequisite
- **AND** published mode does not silently grant the proposed capability

#### Scenario: A snapshot frame has no published vector

- **WHEN** a scenario depends on a signed snapshot frame not yet covered by a producer vector
- **THEN** its candidate frame is identified and its evidence is proposed qualification, never published conformance
- **AND** a placeholder proof is not accepted as a verified snapshot

### Requirement: Payment double models per-part lifecycle and held-money correction

The target payment double MUST model per-part authorities, payee-only rate start, notice-bearing pending stops, term/exhaustion stops, afterStop holds, repeatable partial reversal of held money and independently referenced hold extensions. Its behavior MUST follow the selected contract. It MUST NOT invent a billing horizon, backdated stop, minimum-spend primitive or released-funds refund route.

#### Scenario: Seller notice survives a storefront outage

- **WHEN** an entitled seller schedules a rate-part stop and then its storefront becomes unavailable
- **THEN** the payment double retains the pending stop and applies it no earlier than the sender's notice allows without another storefront call
- **AND** the earliest pending stop wins and cannot be withdrawn

#### Scenario: A seller has no stop entitlement

- **WHEN** the payee attempts to stop an on-demand rate part whose mandate grants it no stop authority
- **THEN** the payment double refuses the command
- **AND** a dispute authority may still apply an authorized ruling with its own account

#### Scenario: A stopped part still holds reversible earnings

- **WHEN** a part stops with an afterStop dispute window and its hold has not released
- **THEN** partial reversal can return held earnings before or after stop up to the remaining held amount
- **AND** no separate released-funds refund command is required or offered

#### Scenario: Two cases hold the same part

- **WHEN** two authorized extends open extensions and one case lifts its own ref
- **THEN** the other extension continues to hold the part subject to its maximum extension
- **AND** retrying an extend with the same key returns the same service-issued ref

### Requirement: Mediation double records party cases and authority holds

The mediation double MUST authenticate file and append as agreement parties, and serve a resumable per-agreement read/watch record signed by the named authority key across all cases. Filing MUST report each part held only after the payment authority accepts its extension, or report not-held, pending or an interface error. Appends MUST be repeatable, actor-attributed and idempotent; closed cases MUST refuse new appends.

#### Scenario: Payout wins the filing race

- **WHEN** the payment authority releases one part before the mediation extension is accepted
- **THEN** the case reports that part not held with its reason, independently of parts successfully held
- **AND** the case record does not claim that released money can be recovered

#### Scenario: A party reconnects after a counterparty filing

- **WHEN** the party reads or watches from its retained per-agreement cursor
- **THEN** it can discover the new case and subsequent signed entries in sequence
- **AND** repeated appends under the same key do not duplicate evidence

#### Scenario: A close precedes an append

- **WHEN** an append reaches a case already closed by the authority
- **THEN** it receives the interface's closed-case refusal rather than a false acknowledgement

### Requirement: Mediation double limits mechanical rulings to acknowledged classes

The mediation double MUST mechanically rule a payee request at least as strong on every part as the standard seller self-penalty, or a payer buyer_end with the storefront's verified acknowledgement bound to that deal and an end at or before the requested time. All other claims MUST enter visible controllable triage. Payment consequences MUST be derived by the authority from the committed form, not trusted from the marketplace caller.

#### Scenario: Seller requests its own standard penalty

- **WHEN** a payee files exceptional_end for failed or undelivered service with a sufficient self-penalty request
- **THEN** the double rules mechanically to end delivery and apply the contract's held-money consequences
- **AND** an insufficient request such as an unentitled bare stop goes to triage instead

#### Scenario: Buyer kept a signed end acknowledgement

- **WHEN** buyer_end includes a valid storefront acknowledgement of the same deal's end at or before the requested time
- **THEN** the double rules mechanically using that acknowledged end
- **AND** a past end is realized as stop-now plus reversal since that end, not a backdated stop

#### Scenario: Acknowledgement is absent or not evidence of this end

- **WHEN** a buyer claim lacks an acknowledgement, has an invalid signature, or carries one for another deal or later end
- **THEN** it goes to triage rather than a mechanical ruling
- **AND** simulated operator notification is visible without sending real external email

### Requirement: Only the mediation authority double applies dispute effects

The mediation double MUST apply ruling effects through authenticated payment HTTP calls as its own authorized account, with stable effect identities and the case reference, then lift only that case's extensions. It MUST record applied state in its signed record and resume incomplete work without duplicate effects. A marketplace dispute adapter MUST only file, append and observe, never apply the ruling itself.

#### Scenario: A ruling is interrupted after one effect

- **WHEN** payments becomes unavailable after one ruling effect commits and before another does
- **THEN** the case remains incompletely applied with stable effect identities
- **AND** resuming retries the pending work without applying the committed effect twice or lifting another case's extension

#### Scenario: An operator rules a triaged discount

- **WHEN** a lane operator control supplies a permissible discount ruling with no delivery end
- **THEN** the authority applies it through the same effect path as a mechanical ruling
- **AND** the running deal is not ended merely because money was partially reversed

### Requirement: Lane authority controls are deterministic and isolated

Doubles MUST offer lane-only routes for deterministic time, exhaustion, stale/equal/regressed or wrong-transaction snapshots, delay/drop/refusal, independent outages, signing-identity rotation and triage/effect progress. Controls MUST be scoped to the owned lane and run, unavailable outside the lane profile, and kept off host ports. They MUST preserve idempotent committed results after response loss and MUST NOT change clients' trust rules.

#### Scenario: An authority response is lost after commit

- **WHEN** a control drops an approval, extension or effect response after the operation commits
- **THEN** the original result remains readable and retrying the same key does not duplicate its effect

#### Scenario: Notice and hold timing is driven without sleeps

- **WHEN** the scenario advances the injected clocks to a pending stop or payout instant
- **THEN** a control barrier reports progress at each authority and the scenario can read the resulting records without wall-clock sleeps
- **AND** no global ordering of the two authorities' records is fabricated

#### Scenario: A signing identity rotates

- **WHEN** a control begins key overlap and later removes the old key
- **THEN** the double exposes the selected contract's key material and signatures
- **AND** the control does not rewrite a committed Agreement's record key or cause clients to trust an unpinned successor

### Requirement: Lane qualification identifies readiness and evidence class

Runs MUST identify the consumer revision, actual authority target kinds, selected contracts and hashes, and classify their evidence as published-contract qualification, proposed-contract qualification or live evidence. A double run MUST never claim live evidence. A required unready authority MUST stop scenario mutation; missing lane-owned settings MUST fail by name. Cleanup MUST remove the owned doubles' state through lane cleanup, and external targets MUST never be silently replaced.

#### Scenario: A mixed-contract run finishes

- **WHEN** published payments and proposed mediation both participate in a scenario
- **THEN** each boundary's contract is reported and the combined result is proposed-contract qualification
- **AND** the result cannot enable live servicing

#### Scenario: A required lane authority is not ready

- **WHEN** the selected scenario's required authority fails readiness
- **THEN** the run reports the exact environment prerequisite before approving a payment or filing a case
- **AND** it does not count the unexercised product assertions as passed

#### Scenario: A lane tears down after failure

- **WHEN** a payment scenario fails after creating authority state
- **THEN** the normal owned-lane cleanup removes that state and retains its report/logs
- **AND** another lane or explicitly configured hosted target is untouched
