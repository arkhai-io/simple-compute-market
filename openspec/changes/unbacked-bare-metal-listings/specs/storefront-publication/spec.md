## ADDED Requirements

### Requirement: Bare-metal publication derives unbacked listings

Bare-metal publication MUST derive a listing from every enabled Physical Resource
that enables bare-metal publication in an enabled pool advertising `bare_metal`,
whatever the pool's backing, and bind it with the backing its pool declares. An
unbacked candidate MUST come from the site's bare-metal view of the resource, MUST
NOT be judged against availability, and MUST follow the region, asking-rate,
override, and shape rules every bare-metal candidate follows. An unbacked
bare-metal listing MUST never be reserved, held, scheduled, or fulfilled. No consumer
MAY compare the backing label to make a backing decision; each is asked of the
delegate the binding carries.

#### Scenario: An unbacked pool advertises bare metal

- **WHEN** a pool advertising `bare_metal` declares itself unbacked, and one of its
  enabled Physical Resources enables bare-metal publication with no host named
- **THEN** bare-metal publication derives a listing for that resource and publishes it
  with `capacity_backing: unbacked`

#### Scenario: A resource in an unbacked pool does not opt in

- **WHEN** a Physical Resource in an unbacked pool advertising `bare_metal` does not
  enable bare-metal publication
- **THEN** no bare-metal listing is derived from it

#### Scenario: An unbacked resource's capacity is consumed

- **WHEN** availability for an unbacked resource's capacity reads as consumed
- **THEN** its listing stays open, because an unbacked listing is not judged against
  availability

#### Scenario: An unbacked bare-metal listing is accepted

- **WHEN** a negotiation against an unbacked bare-metal listing is accepted
- **THEN** no capacity is reserved and the deal settles by introduction, revealing the
  contact of the listing's origin seller

### Requirement: A bare-metal listing carries delivery terms only when backed

A bare-metal listing's delivery terms — its host identity, physical host identity,
and access methods, and on its site view its availability — MUST be present and
non-empty when the listing is capacity-backed and absent when it is unbacked, as its
backing delegate decides. No delivery term MAY be given a default value. The site's
bare-metal view carries no backing label: the storefront MUST validate each view's
delivery terms against the backing its containing pool declares, through that
backing's delegate, and MUST treat a view whose terms the delegate refuses as a
malformed view, refusing the site's generation as it refuses any malformed view. A
pool whose declarations do not resolve is held, and its views' terms are not judged.
The storefront MUST report each resource the site projects with a
`publication_view_problems` entry for the bare-metal view as a
`publication_view_unbuildable` report in that site's derivation.

#### Scenario: An unbacked declaration names a host

- **WHEN** a Physical Resource in an unbacked pool names a host and declares access
  methods
- **THEN** its listing publishes neither the host identity nor the access methods

#### Scenario: A backed view omits a delivery term

- **WHEN** a site's generation carries a bare-metal view in a capacity-backed pool with
  no host identity or no access methods
- **THEN** the storefront refuses that generation as malformed, and the site's listings
  are held as `site_projection_refused`

#### Scenario: An unbacked view carries a delivery term

- **WHEN** a site's generation carries a bare-metal view in an unbacked pool that names a
  host
- **THEN** the storefront refuses that generation as malformed, and the site's listings
  are held as `site_projection_refused`

#### Scenario: The site cannot build a resource's view

- **WHEN** a site projects a resource with a `publication_view_problems` entry for the
  bare-metal view
- **THEN** no listing is derived from it, and the site's derivation reports
  `publication_view_unbuildable` with the problem

### Requirement: A compute candidate with no settlement option yields no listing

VM and bare-metal publication MUST refuse a candidate, whatever its backing, whose
payload carries no settlement option and no accepted escrow, through a typed refusal
recorded with the candidate's site, pool, and source resource. When the candidate's
listing is open, the refusal's readiness blockers MUST decide what becomes of it: when
any mechanism is ruled out by a configuration blocker, or no clause is configured, the
listing MUST be closed through reconciliation as `no_settlement_option` and MUST reopen
under the same identity on the first cycle whose payload builds again; when every
mechanism is ruled out only by reachability blockers, the listing MUST be held, keeping
its last-published terms. A payload failure other than this refusal MUST leave an open
listing as it is.

