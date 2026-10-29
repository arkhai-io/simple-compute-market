# Design: in-lane authority doubles

## Context

The foundation is `agreed-evidence-and-early-termination`: commitment ends the
protocol; lifecycle commands go through payment and dispute adapters; end service
realizes the earliest final request; money moves only at the named authorities.
The reconciled plan uses authority records and held-money remedies. The
buyer's guarantee is its own authority stop and a case over held money, backed by
kept signed bytes. Seller cooperation is useful but not assumed.

Observed on the reconciliation base:

- `kit/arkhai-payments/src/market_arkhai_payments/fixtures/payments_client.py`
  is an in-process `FakePaymentsClient`; its snapshot proof is a placeholder, its
  parts are held/reversed, and it has no rate-part stop or case extensions.
- `kit/arkhai-payments/schema/SOURCE.md` pins the mandate-level-authority
  publication, which already supports rate parts. SCM currently derives once-only
  mandates. The foundation's per-part-authority revision is not yet vendored.
- `e2e-tests/Makefile` owns three isolated Compose lanes and their cleanup targets;
  payment settings are blank by default. Bare-metal and credits payment scenarios
  already exist. There is no mediation kit on this base.
- The foundation assigns runnable doubles here and keeps contract fakes in the
  kits. The remaining prerequisite seams are installed contract resources and one
  shared payments fixture engine (03 F2 / 04 F3/F11, owner E-H).

## Goals and acceptance boundary

Both authority boundaries are reachable through the marketplace parties' real HTTP
clients with verifiable signed records. Existing payment scenarios run rather than skip on a ready lane.
Later lifecycle scenarios can independently fail the storefront, payments or
mediation without assuming that the counterparty is cooperative. Evidence says
which contract each authority played. Passing against a double establishes SCM's
use of the boundary, never the correctness or readiness of a hosted authority.

Missing signed snapshot, before/after-start or partial-reversal producer vectors
keep affected first-use scenarios in proposed-contract qualification, even if the
scenario uses only once parts. This does not block honestly labelled first use.

This is design-stage work. No deployed target, new runtime or live qualification is
claimed by this reconciliation.

## Decisions

### D1. Two HTTP services in test tooling, not a second production implementation

**Recommendation:** put a wheel-building tooling project at
`tools/authority-lane-doubles`, import package `authority_lane_doubles`. One image
runs two separate entry points (payments and mediation), with separate account
identities, signing keys, stores and health states. The tooling project is outside
the production package-layer graph, so it can compose both kits without making the
mediation kit import a payment mechanism. No kit, including its test environment,
depends on this tool.

Reuse the kits' public models, canonicalization and signed-frame fixture functions.
Keep fixture primitives in their own kits. One pure, clock-injected payments
authority engine lives in `kit/arkhai-payments` fixtures (foundation 8.1 owns it).
The kit's in-process fake uses that engine directly; this tool wraps the same engine
with HTTP, controls and mediation composition (04 F3, E-H). Mediation's state
machine and authority-side payment composition live only in tooling. Both consumers
exercise the kit-owned vectors; there is no second hand-maintained payments ledger.
Kits keep in-process contract fakes for unit and library-integration tests (D-H). Application-integration tests use
those injected fakes too; only lane/system-integration tests require the runnable
HTTP services. No Compose dependency is added to ordinary kit `make test`.

The tool's own suite lives in its `tests/` directory and drives public marketplace
clients against its services with an injected HTTP transport, plus a container
transport smoke. Authority-side `extend`/`lift` and ruling effects have no existing
SCM party client: one tool-owned `authority_payments_client.py` builds authenticated
HTTP requests from kit-generated models. It is not exported from the mediation kit
and is not a new production adapter (02 F14).

Build from the committed lock and repository wheelhouse using
`docs/development/BUILD_AND_PACKAGING.md`'s image rules. The image ships no source
mount or hidden local environment. Keys and accounts are deterministic, explicitly
labelled public development fixtures, trusted only in lane profiles and never on a
public network. The payment authority always signs `livemode: false`.

