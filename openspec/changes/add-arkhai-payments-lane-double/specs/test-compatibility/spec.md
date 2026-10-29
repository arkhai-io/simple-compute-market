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

Kits MUST use in-process contract fakes and kit-owned vectors for unit and library-integration tests. The payment fake and HTTP double MUST share one clock-injected payments authority engine in payments-kit fixtures. Kits MUST NOT depend on tooling. HTTP doubles MUST serve lane/system-integration runs; their own suites MUST verify timers, holds, triage/operator rulings, effect recovery and controls.

#### Scenario: A kit runs its ordinary tests

- **WHEN** a kit exercises its lifecycle client without a lane
- **THEN** its injected contract fake uses the same vectors as the runnable double, and the payments fake uses the shared kit engine directly
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

### Requirement: Authority contract resources work from installed artifacts

Doubles MUST consume the owning kits' installed resource/model API for the selected schema, vectors, publication status and hashes, without sibling checkouts. Packaged resources and generated metadata MUST derive from one canonical source. Readiness MUST compare the selected hashes with required consumers in both modes before mutation.

#### Scenario: A source-free image selects a contract

- **WHEN** the tool and consumer kits are installed from built wheels without source trees
- **THEN** both select identical contract bytes/models and report identical publication/hash metadata
- **AND** absent resources or mismatched hashes fail setup by name

### Requirement: Payment double models per-part lifecycle and held-money correction

The target payment double MUST model per-part authorities, payee-only rate start, notice-bearing pending stops, term/exhaustion stops, afterStop holds, repeatable partial reversal of held money and independently referenced hold extensions. Its behavior MUST follow the selected contract. It MUST NOT invent backdated stops, minimum-spend primitives or released-funds refund routes.

#### Scenario: Seller notice survives a storefront outage

- **WHEN** an entitled seller schedules a rate-part stop and then its storefront becomes unavailable
- **THEN** the payment double retains the pending stop and applies it no earlier than the sender's notice allows without another storefront call
- **AND** the earliest pending stop wins and cannot be withdrawn

#### Scenario: Seller entries express entitlements only

- **WHEN** a seller requests a payment stop
- **THEN** the double requires an entitlement entry, such as spot's notice entry, and refuses a stop without authorization regardless of asserted favour
- **AND** no seller restitution entry or several-stop-entries-per-account dependency is added; spot emergency exit is an exceptional_end dispute filing

#### Scenario: On-demand non-preemption is remedy-enforced

- **WHEN** an on-demand seller preempts delivery
- **THEN** the buyer's remedy is the premature-stop penalty and a case over held money, not a mandate prohibition
- **AND** the seller's own exit is exceptional_end, the qualifying mechanically ruled self-penalty, always returned on-demand

#### Scenario: A stopped part still holds reversible earnings

- **WHEN** a part stops with an afterStop dispute window and its hold has not released
- **THEN** partial reversal can return held earnings before or after stop up to the remaining held amount
- **AND** no separate released-funds refund command is required or offered

#### Scenario: Two cases hold the same part

- **WHEN** two authorized extends open extensions and one case lifts its own ref
- **THEN** the other extension continues to hold the part subject to its maximum extension
- **AND** retrying an extend with the same key returns the same service-issued ref

### Requirement: Payment double applies the selected stopper's partial-period terms

The double MUST implement its selected contract's notice, partialPeriod, earning and hold semantics, refusing unsupported terms without correction. When expressible, it MUST support end.partialPeriod without rounding, chosen dispute stops with explicit treatment, period-end/stop earning and {for} holds from earning. Setup ends MUST use the contract's immutable anchor, not compute observations.

#### Scenario: A revision lacks partialPeriod

- **WHEN** the selected contract cannot encode returned/prorated
- **THEN** the double refuses those inputs and retains its publication's actual supported stop/earning semantics
- **AND** it does not implement offer disclosure or buyer acceptance policy

