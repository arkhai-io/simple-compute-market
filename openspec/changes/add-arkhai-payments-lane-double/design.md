# Design: in-lane authority doubles

## Context

The foundation is `agreed-evidence-and-early-termination`: commitment ends the
protocol; lifecycle commands go through payment and dispute adapters; end service
realizes the earliest final request; money moves only at the named authorities.
The owner-approved reconciliation removes the payee-advanced billing horizon. The
buyer's guarantee is its own authority stop and a case over held money, backed by
kept signed bytes. Seller cooperation is useful but not assumed.

Observed on the reconciliation base:

- `kit/arkhai-payments/src/market_arkhai_payments/fixtures/payments_client.py`
  is an in-process `FakePaymentsClient`; its snapshot proof is a placeholder, its
  parts are held/reversed, and it has no rate-part stop or case extensions.
- `kit/arkhai-payments/schema/SOURCE.md` pins a once-only vendored publication.
  The foundation describes the next revision, not yet vendored on this base.
- `e2e-tests/Makefile` owns three isolated Compose lanes and their cleanup targets;
  payment settings are blank by default. Bare-metal and credits payment scenarios
  already exist. There is no mediation kit on this base.
- The foundation's tasks 11.1 and 12.2 consume boundary doubles; its section 12 also
  says it delivers the mediation double. Ownership must be made singular (D7).

## Goals and acceptance boundary

Both authority boundaries are reachable through real HTTP clients with verifiable
signed records. Existing payment scenarios run rather than skip on a ready lane.
Later lifecycle scenarios can independently fail the storefront, payments or
mediation without assuming that the counterparty is cooperative. Evidence says
which contract each authority played. Passing against a double establishes SCM's
use of the boundary, never the correctness or readiness of a hosted authority.

This is design-stage work. No deployed target, new runtime or live qualification is
claimed by this reconciliation.

## Decisions

### D1. Two HTTP services in test tooling, not a second production implementation

**Recommendation:** put a wheel-building tooling project at
`tools/authority-lane-doubles`, import package `authority_lane_doubles`. One image
runs two separate entry points (payments and mediation), with separate account
identities, signing keys, stores and health states. The tooling project is outside
the production package-layer graph, so it can compose both kits without making the
mediation kit import a payment mechanism. No production package imports this tool.

Reuse the kits' public models, canonicalization and signed-frame fixture functions.
Keep fixture primitives in their own kits; the HTTP state machines, authority-side
payment composition and lane controls live only in the tool. The existing narrow
in-process fake may remain for receipt-gate tests; it is not a competing authority
simulator and must not grow its own rate/mediation model.

Build from the committed lock and repository wheelhouse using
`docs/development/BUILD_AND_PACKAGING.md`'s image rules. The image ships no source
mount or hidden local environment. Keys and accounts are deterministic, explicitly
labelled public development fixtures, trusted only in lane profiles and never on a
public network. The payment authority always signs `livemode: false`.

### D2. Two contracts, pinned independently from deployment

Keep the `published` / `proposed` flag, not the former horizon extension. For each
service, published mode is exactly the schema and vectors identified by its kit's
`schema/SOURCE.md`. Proposed mode is a versioned candidate contract with a manifest
of differences and content hashes, kept with the tooling and explicitly unpublished.
It is not a permissive union: unsupported commands fail, never silently succeed.
When publication and vendoring catch up, matching features move to published mode;
that does not establish that the hosted deployment has them.

The flag may be selected per service with the same vocabulary. A run records a
contract/evidence class for each boundary it uses; if either needs a proposed
contract, the combined result is proposed qualification. A service without a
published contract cannot claim published readiness. Payment-only scenarios can
still use published payments without requiring an unpublished mediation interface.

**Recommendation:** expose contract identity, mode, readiness, content hashes and
control state on a lane-only status route and in the run report, not as new fields
in authority-signed wire frames. Public responses remain valid against the selected
schema. Valid receipt and snapshot frames must reproduce published vectors when
available. Until a required frame/vector is published, pin its candidate explicitly
and classify that scenario as proposed; a placeholder proof is never success.