### D2. Two contracts, pinned independently from deployment

Keep the `published` / `proposed` contract selector. For each
service, published mode is exactly the schema and vectors marked published by its
kit's `schema/SOURCE.md`. Candidate schemas, models and vectors also live in the
owning kit, explicitly marked unpublished with content hashes. Proposed mode selects
those same bytes. The tool holds only a selector and difference manifest referencing
them, not a second candidate contract (02 F5). A SOURCE identifying a draft cannot
make published mode ready.

**Recommendation (03 F2 / 04 F11):** foundation 8.1 and 12.1 own installed
resource APIs for both kits: selected schema/vector bytes, generated models and
publication/hash metadata readable from a built wheel without sibling checkouts.
Keep one canonical source and generate packaged resources/metadata from it. Payments
8.1 also pins the unpublished candidate, models and vectors when publication lacks
the requested features. The lane-only proposed declaration selects the same candidate
for publication, acceptance, mandate derivation and this tool; expressibility checks
use that selection, never a union of models. Missing resources block the affected
surface by name. Readiness compares consumer hashes in both modes.

It is not a permissive union: unsupported commands fail, never silently succeed.
When publication and vendoring catch up, matching features move to published mode;
that does not establish that the hosted deployment has them.

The flag may be selected per service with the same vocabulary. A run records a
contract/evidence class for each boundary it uses; if either needs a proposed
contract, the combined result is proposed qualification. A service without a
published contract cannot claim published readiness. An Agreement naming an unpublished dispute interface also makes the run proposed,
even if no case is filed: its committed hold/adjudication terms depend on that draft.
Only scenarios whose commitments and exercised surfaces are all published may claim
published qualification. Draft mediation admission is explicit and lane-only.

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
  `{account, notice, partialPeriod}` when the selected revision supports it.
  Parties' `partialPeriod` is `charged`, `returned` or `prorated`, mapping respectively to
  SCM `settles_through` values `started_period` (bill the started period),
  `last_boundary` (bill only to the last boundary) and `stop` (prorate to the
  effective stop time).
  The payment authority computes the result; no storefront started-period refund
  corrects it afterwards. Client defaults are payer charged and payee returned;
  until vendored support exists, publication/acceptance refuse unexpressible terms
  and spot uses charged for both. There is one notice per party, from its
  entitlement's `notice_seconds`. The dispute authority's stop entry uses
  `partialPeriod: chosen`; every operator ruling states its treatment explicitly.
  Seller entitlement treatment is negotiated, not mandated by mediation. An on-demand
  part has no payee entitlement to stop in its own interest. Under the candidate
  contract, however, the payee may always stop immediately in the payer's interest,
  without a stop entry, with partialPeriod returned (E-A/E-C). The payee may waive
  payer notice, and the payer may release held money early, waiving its dispute
  window. Unsupported candidate operations in published mode refuse explicitly.
- An entitled `stop {part, at?}` is never backdated: effective time is the later of the requested
  time (or now) and receipt time plus that sender's notice. The earliest pending
  stop wins, cannot be withdrawn, and fires at the authority without another
  storefront call. Buyer notice is priced in the accepted terms, including zero
  when offered; reserve-ahead is not a substitute for it.
- Where the selected contract expresses these features, absolute per-part `end`
  carries its own `partialPeriod`, with no whole-period
  rounding of accepted terms; compute presets use returned when expressible.
  Transaction funding exhaustion stops at its funded-through period boundary.
  Rate periods are earned at period end or the part's stop, remaining reserved
  until then. A `{for}` hold pays relative to that earning instant, not period start.
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
  supports them. Setup ends at activation/provisioning and pays out one dispute
  window later, only through an immutable authority event/anchor defined by the
  selected candidate; the authority does not observe compute activation itself.
  Missing representability refuses setup support rather than inventing an end.
  Published mode always follows its publication's actual earning/hold semantics.
  Started-period arithmetic follows the selected contract; per-part reversal uses
  the same pinned arithmetic, not storefront estimates.
  No minimum-spend primitive or bond capability is invented by this double.