#### Scenario: Stopper terms differ

- **WHEN** the selected revision supports returned for a payee stop and charged for a payer stop
- **THEN** the double computes each stop's billing from that authority's terms
- **AND** no caller sends a compensating started-period refund

#### Scenario: The contract represents setup maturity

- **WHEN** the selected contract defines an immutable activation anchor and receives its specified authority event
- **THEN** the double ends the setup once part at that anchor and releases only after its dispute window
- **AND** a contract without that representation refuses unsupported setup inputs

#### Scenario: Buyer stops while payments is unavailable

- **WHEN** the buyer half cannot reach payments before sending end_delivery without at
- **THEN** it journals its payment stop and retries under the same key; billing runs until the stop lands under its notice and partialPeriod
- **AND** the storefront signs its receipt time as evidence but has no authority to stop buyer billing
- **AND** the buyer may additionally file buyer_end with signed request and receipt, remaining in triage

#### Scenario: No implicit waiver or early release exists

- **WHEN** a caller requests a payee notice waiver or payer early release outside the selected contract's authorizations
- **THEN** the double refuses it rather than adding such an operation or inferring permission from whose interest it serves

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

### Requirement: Mediation mechanically rules only qualifying seller self-penalties

The double MUST expose exceptional_end and its pinned mapping. Only payee requests at least as strong as standard self-penalty MAY be mechanically ruled. Other claims, including buyer_end, MUST enter visible triage with an operator outbox. Stop rulings MUST state partialPeriod. Effects MUST derive from the exact case Agreement verified against the mandate deal hash, not an attachment or trusted caller-computed remedies.

#### Scenario: Buyer kept a signed end acknowledgement

- **WHEN** buyer_end includes a storefront acknowledgement at filing or in a seller append
- **THEN** the case remains in visible triage for a person to rule
- **AND** the acknowledgement is evidence, not an automatic ruling input

#### Scenario: Operator realizes a buyer end

- **WHEN** an operator rules buyer_end for a past requested end
- **THEN** the remedy realizes the payer's own stop at that instant, including payer notice and committed partialPeriod, leaving once parts untouched
- **AND** it uses a present stop plus the net held-money adjustment, never a backdated stop or a way to bypass priced notice
- **AND** a stop ruling omitting partialPeriod refuses before applying effects

#### Scenario: Seller files the standard exceptional end

- **WHEN** the seller half journals exceptional_end(at) with the end and files through the Agreement's dispute adapter and authority
- **THEN** the seller sends no stop or reverse of its own and the qualifying payee self-penalty is mechanically ruled through mediation's own `{account, notice: PT0S, partialPeriod: chosen}` stop entry
- **AND** it stops rate parts now returned, always returned for on-demand, reverses earnings since at and reverses unserved once share by time
- **AND** setup's term ends at activation so all is reversed if undelivered and none once delivered
- **AND** then min(premature_stop_penalty, earned amounts still held) is reversed to payer across parts in mandate order; bond award stays reserved for hosted bonds
- **AND** the authority records the dispute and owns the whole remedy, with no seller exceptional-end direct effects to reconcile

#### Scenario: Seller penalties distinguish entitled notice from emergency

- **WHEN** a spot seller uses its entitled notice and a separate seller ends without that notice
- **THEN** the entitled stop pays no penalty and the emergency self-penalty pays the configured amount capped by earned amounts still held after refunds
- **AND** a buyer case alleging an unentitled seller end goes to a person applying that same cap

#### Scenario: A request does not qualify for mechanical self-penalty

- **WHEN** the filer is not the payee or its request is weaker than standard self-penalty
- **THEN** the double does not mechanically grant the self-penalty and leaves nonqualifying claims in triage
- **AND** no buyer_end request is mechanically ruled, with or without a signed acknowledgement

#### Scenario: A seller fails before Agreement start