Required vectors for requalification are a signed snapshot, snapshots before/after
`start` (including the pre-start reserved batch/funded-through), and partial rate
reversal before and after stop. Missing producer vectors block published
qualification of those surfaces, not honest proposed qualification. Do not invent a
published frame or claim that two SCM implementations agreeing proves conformance.

### D3. Payments target: the per-part revision

The target contract mirrors the foundation's authority derivation, with production
rate-part behavior owned by `spot-deals-through-arkhai-payments`:

- Approve the exact mandate, receipt and Agreement attachment; authenticated accounts
  and idempotency keys go through the real client boundary. No rate earnings before
  the payee's per-part `start`; the period clock begins there, not at approval.
- Parts carry their own authorities. Start is payee-only; stop entries carry
  `{account, notice}`. An on-demand part has no payee stop entitlement. Unauthorized
  events are refused, even when the caller is the seller.
- `stop {part, at?}` is never backdated: effective time is the later of the requested
  time (or now) and receipt time plus that sender's notice. The earliest pending
  stop wins, cannot be withdrawn, and fires at the authority without another
  storefront call. Buyer notice is priced in the accepted terms, including zero
  when offered; reserve-ahead is not a substitute for it.
- Absolute per-part `end` and transaction funding exhaustion stop with cause terms.
  Snapshots expose `fundedThrough`, per-part `started`, `stop`, `pendingStop`, event
  sequence and `latestEventSequence`, according to the selected contract.
- Held rate earnings release no earlier than stop plus the dispute window
  (`{afterStop: d}`). Once amounts retain their term-end/window hold. Partial
  `reverse {part, amount}` is repeatable up to held money, before or after stop;
  released money cannot be reversed. There is no separate post-stop refund command.
- Only an authorized authority opens `extend {part, until?}` and receives a stable
  service-issued ref under the same idempotency key; `lift {part, ref}` closes only
  that extension. Multiple cases compose, open extensions delay `releaseAt`, and
  `maxHoldExtension` caps them (null means unbounded). Report the contract's
  `hold_not_extendable`, `extension_not_found` and `extension_closed` refusals.
- Mixed setup `once` plus `rate` mandates are supported when the selected contract
  supports them. Started-period arithmetic follows that contract; authority-side
  reversal since an end uses the same pinned arithmetic, not storefront estimates.
  No minimum-spend primitive or bond capability is invented by this double.

This model must make both no-stop-on-demand and authority-hosted seller notice
observable while the storefront is down. It does not emulate storefront-local
schedules, vouching or a seller-supplied claim that service continued.

### D4. Mediation target: a separate dispute authority

The `arkhai.mediation.v1` double follows the foundation's public dependency contract,
not a new SCM adjudication policy. Its advertisement pins supported mechanisms,
minimum dispute window/case hold, and procedure. Lane fixtures simulate approval of
the seller at transaction approval; out-of-scope filings receive a named refusal.
File/append/read access is checked against the agreement parties and the configured
authority identity. Knowing a transaction or case ref grants no permission.

- Either party files an idempotent, self-contained case about the commitment, with
  the Agreement, claim, requested intent and ordered evidence. The authority reads
  the attached committed form and determines per-part effects; neither SCM adapter
  nor control caller supplies a trusted computed refund.
- Before reporting a part held, the authority sends `extend` to the payment double
  using its own account, keyed by case and part. File returns the case reference and
  each part's `held` with ref or `not_held` with reason. Unreachable/uncertain
  extensions stay pending or return the interface's error, not fictional acceptance.
  Payout can win the race; a late case is recordable but cannot recover paid-out funds.
- Either party appends items/statements repeatedly to an open case, under its actor
  and idempotency key. A closed case refuses new appends. One per-agreement signed
  sequence spans all its cases: filing, append, ruling, close, extension refs and
  effects with stable IDs and applied state. Read/watch supports resumable cursors
  and discovery of cases filed while a party was offline; no cross-authority order
  is assumed. Sign with the Agreement's `record_key` through the shared kit fixture.