Consumers preserve the other settled delivery boundaries: rate `start` is issued
only after activation (D-F); a buyer's nonzero-notice stop sends a hint and delivery
continues until watch observes effectiveness, while explicit end-now/unreachable-
authority paths retain `end_delivery` and `buyer_end(at)` (D-C). The VM admin route
uses an entitled notice stop or otherwise exceptional_end (D-E). Physical completion
requires proven release, never a `lease_ended` intent report (D-G). These behaviors
are owned by their foundation/rate/servicing changes, not reimplemented in the double.

Exceptional_end is a seller payment-adapter command, not a mediation request (E-C).
The adapter stops every rate part now with returned treatment, reverses rate earnings
since the past end and the unserved once share by time, and awards a bond in full
only once supported. Setup returns all before activation and none after. It journals
immediately, never future-dates; a pre-start failure acts at the Agreement start.
Revised self-corrections must account for prior reversals rather than duplicate them;
SCM adapter/journal ownership remains with the foundation and spot.

On end_delivery (no buyer-supplied at), the seller records its own receipt and ends
service then. It journals a cooperative payee stop for receipt plus the payer's
notice with the payer's partialPeriod, retrying when payments recovers; policy may
waive notice (E-B/E-E). The double supports the candidate payment operations behind
that path; delayed replay follows the foundation's pinned per-part mapping, never
backdates a stop or fabricates billing completion. It does not implement end service. The buyer still stops at payments
first when reachable. This is distinct from the payee's unconditional returned stop.

This model must make both no-self-interested-stop-on-demand and authority-hosted seller notice
observable while the storefront is down. It does not emulate storefront-local
schedules or a seller-supplied claim that service continued.

### D4. Mediation target: a separate dispute authority

The `arkhai.mediation.v1` double follows the foundation's public dependency contract,
not a new SCM adjudication policy. Its advertisement pins supported mechanisms,
minimum dispute window/case hold, and procedure. Lane fixtures simulate approval of
the seller at transaction approval; out-of-scope filings receive a named refusal.
File/append/read access is checked against the agreement parties and the configured
authority identity. Knowing a transaction or case ref grants no permission.

- Either party files an idempotent, self-contained case about the commitment, with
  the Agreement, claim, requested intent and ordered evidence. The authority reads
  the exact Agreement carried in the case, verifies it against the committed
  mandate's deal hash, and determines per-part effects without requiring an attachment
  (E-F); neither SCM adapter
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
  is assumed. A known authorized agreement with no cases returns an empty signed
  record at cursor zero; watch starts there and waits for subsequent entries. An
  unknown agreement or unauthorized reader receives the pinned contract's refusal,
  not a fabricated empty record. Sign with the Agreement's `record_key` through the
  shared kit fixture (02 F12).
- Every claim, including buyer_end(at) with a signed storefront acknowledgement,
  enters visible triage. There are no mechanical rulings before the managed metering
  gateway (E-D). Exceptional_end is absent from mediation's request vocabulary,
  mapping and classifier; seller self-correction goes through the payment adapter.
  Acknowledgements are evidence for a person, not an automatic ruling input.
  **Recommendation:** represent operator notification by a local outbox visible to
  controls; do not send real email. A lane-only operator ruling control feeds the
  single authority effect application path. Every ruling that stops a rate part
  explicitly states partialPeriod; omission refuses without mutation.
- A buyer_end ruling realizes the payer's own stop submitted at at: its effective
  billing end includes the payer's priced notice and its committed partialPeriod.
  It cannot skip notice via mediation. A past remedy uses a present stop and only
  the held-money adjustment needed to realize that target, never a backdated stop.
  Future requested end times refuse. Once parts remain untouched by buyer_end.
