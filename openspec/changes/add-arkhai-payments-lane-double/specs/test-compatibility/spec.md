## ADDED Requirements

### Requirement: Lanes use separate runnable authority doubles

Credential-free payment lanes MUST provide HTTP doubles of the payment and dispute boundaries, using the marketplace parties' real clients and separate authority identities, records and availability. Test tooling MUST own both runnable doubles; production kits MUST own their contracts and signing fixtures without importing that tooling. The payment double MUST sign only test-mode records, and fixture authority trust MUST remain lane-only.

#### Scenario: Existing payment scenarios run in a lane

- **WHEN** the bare-metal or API-credit lane runs its existing payment deal with the default lane profile
- **THEN** it reaches the payment double through HTTP rather than skipping for an absent payments target
- **AND** receipt gating, retry and mock delivery observations are attributed to the marketplace boundary, not live ledger or provider behavior

#### Scenario: One authority is unavailable

- **WHEN** a scenario disables payments while mediation is ready, or disables mediation while payments is ready
- **THEN** the other authority remains independently reachable
- **AND** no storefront, adapter or double silently assumes the unavailable authority's identity or powers

### Requirement: Kit contract fakes and runnable doubles have separate consumers

Kits MUST use in-process contract fakes generated from their kit-owned vectors for unit and library-integration tests. A kit and its test environment MUST NOT depend on runnable tooling. HTTP doubles MUST serve lane and system-integration runs. The tooling's own suite MUST verify its timers, holds, mechanical classifier, effect recovery and control isolation against those same contracts.

#### Scenario: A kit runs its ordinary tests

- **WHEN** a kit exercises its lifecycle client without a lane
- **THEN** its injected contract fake uses the same vectors as the runnable double
- **AND** no Compose service or tooling distribution is required

### Requirement: Lane origins and authentication preserve production client checks

Lane profiles MUST explicitly select test-only HTTPS origins, lane CA trust and fixture bearer credentials. Production configuration MUST refuse lane-only settings and fixture identities. Clients MUST retain non-loopback HTTPS, certificate verification and development-auth restrictions. Mediation's authority-side payment calls MUST use tooling-owned HTTP composition over kit-generated models.

#### Scenario: A container calls an authority double

- **WHEN** a lane client uses the explicit lane origin, CA and bearer credential
- **THEN** a real client request reaches the intended fixture account over verified TLS
- **AND** plain HTTP or non-loopback development-account auth remains refused

#### Scenario: Lane settings reach a production profile

- **WHEN** production configuration receives the lane-only origin/auth tuple or fixture authority identity
- **THEN** startup refuses it by name rather than trusting the fixture or relaxing client validation

### Requirement: Authority doubles declare a pinned contract mode

Each double MUST select `published` or `proposed` before scenario mutation. Published mode MUST implement the exact kit-marked publication and vectors. Proposed mode MUST select the same kit-owned candidate bytes as its consumer and label differences. Unsupported operations MUST fail explicitly. Contract metadata MUST be reported without altering signed wire frames, and a missing required publication or frame vector MUST preclude a published qualification claim for that surface.

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

### Requirement: Payment double applies the selected stopper's partial-period terms

For a supporting revision, stop entries MUST carry partialPeriod charged, returned or prorated, corresponding to SCM started_period, last_boundary or stop. The double MUST compute billing without a storefront correction and refuse unexpressible terms. A revision lacking partialPeriod MUST retain its charged stop semantics. Exhaustion and part end MUST use charged, and maximum terms MUST round down to whole periods. Each party MUST have one notice, from notice_seconds.

#### Scenario: Stopper terms differ

- **WHEN** the selected revision supports returned for a payee stop and charged for a payer stop
- **THEN** the double computes each stop's billing from that authority's terms
- **AND** no caller sends a compensating started-period refund

#### Scenario: Setup delivery activates

- **WHEN** a setup once part's delivery activates
- **THEN** its end is activation and payout is one dispute window later
- **AND** the standard self-penalty returns all setup payment for undelivered service and none after delivery

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

#### Scenario: An agreement has no cases yet

- **WHEN** an authorized party reads or watches a known agreement with no cases
- **THEN** the double returns a signed empty record at cursor zero and watch can discover later entries
- **AND** an unknown agreement or unauthorized party receives the selected contract's refusal, not a fabricated empty record

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