#### Scenario: An unbacked candidate's origin has no contact

- **WHEN** an unbacked candidate's only admissible mechanism is contact exchange and its
  origin site has no configured contact
- **THEN** no listing is derived, and the site's derivation records a refusal naming the
  candidate's pool and resource

#### Scenario: An open listing loses its last option to configuration

- **WHEN** an open bare-metal listing's only configured mechanism becomes unready for a
  configuration blocker
- **THEN** the listing is closed as `no_settlement_option`, and it reopens under the same
  listing identity once a cycle builds its payload again

#### Scenario: An open listing's mechanism is unreachable

- **WHEN** an open VM listing's only mechanism is unready because its chain cannot be
  reached
- **THEN** the listing stays open on its last-published terms and the site's derivation
  records a hold

#### Scenario: A payload fails for another reason

- **WHEN** building an open listing's payload raises an error that is not the
  no-settlement-option refusal
- **THEN** the failure is reported and the listing is left as it is

### Requirement: A deal settled by introduction has no settlement or fulfillment

A seller stage whose mechanism completes outside settlement and fulfillment MUST
declare that it has no settle, delivery, or refund operation, in every compute
domain. Settle and fulfillment requests MUST be answered from the stage the deal's
accepted Agreement selected, through one shared refusal, and MUST NOT compare a
mechanism identifier or the listing's backing: a settle request MUST be refused with
409, and a fulfillment status, access, or result read or a teardown MUST be refused
with 404, each naming that the deal settled by introduction. A fulfillment route MUST
check the caller's ownership against the accepted negotiation before resolving the
stage, and MUST resolve the stage before loading a fulfillment context or building the
fulfillment service. A stage without delivery MUST NOT record settlement evidence.

#### Scenario: A buyer asks for an introduction deal's fulfillment

- **WHEN** a buyer requests fulfillment status, access, result, or teardown for a
  bare-metal deal settled by introduction
- **THEN** the storefront answers 404, naming that the deal has no fulfillment

#### Scenario: A buyer settles an introduction deal

- **WHEN** a buyer submits a settle request for a VM or bare-metal deal settled by
  introduction
- **THEN** the storefront answers 409, naming that a contact exchange completes by
  introduction, not settlement

#### Scenario: Another buyer asks about an introduction deal

- **WHEN** a principal other than the deal's buyer requests its fulfillment status
- **THEN** the storefront refuses it as it refuses any other buyer's request, without
  revealing the deal's mechanism

#### Scenario: An unbacked introduction deal's fulfillment is requested

- **WHEN** a buyer requests fulfillment status for a deal accepted on an unbacked
  bare-metal listing, whose binding names no host
- **THEN** the storefront answers 404 without loading a fulfillment context

#### Scenario: An introduction is revealed

- **WHEN** a bare-metal introduction is revealed
- **THEN** the storefront records no settlement evidence for it

### Requirement: A compute storefront reports and logs its site derivation

The VM and bare-metal storefronts MUST keep each configured site's publication
derivation — every hold, refusal, and report a publication cycle made, each a reason
code with its pool or Physical Resource and any detail — in one kit-owned site
derivation log. Only a real publication cycle MUST record it; a preview, a
listing-source check, and capacity-event reconciliation MUST NOT. Each storefront's
system status MUST report `publication_derivation` from it, per site, as `holds`,
`refusals`, and `reports`, a site that derived cleanly present with empty lists. The
log MUST record each entry as a warning when it first appears in a site's derivation
and at info when it clears, and MUST NOT log a standing entry again or log a preview.

#### Scenario: A pool states no region for many cycles

- **WHEN** a bare-metal pool states no region across several publication cycles
- **THEN** its hold is logged once when it first appears, and status reports it in every
  cycle until it clears

#### Scenario: A held pool recovers

- **WHEN** a pool held for a missing region states one
- **THEN** the next cycle logs the hold's clearing at info and status no longer reports it

#### Scenario: A preview runs

- **WHEN** an administrator previews a publication cycle
- **THEN** the site derivation and its log are unchanged

#### Scenario: VM and bare metal report alike