- Only the authority double applies dispute effects over authenticated payment HTTP
  calls with case refs and stable effect keys, then lifts that case's extensions.
  Delivery end is in the signed ruling for end service to observe; a discount need
  not end delivery. Partial application resumes without duplicate effects and is
  not reported complete while effects remain pending.
- **Recommendation (03 F1 / 04 F9):** revision-bound cases carry prior case/effect
  references and earlier signed evidence. Compute the agreement-wide target remedy
  using the foundation's pinned mapping, net prior confirmed remedies per part,
  resolve uncertain effects before calculating the remainder, and apply only the
  additional amount (40 returned toward a total remedy of 60 means 20 more, not 60).
  Preserve provenance across open/closed cases, partial application and append/close
  races. Serialize competing remedy application per agreement. Missing contract or
  netting vectors leaves the revision in explicit repair/triage, never fabricated
  completion. This remains necessary for operator cases after self-correction;
  no automatic exceptional_end rule is restored.

Pinned keys/origins keep the foundation's limitation: controls may simulate rotation,
but do not teach clients to trust an unpinned successor or claim solved key migration.

### D5. Controls are lane-only routes

Retain mid-run controls for chosen-instant exhaustion, stale/equal/regressed sequence
and wrong-transaction snapshots, delayed/dropped responses, chosen command/error
refusals and signing-key rotation with overlap. Add independent authority outages,
append/close races and pause/resume of ruling effects. Add payer funding/top-up
controls that advance funded-through through the selected contract engine, and a
labelled record-corruption control that signs a livemode:true fault frame. Normal
records remain livemode:false; this fault is never a readiness or live-evidence mode.
**Recommendation (04 F9):** payments rotation serves old receipts unchanged inside
current-identity-signed snapshots during overlap, with the selected contract's
attestation/re-anchoring proof; removing the old signer does not erase that proof.
Missing vectors keep this scenario proposed-only. Dropping a response after
commit must leave the original idempotent result readable. Faults are scoped by run,
transaction/case and operation; they do not contaminate another lane or scenario.

**Recommendation (02 F4):** use wall time in lanes, with short notice/dispute
windows admitted by lane advertisements. A typed due-work barrier processes work
due at its captured current instant and reports the processed watermark per
authority, pending effects and blocked dependencies. Future work remains pending;
a blocked effect is never a successful completion. Bounded waits observe progress,
not arbitrary sleeps. No lane-wide time travel or cross-authority order is claimed.
Each authority processes due work on reads and writes and with an internal
wall-time scheduler, independent of barrier calls (04 F10). A barrier forces and
reports progress; it is not the event that makes a stop or payout effective.
Status and barriers expose each authority's current instant for consumer skew checks.
Only isolated state-engine tests inject and advance deterministic time.
This replaces D5's per-service clock advancement in live lane compositions, which
would put authority records ahead of the storefront/site clocks.

**Recommendation (01 F2 / 02 F12):** publish tooling-owned versioned control models,
a route contract and typed `control_client.py`. Consumers do not hand-write raw
requests or import service internals. Explicit initialization creates a run with
seed, mode and fixture identities; status before selection is not ready. Unknown
run/transaction/case references refuse and create nothing. Every mutation requires
a run ID and a nonempty explicit target set; omitted or empty targets refuse rather
than mean all. Only explicit initialization may create run scope. Reset names that
run explicitly, removes only its state, and refuses
unknown runs. Unsupported control versions refuse before mutation. Barriers return
per-authority progress, never a fabricated global cursor. A tooling-owned isolated
HTTP harness creates, initializes and tears down only its own services and run;
ordinary kit suites continue to use contract fakes rather than this harness.

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