- **WHEN** the seller's end precedes Agreement start
- **THEN** it journals immediately and files exceptional_end at Agreement start
- **AND** future-dated exceptional_end requests refuse

#### Scenario: A case supplies its own Agreement

- **WHEN** a case carries the exact Agreement and no attachment is stored
- **THEN** the authority verifies its hash against the committed mandate before deriving dispute effects
- **AND** a mismatching Agreement is refused

### Requirement: Only the mediation authority double applies dispute effects

The mediation double MUST apply ruling effects through authenticated payment HTTP calls as its own authorized account, with stable effect identities and the case reference, then lift only that case's extensions. It MUST record applied state in its signed record and resume incomplete work without duplicate effects. A marketplace dispute adapter MUST only file, append and observe, never apply the ruling itself.

#### Scenario: A ruling is interrupted after one effect

- **WHEN** payments becomes unavailable after one ruling effect commits and before another does
- **THEN** the case remains incompletely applied with stable effect identities
- **AND** resuming retries the pending work without applying the committed effect twice or lifting another case's extension

#### Scenario: An operator rules a triaged discount

- **WHEN** a lane operator control supplies a permissible discount ruling with no delivery end
- **THEN** the authority applies it through the single authenticated ruling-effect path
- **AND** the running deal is not ended merely because money was partially reversed

### Requirement: Mediation nets revised remedies across an agreement

The double MUST use the pinned mapping to net confirmed remedies per part across revised exceptional_end and operator cases. It MUST serialize application per agreement, resolve uncertain effects before computing the remainder, apply only additional amounts and preserve case/effect provenance. Missing mapping or vectors MUST leave revised remedies in explicit repair/triage, not report completion.

#### Scenario: Earlier evidence follows a prior remedy

- **WHEN** a prior remedy returned 40 and earlier evidence establishes a total remedy of 60
- **THEN** the revised case applies only 20 more with references to the prior cases and effects
- **AND** this holds during partial/uncertain application, after closure and across append/close races

### Requirement: Lane authority controls are deterministic and isolated

Doubles MUST offer versioned typed lane controls for funding/exhaustion, snapshot faults (including labelled livemode corruption), delay/drop/refusal, outages, key rotation and triage/effect progress. Controls MUST require an owned run and explicit nonempty targets, refuse unknown scope/versions without mutation, stay off host ports and be unavailable outside lane profiles. Reset MUST name only its owned run. Lost responses MUST preserve idempotent results. Controls MUST NOT change client trust.

#### Scenario: An authority response is lost after commit

- **WHEN** a control drops an approval, extension or effect response after the operation commits
- **THEN** the original result remains readable and retrying the same key does not duplicate its effect

#### Scenario: Notice and hold work becomes due

- **WHEN** a lane scenario reaches a pending stop or payout using short real-time terms
- **THEN** authorities process due work on reads/writes and an internal wall-time scheduler without needing a barrier
- **AND** a typed barrier forces due work and reports current instants, per-authority watermarks, pending effects and blocked dependencies; status also reports each authority's current instant
- **AND** a blocked effect is not complete and no global ordering of records is fabricated
- **AND** deterministic clock advancement is confined to isolated tooling tests, not lane authorities ahead of their consumers

#### Scenario: A control omits its target scope

- **WHEN** a mutation omits targets, supplies an empty target set or names an unknown run, transaction or case
- **THEN** it refuses without creating scope or mutating another run
- **AND** status before mode selection reports not ready

#### Scenario: Payer funding rescues a transaction

- **WHEN** a scoped funding control tops up the payer before verified exhaustion
- **THEN** the selected contract engine updates reservations and funded-through in signed observations
- **AND** the control neither ends another transaction nor claims an unconfirmed exhaustion

#### Scenario: A livemode fault is injected

- **WHEN** a scoped record-corruption control emits a signed livemode:true frame
- **THEN** the report identifies that injected fault and normal double records remain livemode:false
- **AND** the fault cannot make readiness or qualification claim live evidence