- **WHEN** an administrator reads the system status of a VM and of a bare-metal storefront
  each with a pool that states no region
- **THEN** both report it under the site's `holds` with the reason `pool_region_missing`

## MODIFIED Requirements

### Requirement: A bare-metal listing sells one whole unit

A capacity-backed bare-metal listing MUST be held by exclusive allocation of one unit
of its Physical Resource. Its capacity claim MUST request exactly one `units` and MUST
carry its shape's attributes, so that admission matches the published attributes. Its
shape's quantities describe what that unit contains, and MUST NOT be requested
dimension by dimension. An unbacked bare-metal listing constructs no capacity claim.

The claimed attributes MUST come from the storefront's trusted record of the accepted
listing, never from buyer input.

#### Scenario: A declaration changes model after acceptance

- **WHEN** a buyer accepts a capacity-backed bare-metal listing published with
  `gpu_model: H200`, and its Physical Resource's declaration is changed to another model
  before reservation
- **THEN** the site refuses the reservation

#### Scenario: An unbacked listing is accepted

- **WHEN** a buyer accepts an unbacked bare-metal listing
- **THEN** no capacity claim is constructed

### Requirement: Bare-metal opening rechecks its listing against its source

Whenever a bare-metal storefront rechecks a listing against its source, it MUST re-derive
the listing's shape and region from the resource-pool projection it holds for the
listing's own site, at its bound pool and Physical Resource, after accepting that
generation's bare-metal views as publication accepts them, and MUST NOT fetch that
projection from the site to do so. It MUST refuse with a declared-match reason when any of
these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent, disabled, or no longer projected under its bound pool.

For a capacity-backed listing it MUST refuse with the availability reason when the held
projection's bare-metal view shows the Physical Resource unavailable; an unbacked listing
is never refused for availability. It MUST refuse as retryable, for either backing, when
the projection it holds for the site has no value, is not freshly confirmed, or has a
generation whose bare-metal views are refused, or when no site authority is configured. A
generation is freshly confirmed when its most recent poll succeeded within the storefront's
source-confirmation window, so the availability and declarations a recheck relies on lag
the site by at most that window; admission at the site remains authoritative.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The Physical Resource is taken

- **WHEN** a buyer opens a negotiation on a capacity-backed bare-metal listing whose
  Physical Resource is reserved by another deal, as the held projection shows
- **THEN** the opening is refused with the availability reason

#### Scenario: An unbacked listing's resource reads as unavailable

- **WHEN** a buyer opens a negotiation on an unbacked bare-metal listing whose resource's
  capacity reads as consumed
- **THEN** the opening is not refused for availability

#### Scenario: An unbacked listing's resource moves to another pool

- **WHEN** a buyer opens a negotiation on an unbacked bare-metal listing whose Physical
  Resource the held projection now places in a pool other than its bound pool
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The site's projection is not held

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's projection the
  storefront does not hold
- **THEN** the opening is refused as retryable, and the site is not called

#### Scenario: The held generation is stale

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's most recent
  projection poll failed, so the storefront holds only an earlier generation
- **THEN** the opening is refused as retryable, and the earlier generation confirms nothing

#### Scenario: The held generation's confirmation has expired

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's generation is still
  `loaded` but was last confirmed longer ago than the source-confirmation window, because no
  poll has run since
- **THEN** the opening is refused as retryable, until a poll confirms the site again

#### Scenario: The held generation is refused

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's held generation
  carries a bare-metal view naming a different pool than its container
- **THEN** the opening is refused as retryable

### Requirement: Complete bare-metal seller lifecycle
A bare-metal storefront MUST validate listing, negotiation-message, agreed-terms, settlement materialization, receipt, and access-result artifacts through its installed domain contract. The listing binding MUST freeze the trusted `site_id`, Physical Resource identity, `bare_metal` offering mode, and contract identity/version; the accepted negotiation MUST copy that binding before persisting domain artifacts. Settlement and fulfillment MUST reload that binding and MUST NOT infer a site, executor, URL, credential, or domain from buyer payload data. Alkahest fulfillment MUST start when settlement verifies the escrow, through the kit settlement-servicing worker's ready hook, which the storefront composes whenever it has a settlement configuration, and MUST NOT wait for a buyer request to begin it or be retried by any other path. Arkhai payments MUST retain receipt-verified delivery and receipt-based reconciliation without creating conditional-escrow obligations. The storefront MUST refuse to start without its settlement configuration, and MUST build a configured mechanism's recovery resources whether or not the mechanism is enabled, wherever its configuration supplies them; a configured mechanism whose section parses but which cannot settle is unready rather than a reason to refuse startup. An Alkahest fulfillment MUST publish on chain only its evidence's digest, and MUST NOT submit evidence again once a submission's outcome is unknown.