**Recommendation (01 F1 / 02 F2):** use HTTPS service origins with certificates
whose SANs name the Compose services, a bundle of the lane-only CA plus default
public roots trusted explicitly through `SSL_CERT_FILE`, and fixture bearer credentials mapped by each double to its own
public development accounts. Keep `development_auth = false`; non-loopback
`X-Account-ID` auth and plain HTTP remain refused by the published clients. The
lane overlay mounts the CA only into participating containers and names credential
environment variables through `api_key_env`. No verification bypass or production
origin/auth relaxation is added. The lane profile explicitly selects this development
origin/auth tuple and `livemode = false`; production configuration refuses lane-only
profile settings, fixture authority identities and proposed declarations. This
change owns the composition guard in role configuration loaders and
`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py` (and the planned
mediation config), not a transport/auth relaxation in `PaymentsClient` or
`ArkhaiPaymentsConfig`. The future mediation client follows the same constraints.
Readiness must use the same explicit CA through an SSL context while preserving
its current `trust_env=false` proxy isolation; it cannot rely on SSL_CERT_FILE being
honored there. Real clients retain `trust_env` for non-loopback origins, so lane
participants explicitly bypass ambient proxies for their service names. Neither
path disables certificate verification.
Files: planned overlay, tooling Dockerfile/TLS fixtures, lane profiles under
`e2e-tests/config`, and their configuration helper. Verify config construction and
a signed real-client request between containers before first-use scenarios.

Existing `make -C e2e-tests test-e2e-bare-metal` and `test-e2e-apicredits` are the
first-use surfaces: build, seed, health-check, then run the existing payment deals
through the configured HTTP service. VM wiring prepares the same boundary for its
later rate scenarios; VM evidence here is only health/readiness, not payment
scenario qualification (02 F15). This change also ports the existing bare-metal
payment scenario to foundation's commit/buyer-half re-drive, seller reverse and
buyer end_delivery flow; API credits retains its separately owned settle binding.
Missing or unready lane-owned targets fail setup by name before scenario mutation,
never skip or report a blocked prerequisite (03 F3 / 04 F1/F2).
Cleanup uses the existing lane down/log targets and also removes double state.
A separately configured external target retains readiness gating; it is never
silently replaced by the double.

Both published- and proposed-mode readiness compare selected schema/vector hashes with each required
consumer's kit SOURCE hashes, refusing mismatch by name before mutation (02 F13).
The fixture payments identity is also the proposed-servicing declaration's binding:
it must equal configured `SERVICE_IDENTITY` in test mode; production refuses it.
Clients never query the private status/control route to establish trust (02 F8).

This change alone defines the evidence classes; foundation target-naming rules
remain their single owner for readiness and blocked-versus-fail behavior. Spot and
activation reference these classes instead of redefining them (02 F6 / F9).
Each scenario/report identifies consumer revision, target kind, selected contracts
and hashes, and exactly one aggregate evidence class:

1. *Qualification against the published contract*: all committed and exercised authority surfaces
   match their pinned publications/vectors, using test doubles.
2. *Qualification against a proposed contract*: at least one committed or exercised authority
   surface uses an explicitly pinned candidate. This cannot enable live servicing.
3. *Live evidence*: only an explicitly configured, ready hosted deployment, after
   the activation follow-on checks its capabilities and the double's conformance.

The double's internal ledger and triage state prove only that the lane was driven
as intended. Signed records and marketplace observations prove SCM's handling of
that boundary, not the real authorities' accounting, adjudication or availability.

### D7. One owner and non-cyclic dependency gates

This change owns both runnable HTTP doubles, mediation's state machine and controls;
foundation 8.1 owns the shared kit payments engine consumed here.
The foundation owns vendoring, generated models, fixture signing/verification seams
and the production adapters. Work can proceed in this order:

1. Foundation sections 1–2 supply interfaces; 8.1 supplies payment schemas/models,
   the unpublished candidate, installed resources and shared payments fixture engine;
   9.1 supplies snapshot framing; 12.1 supplies mediation contracts, installed
   resources, models, netting mapping/vectors and record-signing fixtures. Its
   adapter verification uses kit fakes, with no library-test dependency back here.