- Mechanically rule only payee requests at least as strong on every part as the
  standard self-penalty, and payer `buyer_end(at)` carrying a verified storefront
  acknowledgement of an end at or before `at`, bound to this deal and buyer request.
  Requested end times are no later than now; a future delivery end is not a ruling.
  The standard self-penalty ends delivery, reverses unserved once shares by time,
  stops rate parts and reverses their earnings since a past end; award a bond only
  if a later pinned contract actually supports one. A weaker seller request is not
  an entitled exit. Missing, forged or mismatched acknowledgements go to triage.
- Everything else, including unacknowledged buyer ends, goes to a visible triage
  queue. **Recommendation:** represent operator notification by a local outbox
  visible to controls; do not send real email. A lane-only operator ruling control
  feeds the same effect application path, not a new mechanical rule.
- Only the authority double applies effects over authenticated payment HTTP calls,
  with the case reference and stable effect keys, then lifts that case's extensions.
  A past end is stop-now plus reversal since `at`, never a backdated stop. Delivery
  end is in the signed ruling for end service to observe. A discount need not end
  delivery. Partial application resumes after outages without duplicate effects;
  a case is not presented as fully applied while any effect remains pending.

Pinned keys/origins keep the foundation's limitation: controls may simulate rotation,
but do not teach clients to trust an unpinned successor or claim solved key migration.

### D5. Controls are lane-only routes

Retain mid-run controls for chosen-instant exhaustion, stale/equal/regressed sequence
and wrong-transaction snapshots, delayed/dropped responses, chosen command/error
refusals and signing-key rotation with overlap. Add independent authority outages,
append/close races and pause/resume of ruling effects. Dropping a response after
commit must leave the original idempotent result readable. Faults are scoped by run,
transaction/case and operation; they do not contaminate another lane or scenario.

**Recommendation:** give both services an injected deterministic clock, advanced by
an explicit control barrier, so notice maturity, payout and extension races are
reproducible without wall-clock sleeps. Advancement reports what each service has
processed; it never creates an order across unrelated authority records. Reset is
scoped to the owned run; destructive controls are never exposed on a hosted target.
Controls require an explicit lane profile and stay on its private Compose network,
without host ports. Contract mode is fixed before scenario mutation, not toggled
mid-deal. Controls are refused outside that profile.

### D6. Lane first use and evidence classes

**Recommendation:** add a shared `compose.authority-doubles-lane.yml` overlay to the
three existing lane targets, not to default/production stacks. Use one image built
by their existing build graph, with services separately addressable on each lane's
network. Each lane owns its stores, identities, seeded payer balance, seller account
and dispute advertisement. Existing environment/profile tooling supplies fixture
credentials and accepted `[[Dispute]]` / `[[DisputeCredential]]` entries rather than
reusing the retired payment-level dispute-authority setting. No live secrets or
operator endpoint is needed by public CI.

Existing `make -C e2e-tests test-e2e-bare-metal` and `test-e2e-apicredits` are the
first-use surfaces: build, seed, health-check, then run the existing payment deals
through the configured HTTP service. VM wiring prepares the same boundary for its
later rate scenarios. Missing lane-owned settings fail by name; an unready required
authority stops scenario mutation and reports environment setup, not product failure.
Cleanup uses the existing lane down/log targets and also removes double state.
A separately configured external target retains readiness gating; it is never
silently replaced by the double.

Each scenario/report identifies consumer revision, target kind, selected contracts
and hashes, and exactly one aggregate evidence class:

1. *Qualification against the published contract*: all exercised authority surfaces
   match their pinned publications/vectors, using test doubles.
2. *Qualification against a proposed contract*: at least one exercised authority
   surface uses an explicitly pinned candidate. This cannot enable live servicing.
3. *Live evidence*: only an explicitly configured, ready hosted deployment, after
   the activation follow-on checks its capabilities and the double's conformance.

The double's internal ledger and triage state prove only that the lane was driven
as intended. Signed records and marketplace observations prove SCM's handling of
that boundary, not the real authorities' accounting, adjudication or availability.

### D7. One owner and non-cyclic dependency gates