#### Scenario: Administrator waits while settlement servicing is held
- **WHEN** an accepted bare-metal deal has begun fulfillment and its selected site converges it to active while the storefront's settlement-servicing loop is held
- **THEN** the administrator's settlement wait refreshes that fulfillment through the accepted thread's buyer principal and durable site binding, reports ready, and records its buyer-safe delivery
- **AND** observing the transition to active wakes only the obligation adopted for that escrow, so its next servicing pass can publish evidence without waiting for the pending-fulfillment retry deadline; repeated ready reads do not wake it again
- **AND** the wait starts no fulfillment, creates no reservation, and publishes no settlement evidence

#### Scenario: Buyer accepts a bare-metal listing
- **WHEN** authenticated negotiation accepts valid terms for a trusted listing
- **THEN** the thread records the canonical buyer and seller principals and the exact listing/site/domain binding, and it is recorded as successful only after its agreement payloads and settlement plan are recorded
- **AND** no capacity is reserved or held until settlement starts fulfillment

#### Scenario: An opening leaves its escrow contract unpinned
- **WHEN** a buyer opens, or an administrator previews an opening, with an escrow proposal naming no escrow contract (no address, or the zero address)
- **THEN** the seller refuses the opening, naming the unpinned contract, and the preview reports that refusal
- **AND** a proposal naming a contract the listing does not accept is refused

#### Scenario: Acceptance is interrupted
- **WHEN** the storefront stops after an acceptance began but before the thread was recorded as successful
- **THEN** the thread is never settled, and it cannot be countered, accepted, or force-accepted again; the negotiation watchdog abandons it

#### Scenario: Settlement verifies the accepted plan
- **WHEN** a buyer settles an accepted bare-metal agreement
- **THEN** the storefront verifies and registers the settlement plan committed at acceptance, which the buyer funded, never a plan rebuilt from current configuration

#### Scenario: Accepted bare-metal agreement is fulfilled
- **WHEN** settlement verifies the escrow
- **THEN** the storefront wakes the settlement-servicing worker for that obligation, whose ready hook resolves its continuation from the seller entry the accepted Agreement selected and reaches the bare-metal fulfillment, which reserves at the recorded site, commits the reservation with the agreed lease window, schedules the accepted Physical Resource, invokes the recorded bare-metal executor, and persists its reservation, settlement-resource, fulfillment, receipt, and result correlations
- **AND** the commit begins the lease with the window the site records, which the materialization and the delivered evidence state, and provisioning records the lease's target when the fulfillment becomes active, so lease expiry and termination find it

#### Scenario: Fulfillment start is interrupted
- **WHEN** settlement was verified but fulfillment did not start
- **THEN** the settlement-servicing worker's next cycle for that obligation starts it, without a second reservation or a buyer request

#### Scenario: An Alkahest fulfillment is evidenced and collected
- **WHEN** an Alkahest fulfillment's lease becomes active
- **THEN** the storefront stores the lease-ready evidence, bound to the accepted thread, the committed plan, and the escrow, and submits its digest on chain as a string obligation referencing the escrow, never its body
- **AND** it binds the attestation as the obligation's fulfillment, after which the worker checks the condition and collects the escrow

#### Scenario: An evidence submission's outcome is unknown
- **WHEN** an Alkahest evidence submission may have reached the chain but its attestation was not recorded
- **THEN** no later attempt submits again; the obligation waits for an operator with a reason, and the administrator's system status counts it

#### Scenario: The chain refuses an evidence submission
- **WHEN** the chain rejects an Alkahest evidence submission
- **THEN** the storefront retries it with backoff, and after a bounded number of rejections the obligation waits for an operator with a reason, which the administrator's system status counts