2. Foundation 2.4 supplies the buyer-usable acknowledgement model/verifier in a
   permitted shared library; 13.1 supplies storefront signing and 7.5 consumes it.
   Mediation takes no acknowledgement-verifier dependency because all cases are
   triaged. Bare-metal scenario porting waits for foundation 7.4, 13.x and 15.x.
3. Build the corresponding HTTP surfaces and lane wiring here. Missing publication
   or producer vectors permits pinned proposed-only work, not published claims.
4. Later rate and compute lane scenarios consume the services. Kit unit/library
   and storefront application-integration tests keep kit-owned contract
   fakes (payments directly uses the shared engine), including foundation 7.4, 11.1, 12.2 and 14.2 and spot's kit suite (D-H).

Recommended landing sequence (02 F3): foundation prerequisites land first, then
this change, then lane consumers; no whole-change cycle or mutually importing
branches. The remaining foundation rounds can proceed using their own fakes.

The foundation owns those prerequisite contracts and kit fakes. Its
7.4/11.1/12.2/14.2 use in-process fakes. Tool construction has no reverse dependency
from kit integration. Archive foundation's target-naming requirement before this
change: the MODIFIED bare-metal requirement preserves all retained purchase,
recovery and cleanup clauses, but ports them to the post-foundation lifecycle flow.
This change alone defines evidence classes; siblings reference the permanent
requirement name, not an active change ID, and do not duplicate its scenarios.

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
- Mechanical buyer_end or seller self-penalty rulings: all mediation cases go to
  triage; exceptional_end is seller payment-adapter self-correction (E-C/E-D).
- A second payments simulator in tooling: shared vectors alone cannot keep two
  time-dependent ledgers aligned; one kit fixture engine serves both (E-H).
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
| D5: typed scoped controls, wall-time lane barriers and isolated test clocks | `openspec/specs/test-compatibility/spec.md`; `e2e-tests/README.md` |
| D6: lane setup and readiness | `docs/development/TESTING.md`; `e2e-tests/README.md` |
| Campaign readiness and Goal 8 gap | `openspec/changes/README.md`; `docs/development/ROADMAP.md` (owner integration, then closeout) |

No permanent behavior is promoted by the design reconciliation itself. External
contract rationale remains the foundation's promotion responsibility.

## First-review disposition and next review

All 01 F1–F3 and 02 F1–F15 findings have local dispositions in their triage records.
The tool-hosted kit-suite alternative is rejected under D-H; the typed control
contract and isolated tooling harness are retained. TLS plus explicit lane CA and
bearer fixtures is the recommended 02 F2 transport, not a production relaxation.
The double's own suites are required by the owner's 02 F10 disposition.

That first-round recommendation was to keep the index in design for the second
review. Reviews 03/04 are now triaged below; the parent owns the workflow exit and
index/roadmap edits.

## Second-review disposition and coordination

Reviews 03 F1–F3 and 04 F1–F13 have dispositions in their triage records. Owner
E-H replaces the dual-engine design with a shared payments-kit fixture engine;
E-C/E-D remove both mechanical ruling classes and mediation exceptional_end.
E-A/E-E add the cooperative seller payment operations; E-F makes the case-carried
Agreement sufficient, verified against the mandate hash. E-B's receipt time is used
by the cooperative stop. E-G remains servicing's authority-read rule, supported by
the double's funding/read controls; E-I retains the single term-end settles_through.

Applied: 03 F1/F2/F3; 04 F1/F2/F3/F5/F6/F7/F9/F10/F11/F12/F13, with coordination
outside this directory listed below. Rejected: 04 F4's automatic reclassification
(the case stays in triage under E-D), and 04 F8's proposed term-end fallback (the
seller corrects directly with returned treatment under E-C, without a mediation
exceptional_end intent). 04 F9's exceptional_end case examples are superseded;
netting remains for operator cases and prior seller corrections.