This change owns both runnable doubles, including their state machines and controls.
The foundation owns vendoring, generated models, fixture signing/verification seams
and the production adapters. Work can proceed in this order:

1. Foundation interfaces and published/draft mediation schema (section 12.1), payments
   re-vendor (8.1), and signed snapshot frame/fixture seam (9.1).
2. This change's corresponding HTTP doubles and lane wiring; proposed mode can use a
   pinned candidate where a publication/vector is not available, without claiming it
   is published. If the fixture seam is not ready, coordinate it in the foundation;
   do not add another private framing implementation here.
3. Foundation adapter integration (11.1, 12.2) consumes these doubles. It does not
   gate their construction. Rate-part production work and compute end-to-end
   scenarios then consume the same double; hosted activation follows publication
   and deployment, not a horizon feature.

Requested edits outside this change (reported to the owner, not applied here):
foundation tasks introduction and sections 11/12 must name this change as the owner
of runnable doubles, remove the section-12 delivery/file entry for a second double,
and split its contract/fixture prerequisite from adapter integration consumption.
Foundation design D6 (adapter and package rows), D15 and the mediation dependency
paragraph should say the kits own contract/client/fixtures, while this change owns
the executable simulators. Existing narrow receipt fakes remain kit fixtures.

## Rejected alternatives

- Payee-advanced billing horizon / `vouch`: a misbehaving payee advances it, so it cannot guarantee the buyer's protection.
- Backdated/effective-time payee stop: stop-now plus held-money reversal realizes a past end without rewriting the stop record.
- Required minimum spend: churn is seller pricing/acceptance policy; a setup once part is an honest default fee.
- Storefront-local stop scheduling: it dies with the storefront; notice belongs on the authority's pending stop.
- Refund of released funds / separate refund journal endpoint: afterStop holds keep timely corrections reversible through ordinary reverse.
- Stop releasing every hold immediately: it defeats the agreed dispute window and timely case extensions.
- Published-only double: it blocks explicitly labelled proposed qualification before the target revision is published.
- Proposed-only double: it hides which guarantees the vendored publication actually supports.
- Separate images for each contract mode: one pinned mode selector per service keeps packaging and controls shared.
- In-process fake as lane authority: it cannot exercise HTTP authentication, retries and signed records through real clients.
- Cross-mechanism payment imports in the dispute kit: authority-side composition belongs in tooling, not a single-interface kit.
- Automatically ruling all buyer claims: the initial mediation policy sends unsupported evidence to triage.
- A fixture key trusted by default production configuration: a public test identity is never a production authority.

## Open questions

None requiring an owner decision for this reconciliation. Publication, vectors and
fixture availability are explicit implementation/qualification gates, not permission
to weaken contract claims. Recommendations above are the supplied implementation
choices and can be revisited at design reverification if actual kit interfaces differ.

## Design promotion record

| Accepted knowledge | Permanent destination at closeout |
|---|---|
| D1, D7: tooling ownership and kit boundary | `openspec/specs/test-compatibility/architecture.md`; `docs/development/TESTING.md` |
| D2, D6: two contracts and three evidence classes | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`; `e2e-tests/README.md` |
| D3, D4: what the doubles simulate, not external guarantees | `openspec/specs/test-compatibility/spec.md` and companion architecture |
| D5: scoped controls and deterministic time | `openspec/specs/test-compatibility/spec.md`; `e2e-tests/README.md` |
| D6: lane setup and readiness | `docs/development/TESTING.md`; `e2e-tests/README.md` |
| Campaign readiness and Goal 8 gap | `openspec/changes/README.md`; `docs/development/ROADMAP.md` (owner integration, then closeout) |

No permanent behavior is promoted by the design reconciliation itself. External
contract rationale remains the foundation's promotion responsibility.

## Reconciliation validation

`openspec validate add-arkhai-payments-lane-double --strict` and
`make check-change CHANGE=add-arkhai-payments-lane-double` pass on the reconciled
design. No runtime, packaging or end-to-end execution is claimed; those remain the
implementation plan's gates.