#### Scenario: Evidence is resolved
- **WHEN** a caller requests lease-ready evidence by its digest
- **THEN** the storefront serves it only on a signed request from a principal the evidence names as buyer or claimant, the seller's administrator
- **AND** the buyer's fulfillment status names the evidence digest once the evidence is stored, and the attestation that published it only once settlement has recorded the chain's acceptance of the submission, so a stored digest awaiting a retry never reads as published

#### Scenario: A settlement ends uncollected after delivery started
- **WHEN** an Alkahest obligation reaches a terminal state other than collected after its fulfillment started
- **THEN** the storefront terminates the lease at the recorded site

#### Scenario: The storefront starts without its settlement configuration
- **WHEN** the bare-metal storefront starts with no settlement configuration
- **THEN** startup refuses with a clear error, and no mechanism is enabled implicitly

#### Scenario: A configured Alkahest section cannot settle
- **WHEN** the bare-metal storefront starts with a configured Alkahest section, enabled or not, that lacks its seller address, chains, or wallet key
- **THEN** the storefront starts, Alkahest is reported unready with a configuration blocker naming what is missing, and its other mechanisms continue

#### Scenario: Buyer supplies conflicting routing material
- **WHEN** a request or domain artifact asserts a provisioning URL, credential, different site, Physical Resource, machine, or physical-host identity
- **THEN** the storefront rejects the conflict before a state-changing authority call

#### Scenario: Storefront restarts during fulfillment
- **WHEN** a process restarts after reservation, scheduling, begin, result, or teardown acknowledgement
- **THEN** it reloads the same immutable binding and durable lifecycle references rather than reserving, provisioning, or releasing through another site

#### Scenario: Bare-metal result is returned
- **WHEN** the recorded fulfillment succeeds
- **THEN** the storefront records one buyer-safe `BareMetalReceipt` and `BareMetalResult` (the tenant account, when access became ready, and the lease end) without an endpoint, a private key, provider payload, authority URL, or credential
- **AND** where to connect is served only live, through the access route, while the lease is active

#### Scenario: Bare-metal lease is torn down
- **WHEN** the buyer requests teardown for the completed fulfillment
- **THEN** the storefront terminates the lease at the recorded site, the site's lease lifecycle converges teardown through the recorded fulfillment and releases the capacity reservation exactly once after authoritative teardown success, and the storefront records the release only on the site's capacity-released callback

### Requirement: An Alkahest listing advertises its release conditions

A listing that publishes an Alkahest settlement option MUST advertise, per chain it
publishes on, the release condition its escrow will use: the arbiter and its demand data,
derived by the Alkahest mechanism from the seller's `[Settlement.alkahest]` policy, the
seller wallet, and the chain's address book, identically for every domain that composes
Alkahest. Release conditions MUST be derived only for Alkahest clauses whose mechanism is
ready. A domain MUST declare which release models it can deliver, and a configured release
model its domain cannot deliver MUST make Alkahest unready with a configuration blocker
naming the model, rather than refusing startup.

#### Scenario: A bare-metal listing offers Alkahest settlement

- **WHEN** a bare-metal storefront publishes a listing with an Alkahest option on a chain,
  under the default release policy
- **THEN** the listing advertises the recipient arbiter paying the seller's wallet on that
  chain, as a VM listing under the same policy does

#### Scenario: A domain is configured for a release model it cannot deliver

- **WHEN** a bare-metal storefront starts with `[Settlement.alkahest]` configured as
  interruptible
- **THEN** it starts, Alkahest is reported unready naming the release model, and no
  listing advertises an Alkahest option

#### Scenario: Alkahest is unready on a VM storefront

- **WHEN** a VM storefront's Alkahest section is oracle-gated with no trusted oracle
- **THEN** no release condition is derived for its clauses, and its candidates publish
  only the options of its ready mechanisms

## REMOVED Requirements

### Requirement: An unbacked pool yields no bare-metal listing

**Reason**: Bare-metal publication now derives unbacked listings from unbacked pools,
bound and published as unbacked, so the refusal no longer holds.
**Migration**: None. Pools previously refused begin yielding unbacked listings on the
first bare-metal publication cycle after this change.