**Recommendations supplied:** foundation 8.1 owns the shared payments fixture
engine and payments candidate/resource seam; 12.1 owns mediation resources/netting
mapping and vectors. Generate installed resources from one canonical source and
check built-wheel use. This change owns the bare-metal scenario port (5.5). Classify
an Agreement naming draft mediation as proposed even without a filing. Serialize
remedy application per agreement and resolve uncertain effects before netting. Add
funding, labelled livemode fault and current-key/old-receipt re-anchoring controls.
Run due work on reads/writes plus an internal wall-time scheduler; barriers only
force/report progress and expose each authority's current instant. Use a lane CA
plus default-root bundle. These recommendations satisfy the settled owner decisions;
they do not reopen them.

Edits required outside this owned directory (parent coordination, not performed here):

| Owner | Required coordination |
|---|---|
| Foundation 8.1 / 9.1 | Supply the shared payments fixture engine/fake, installed resource/model metadata API, unpublished payments candidate and coherent snapshot/start/reversal vectors, including partial reversal before/after stop. The candidate and consumer selector must express the E-A/E-C/E-E operations. |
| Foundation 12.1 | Supply installed mediation resources and Agreement-in-case hash verification; triage only, no exceptional_end or acknowledgement-based mechanical rules; explicit ruling partialPeriod, payer-notice buyer_end mapping and agreement-wide netting vectors. |
| Foundation 2.4 / 7.5 / 13.1 | Put acknowledgement model/verification in a buyer-permitted shared library in round 1 (2.4); leave signing at 13.1. Mediation no longer depends on this verifier. |
| Foundation test-compatibility delta | Reference the permanent requirement name "Lane qualification identifies readiness and evidence class", remove duplicate mixed-contract scenario and stale change-ID citation; archive that target-naming modification before this change. |
| Spot and convergence | Consume the shared engine/typed controls; classify by the single lane requirement. Seller exceptional_end is payment self-correction; revised authority remedies net prior effects. Convergence reads authority at funding-timer expiry (E-G), compares exposed current instants and removes lane clock-jump wording. |
| Terms | Lane-only proposed declarations select installed candidate expressibility for publication, acceptance and mandate derivation; draft identities/contracts remain refused outside lanes. |
| Activation | Reference the class rule conditionally, include mediation publication when Agreement terms name it, and identify exactly which consumer declaration/artifact is retired, never the tool's proposed selector. |
| Campaign index / roadmap | Parent updates status/dependencies and removes obsolete mechanical/self-filing descriptions; these files remain outside this worker's authority. |

**Recommended status:** ready for planning once the parent integrates these
coordination edits. No further full design round is recommended: the central
changes are settled owner decisions and the remaining choices above are explicit.
Implementation remains section-gated on the named contract/fixture seams, and
missing publications/vectors still prohibit published or live qualification claims.
This is a recommendation to the parent, not an implicit index edit.

## Reconciliation validation

First-review triage validation: pinned
`bunx @fission-ai/openspec@1.14.0 validate add-arkhai-payments-lane-double --strict`,
installed `openspec validate add-arkhai-payments-lane-double --strict` (without
long-requirement warnings), `make check-change CHANGE=add-arkhai-payments-lane-double`
and `git diff --check` pass. No runtime, packaging or end-to-end execution is claimed;
those remain the implementation plan's gates.

Second-review triage: the same pinned and installed strict validators (no warnings),
`make check-change CHANGE=add-arkhai-payments-lane-double` and `git diff --check`
pass. The first validation caught the renamed retained bare-metal scenario; keeping
its original name with the narrowed external-target condition preserves the
MODIFIED superset. Reviews 03/04 and their triage records remain in the ignored
reviews directory for owner collection. Five course-correction ledger entries
record E-H, E-D, E-C, E-E and E-F. This remains plan-only validation, not runtime,
packaging or live qualification.