Doubles MUST offer versioned typed lane controls for exhaustion, snapshot faults, delay/drop/refusal, independent outages, key rotation and triage/effect progress. Controls MUST require an owned run and explicit nonempty targets, refuse unknown scope or versions without mutation, stay off host ports and be unavailable outside lane profiles. Reset MUST name only its owned run. Lost responses MUST preserve idempotent results. Controls MUST NOT change client trust.

#### Scenario: An authority response is lost after commit

- **WHEN** a control drops an approval, extension or effect response after the operation commits
- **THEN** the original result remains readable and retrying the same key does not duplicate its effect

#### Scenario: Notice and hold work becomes due

- **WHEN** a lane scenario reaches a pending stop or payout using short real-time terms
- **THEN** a typed due-work barrier drains work due at its captured instant and reports per-authority watermarks, pending effects and blocked dependencies
- **AND** a blocked effect is not complete and no global ordering of records is fabricated
- **AND** deterministic clock advancement is confined to isolated tooling tests, not lane authorities ahead of their consumers

#### Scenario: A control omits its target scope

- **WHEN** a mutation omits targets, supplies an empty target set or names an unknown run, transaction or case
- **THEN** it refuses without creating scope or mutating another run
- **AND** status before mode selection reports not ready

#### Scenario: A signing identity rotates

- **WHEN** a control begins key overlap and later removes the old key
- **THEN** the double exposes the selected contract's key material and signatures
- **AND** the control does not rewrite a committed Agreement's record key or cause clients to trust an unpinned successor

### Requirement: Lane qualification identifies readiness and evidence class

Lane runs MUST obey External payment qualification names its target and report authority kinds, modes and hashes. Their evidence MUST be published-contract qualification only if every exercised surface matches published bytes/vectors; any proposed surface MUST make the aggregate proposed-contract qualification. Live evidence MUST require an explicitly configured ready hosted target, never a double. Cleanup MUST remove only owned state; external targets MUST NOT be replaced.

#### Scenario: A mixed-contract run finishes

- **WHEN** published payments and proposed mediation both participate in a scenario
- **THEN** each boundary's contract is reported and the combined result is proposed-contract qualification
- **AND** the result cannot enable live servicing

#### Scenario: A cached double has a different published contract

- **WHEN** published-mode readiness finds a schema or vector hash different from a required consumer's kit SOURCE hashes
- **THEN** setup fails naming the mismatch before any scenario mutation
- **AND** an unavailable producer vector precludes a published qualification claim

#### Scenario: A required lane authority is not ready

- **WHEN** the selected scenario's required authority fails readiness
- **THEN** the run reports the exact environment prerequisite before approving a payment or filing a case
- **AND** it does not count the unexercised product assertions as passed

#### Scenario: A lane tears down after failure

- **WHEN** a payment scenario fails after creating authority state
- **THEN** the normal owned-lane cleanup removes that state and retains its report/logs
- **AND** another lane or explicitly configured hosted target is untouched

## MODIFIED Requirements

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target, the bare-metal lane MUST qualify a fixed-term whole-host arkhai.payments.v1 purchase: discovery, negotiation, approval, receipt-gated mock delivery, original-run re-drive, separate refund and teardown. It MUST apply Lane qualification identifies readiness and evidence class. Mock access MUST NOT claim real access or revocation. Cleanup MUST run on pass or failure. An absent or unready target MUST report a named prerequisite, never count as qualification or fall back.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** three ordered calls discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, re-drives
  the same negotiation through `SyncStorefrontClient.settle_agreement`, and requires
  the original transaction, fulfillment identity, and durable result
- **AND** the pinned seller refunds the held payment and the buyer separately
  requests physical teardown, converging mock reclaim and selected-site capacity release
- **AND** a double target reports its published-contract or proposed-contract qualification class, never live evidence

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup refunds the deal's payment if it is not already refunded,
  then reads the deal's fulfillment and tears down a host it finds not yet torn down,
  reading the deal's identifiers from the original run when the purchase command failed
- **AND** a host delivered while the refund was being requested is found and torn down,
  and one whose fulfillment cannot be read or torn down is reported as a failed step
- **AND** a refund the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  refund that still fails fails the scenario naming the negotiation and transaction
  and any host its seller may still deliver for it
- **AND** no allocated host, mock rule, payment hold or held loop is left except the
  explicitly reported unrecoverable payment or failed host cleanup
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal payment scenario runs with no payments target configured, or an unready one
- **THEN** it reports a named blocked prerequisite and makes no purchase