#### Scenario: A signing identity rotates

- **WHEN** a control begins key overlap and later removes the old key
- **THEN** payments retains old receipt bytes inside current-key signed snapshots with the selected contract's re-anchoring attestation during overlap
- **AND** missing attestation vectors keep that scenario proposed-only
- **AND** the control does not rewrite a committed Agreement's record key or cause clients to trust an unpinned successor

### Requirement: Lane qualification identifies readiness and evidence class

Lane runs MUST obey "External payment qualification names its target" and report authority kinds, modes and hashes. Published qualification MUST require all committed and exercised surfaces to match publications/vectors; any proposed surface, including a named draft dispute interface, MUST make the run proposed. Only an explicitly configured ready hosted target can yield live evidence. Cleanup MUST remove only owned state; external targets MUST NOT be replaced.

#### Scenario: A mixed-contract run finishes

- **WHEN** published payments and proposed mediation both participate in a scenario
- **THEN** each boundary's contract is reported and the combined result is proposed-contract qualification
- **AND** the result cannot enable live servicing

#### Scenario: A cached double has a different selected contract

- **WHEN** published- or proposed-mode readiness finds a schema or vector hash different from a required consumer's installed kit metadata
- **THEN** setup fails naming the mismatch before any scenario mutation
- **AND** an unavailable producer vector precludes a published qualification claim

#### Scenario: A required lane authority is not ready

- **WHEN** a required lane-owned authority is absent or fails readiness
- **THEN** setup fails naming the exact prerequisite before approving a payment or filing a case; it does not skip or report a blocked prerequisite
- **AND** it does not count the unexercised product assertions as passed

#### Scenario: A lane tears down after failure

- **WHEN** a payment scenario fails after creating authority state
- **THEN** the normal owned-lane cleanup removes that state and retains its report/logs
- **AND** another lane or explicitly configured hosted target is untouched

## MODIFIED Requirements

### Requirement: A configured bare-metal payment purchase is qualified end to end

The bare-metal lane MUST qualify discovery, negotiation, approval, commit, receipt-gated mock delivery, original-run buyer-half re-drive, seller reverse and buyer end_delivery for a fixed-term whole-host arkhai.payments.v1 purchase. It MUST apply "Lane qualification identifies readiness and evidence class". Mock access MUST NOT claim real access/revocation. Cleanup MUST run on pass/failure. Missing/unready lane targets MUST fail setup; unavailable external targets MUST report blocked.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with ready configured required authorities
- **THEN** three ordered calls discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  then commit and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, re-drives
  the same negotiation through the buyer half's commit path, and requires
  the original transaction, fulfillment identity, and durable result
- **AND** the pinned seller reverses the held payment and the buyer separately
  sends end_delivery without a buyer-supplied time, converging mock reclaim and selected-site capacity release
- **AND** a double target reports its published-contract or proposed-contract qualification class, never live evidence

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup reverses the held payment if it is not already reversed,
  then reads the deal's fulfillment and sends end_delivery for a host not yet torn down,
  reading the deal's identifiers from the original run when the purchase command failed
- **AND** a host delivered while the reversal was being requested is found and ended,
  and one whose fulfillment cannot be read or torn down is reported as a failed step
- **AND** a reversal the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  reversal that still fails fails the scenario naming the negotiation and transaction
  and any host its seller may still deliver for it
- **AND** no allocated host, mock rule, payment hold or held loop is left except the
  explicitly reported unrecoverable payment or failed host cleanup
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal scenario explicitly selects an external target that is absent or unready
- **THEN** it reports a named blocked prerequisite, makes no purchase and does not fall back to a double

#### Scenario: The required lane target is unavailable

- **WHEN** the default lane target is absent or unready
- **THEN** setup fails naming the target before purchase mutation, rather than reporting blocked or skipped
