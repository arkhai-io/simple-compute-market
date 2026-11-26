# Design: negotiation-capacity-feasibility-probe

## Context

**The listing-source check.** The negotiation runtime asks each compute domain to check
a listing against the declaration it was published from, and enforces the verdict
itself, whatever the seller's policy chain contains. It obtains the verdict before the
chain runs on an opening and on a buyer's counter, applies it to a seller decision that
would counter or accept, and obtains it again before a buyer's or an administrator's
acceptance writes anything (`kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py`,
`_listing_source`, `_enforce_on_decision`, `_enforce_on_acceptance`). The hook receives
the repository and the resolved listing, not the round's terms. A verdict is one of
four outcomes, and each has its refusal: a declared mismatch is `no_matching_declaration`,
taken capacity is `no_matching_inventory`, and a source that cannot be confirmed is a
retryable refusal, HTTP 503 (`kit/policy/src/market_policy/listing_source.py`). The
check has two halves, and the listing's backing delegate decides whether the second is
asked: an unbacked listing is judged on its declaration alone
(`kit/resource-pools-contracts/src/market_resource_pools_contracts/backing.py`,
`judge_async`).

**What the availability half asks today.**

- VM reads the bound site's snapshot, combines it with the projections the storefront
  holds, and judges whether the quantity the listing advertises is free now
  (`domains/vms/storefront/src/market_storefront/services/listing_source_check.py`,
  `_pinned_site_availability` and `check_listing_source`). The snapshot states what is
  free at the instant it is read. It says nothing of the shape the round carries, of
  holds over the deal's window, or of a conflict on the physical host.
- Bare metal reads the bare-metal view in the projection the storefront holds, which
  lags the site by up to the source-confirmation window, and calls no site
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/listing_source_check.py`).

**The site's dry-run.** `POST /api/v1/capacity/probe` takes a claim and an optional
lease window and answers the match a reserve would have made, or none
(`kit/site/src/market_site/router.py`; `kit/site/src/market_site/ledger.py`, `probe`).
It runs the candidate search a reserve runs, `_find_candidate`: the pool's deliverable
modes, the usable-host rule, held quantities over the window, and physical-host
conflicts. It reserves nothing. Like every ledger operation it first lapses expired
holds, and it runs under the ledger's one lock, as the snapshot read does. With a window
it counts the holds that overlap it; with none it counts every hold, whenever it runs
(`_held_dimensions`). A claim that names no offering mode is refused. The route's
contract admits the seller role (`kit/site/src/market_site/auth.py`), and the client
method is `SiteCapacityClient.probe`
(`kit/site-client/src/market_site_client/client.py`).

**The storefront's capacity path.** Every capacity effect a storefront makes passes one
guard, which acts only at the listing's bound site and only after the backing delegate
admits the effect (`kit/capacity-publication/src/market_capacity_publication/capacity.py`,
`CapacityEffects`). It has no probe. The aggregate client has one, which tries sites in
its ranking order, takes no site to pin, and reads a site whose call fails as a site
with no match (`core/storefront/src/core_storefront/aggregation.py`,
`AggregateCapacityClient.probe`). Its one production caller is the administrator's
settle dry-run
(`domains/vms/storefront/src/market_storefront/services/admin_settle_service.py`,
`evaluate_settle_dry_run`).

**A round's shape, and the cap.** A VM round may carry a shape other than the
listing's. The seller resolves the shape's policy, checks admissibility, checks
feasibility, compares GPU model and region, and only then prices, each refusal distinct
(`domains/vms/storefront/src/market_storefront/services/negotiation_shapes.py`,
`check_requested_shape`). No feasibility check is composed. In its place the seller
refuses any quantity above the listing's advertised one as `shape_exceeds_advertised`
(`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`,
`within_advertised`), and records the check as "not checked; capped at the advertised
shape". A flat-priced listing is shape-fixed apart from the cap. Bare metal negotiates
no shape: its claim is one whole unit of its Physical Resource
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/claims.py`,
`whole_machine_claim`).

**What bounds a shape besides the cap.** A stated listing shape may bound each quantity
inline, as `{offer, min, max}`, and the storefront's configured default fills the
bounds a listing leaves unstated. `settings.toml` ships no default, so a quantity whose
listing states no maximum has none
(`openspec/specs/storefront-publication/configuration.md`).

**When the site first admits a deal.** The VM storefront ships
`capacity.hold_ttl_seconds = 0`, so its acceptance places no hold, and the bare-metal
storefront composes none. The first admission is the reserve at settlement, after the
buyer has funded (`domains/compute/delivery/src/compute_delivery/path.py`,
`_reserve_settlement`). The claim it sends is built from the agreed terms: for VM by
`compute_capacity_claim_from_order` over the agreed order
(`domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`), for
bare metal by `whole_machine_claim`.

**A deal's window.** A deal billed per period states no duration of its own. Its
horizon is resolved at acceptance by the domain's `resolve_acceptance` hook, after the
runtime fixes the acceptance instant (`runtime.py`, `_fix_acceptance_time`). On a
buyer's or an administrator's acceptance the source check runs before that step.

**Released.** `marketplace-v0.4.0` carries all of the above, the probe route included.

## Decisions

### D1 — A seller asks its site whether it would admit the claim a round would reserve

Before a compute seller agrees terms, it asks the listing's site the question admission
will ask at settlement: would this claim, over this deal's window, be admitted now. The
claim is the one the settlement reserve would send, built by the same builder from the
round's effective terms, so the probe and the reserve cannot disagree about what is
being asked. The site answers with its existing dry-run.

Both compute domains ask it. For VM the claim carries the round's shape, so a shape
other than the advertised one is judged against capacity, and the advertised-shape cap
is no longer what stands in for that judgement; what then bounds an ask is Q1. For bare
metal the claim is one whole unit of the listing's Physical Resource.

A round within the advertised shape gains from it as well: a claim the site would
refuse for a hold over the window or a physical-host conflict is refused in the round,
where today the buyer learns of it at settlement.

Rejected:

- Folding the work into `publish-shape-bounds`. That change's work is the admissibility
  kit's render operation, publication and the buyer's reader; this change's is the
  negotiation runtime and the storefront's capacity path.
- Leaving the cap and having sellers publish every size they would sell. A catalogue of
  sizes is the pre-partitioning Goal 2 exists to remove, and a large listing closes once
  any of its quantity is taken.

### D2 — The question is the availability half of the listing-source check

The listing-source check is given the round's effective terms, and its availability
half asks the site D1's question. The check's verdict, its four outcomes and the
runtime's enforcement stay as they are. The site is therefore asked before every seller
decision, and on all four acceptance paths: an opening the seller accepts, a counter the
seller accepts, a buyer's acceptance and an administrator's. Both compute domains
contribute the question through the one hook.

Rejected:

- A second kit hook beside the listing-source check. It would need its own verdict, its
  own enforcement on every acceptance path and its own retryable outcome, all of which
  the check has.
- A step inside the VM seller's round evaluation alone. A buyer's and an
  administrator's acceptance run no seller evaluation, so two of the four acceptance
  paths would agree terms unasked, and bare metal would be left out with no reason
  particular to it (`docs/guidance/repository/family-kits.md`, "Sibling domains behave
  alike").

### D3 — A probe, not a hold

The seller asks and reserves nothing. Holding capacity during negotiation would exclude
other buyers at no cost to the holder, which is the denial the storefronts' default of
no hold before settlement closes. Charging for held time is Goal 5's work, and
`negotiation-time-capacity-hold` moves the hold earlier once it is charged.

Rejected: a short hold in place of the probe. Shortening the window does not remove the
denial; it raises only the request rate an attacker needs to keep the capacity held.

### D4 — The answer is advisory, and the race is accepted

A probe's answer is what a reserve would have decided at that instant, and only then.
Two negotiations may both be told the site would admit them, and one may be refused at
settlement. The reserve at settlement stays the admission. The requirement states this,
so no caller reads the answer as a guarantee.

Rejected: closing the race. That takes a hold (D3).

### D5 — A shape the seller's own policy refuses never reaches the site

Admissibility is judged before the site is asked. A seller that would not sell
sixty-four GPUs does not ask its site whether sixty-four are free, so site calls stay
proportional to asks the seller would consider. Admissibility is composed in every VM
round, so this has no degraded mode.

Where the question falls among the seller's later checks, the commercial guard and
pricing, follows the hook's shape (Q5).

### D6 — The site is unchanged, and only the listing's own site is asked

The site's route, its route contract, its ledger and its client method are used as they
stand. Nothing is added to the site, so no site release is needed and no pool fact is
read that the site does not read today.

The probe goes to the site the listing's binding names, and to no other. The source
check judges a listing against "the listing's own site and pool or Physical Resource,
never a resource elsewhere" (`storefront-publication`, "The seller's inventory guard
checks a listing against its own source"), and a deal reserves at its binding's site.
The aggregate client's ranked probe is not used: it cannot be pinned, and it reads a
site that did not answer as a site with no capacity.

Rejected: a dry-run flag on the reserve route, or a reason added to the probe's
response. The released route already answers the question, and a storefront needs only
a match or none.

### D7 — The source check's outcomes carry the probe's answers

- **An unbacked listing is never asked about.** The backing delegate decides whether
  the availability half runs, as it does today, so no site is contacted for a listing
  nothing stands behind.
- **A site that does not answer is a retryable refusal.** It is a source the storefront
  cannot confirm, which the check already refuses as retryable before any write. The
  seller bears its own outage: a buyer is not led to fund a deal the seller could not
  confirm. No setting chooses another outcome.
- **A site that would not admit the claim is an availability refusal**, distinct from a
  declared mismatch, from an inadmissible shape and from a commercial refusal.

Each is the existing requirement applied to D2, and none is a new policy.

Rejected: proceeding when the site cannot be reached, leaving settlement to find the
answer. With no hold before settlement, that moves the seller's outage onto a buyer who
has paid.

### D8 — Nothing gates the change

No other change, and no other repository, must land first. The probe route is released.
`inject-site-pool-authority` has landed, and this change reads no pool fact and adds no
read to the site's ledger. `settle-capacity-claim-vocabulary` adds a category to the
claim; the probe sends whatever claim the reserve would send, so whichever of the two
lands second reverifies against the other.

### D9 — The change is Goal 2's

Goal 2 is negotiating a full shape. A buyer who cannot ask above the advertised shape,
and a seller who must publish every size, is the part of that still missing, so the
change is listed in Goal 2's campaign and owns that gap.

It is no prerequisite of Goal 5. `billable-capacity-reservations` requires only that an
operation reserving nothing is never charged, which is true of the probe route today,
and no Goal 5 change needs anything this change lands.

Rejected: listing it as a shared prerequisite of both goals. A dependency is a
technical gate, and there is none.

### D10 — The storefront's dependency on the site authority package is not decided here

The VM storefront declares `arkhai-kit-site` at runtime and imports the site's claim
predicate, `dict_resource_satisfies_claim`, for two uses: publication's judgement of
each listing shape against projected members, which `storefront-publication`'s "A
listing shape is published only where a source member is feasible for it" requires to
be the site's own predicate, and the ranking matcher of the `most_available` placement
policy. This change touches neither. A negotiation probe goes to the listing's bound
site and passes no ranking, and a probe cannot replace a judgement publication makes
over projections for every listing shape.

The question is recorded as unowned in the change index, under "Package and release
readiness".

## Open Questions

Each is decided in this change's design session. Q1 is settled first: it decides what
lifting the cap means.

### Q1 — What a buyer may ask above the advertised shape where the seller stated no maximum

The cap is today the only upper bound on a quantity whose listing states no `max`,
since `settings.toml` ships no admissibility default. Once the probe judges a requested
shape, a one-GPU shape-priced listing on an eight-GPU machine could sell any shape one
machine can serve, at the published rates, though its seller stated nothing about
selling larger.

```yaml
# A pool's hint as a 0.4.0 seller may have written it: an offer and nothing else.
listing_shapes:
  vm:
    - gpu: { model: A100, count: 1 }
      cpu: { count: 8 }

# A seller stating that it sells larger.
listing_shapes:
  vm:
    - gpu: { model: A100, count: { offer: 1, max: 4 } }
      cpu: { count: { offer: 8, max: 32 } }
```

- (a) The cap lifts wherever admissibility admits. The first listing sells up to what
  one machine can serve; the second up to four GPUs and thirty-two vCPUs.
- (b) A quantity with no stated `max` keeps the advertised quantity as its ceiling. The
  first listing sells at most one GPU and eight vCPUs, as under 0.4.0; the second sells
  up to its stated maxima, and the probe judges each ask.
- (c) A pool policy tag states whether its listings sell above their offer.

A storefront setting is not among the alternatives.

Recommended: (b). A seller who stated nothing keeps released behaviour
(`docs/development/ARCHITECTURE.md`, "Omission states no commitment"), and a stated
`max` above the offer is already the form in which a seller says it sells larger, so
nothing is switched on. Its cost is one sentence to change: the configuration reference
says "an `offer` alone says nothing about negotiability", and under (b) an offer alone
is the ceiling of what may be asked, while a smaller ask stays free. It would move to
(a) if a shape-priced listing is taken as a statement that any shape is for sale at its
rates.

Whether the refusal `shape_exceeds_advertised` survives follows this answer: under (b)
it remains the refusal for a quantity above an unstated maximum; under (a) it is
retired.

### Q2 — A buyer asking about feasibility without opening a negotiation

Under D2 a buyer learns whether a seller's site would serve a shape by opening a
negotiation, which holds nothing and funds nothing. The Goal 5 documents speak of a
buyer who "verifies its feasibility without proposing".

- (a) No buyer-facing route. The opening is the inquiry.
- (b) A storefront route that answers for a listing and a shape with no thread.

Recommended: (a). An opening costs a buyer one signed request and already answers the
question, and a second route would answer it through a second surface that must be kept
in step with the first.

To the owner: is an inquiry without a thread anticipated, for example for a buyer
comparing many sellers before opening with one? If it is, (b) is a new public route
with a contract of its own, and it is designed here.

### Q3 — Whether the probe replaces the present availability judgement or joins it

Today the availability half asks whether the advertised quantity is free: for VM from
the snapshot and the held projections, for bare metal from the held projection's view.

- (a) The probe replaces it for a capacity-backed listing. A VM round costs one site
  call, as today. A shape smaller than the advertised one can then be agreed on a
  listing whose advertised quantity is no longer free, until reconciliation closes that
  listing.
- (b) The probe joins it. A VM round costs two site calls, and a shape the site would
  admit is still refused where the advertised quantity is taken.

Recommended: (a). The claim the deal would reserve is the thing to judge, and one call
answers it. It would move to (b) if a listing whose advertised quantity is taken must
stop selling at once and not at its next reconciliation.

The declared-match half is unchanged either way.

### Q4 — The window the probe asks for

A probe with a window counts the holds that overlap it; with none it counts every hold.
In a seller's round a per-period deal has no resolved horizon yet.

- (a) The window acceptance would resolve at this instant: the buyer's requested
  duration, or the horizon `resolve_acceptance` would bind now. The probe then asks
  what the reserve will ask.
- (b) No window. A shape that would fit beside a later reservation is refused.
- (c) One billing period. A deal whose later periods collide with another reservation
  is agreed and then refused at settlement.

Recommended: (a). On a buyer's or an administrator's acceptance the question is asked
once the acceptance instant and horizon are fixed, so the probe's window is the
Agreement's. It would move to (b) if resolving a horizon in a round proves to need
state the round does not have.

### Q5 — The hook's shape, and when in a round the site is asked

Today the runtime calls the hook once before the policy chain, with no terms, and the
chain's `has_matching_inventory_guard` reads that verdict at its place in the chain. A
round's effective shape exists only once the domain's evaluation has merged a partial
opening and judged admissibility (D5).

```python
# Today.
verdict = await hooks.check_listing_source(repository, resolved)
evaluation = await hooks.evaluate_round(request_with(verdict))

# (a) One call, after evaluation.
evaluation = await hooks.evaluate_round(request)
verdict = await hooks.check_listing_source(repository, resolved, evaluation.agreed_terms)

# (b) Two calls: the declaration before the chain, availability after evaluation.
declared = await hooks.check_listing_source(repository, resolved, None)
evaluation = await hooks.evaluate_round(request_with(declared))
verdict = await hooks.check_listing_source(repository, resolved, evaluation.agreed_terms)

# (c) One call before the chain; the domain's check resolves the shape itself.
verdict = await hooks.check_listing_source(repository, resolved, decoded_terms)
evaluation = await hooks.evaluate_round(request_with(verdict))
```

- (a) The guard has no verdict when the chain runs and becomes a name the runtime
  ignores. A declared mismatch is found after the seller has priced.
- (b) The guard keeps its place. The site is asked only for a decision that would
  counter or accept, the decisions the verdict applies to today; a decision that
  rejects or exits for its own reason asks nothing. The seller prices before the site
  is asked, so the companion's evaluation order, which places feasibility before the
  commercial guard and pricing, is restated.
- (c) The order of the companion stands. The domain's check repeats the shape
  resolution and admissibility that its evaluation performs.

Callers of the hook, each of which must be able to ask through it alone:

| Caller | What it has when it asks |
|---|---|
| An opening and a buyer's counter | The decoded terms before evaluation; the effective terms after it |
| A buyer's acceptance | The terms recorded with the seller's last quote |
| An administrator's acceptance | The same |
| The administrator's opening preview | As an opening; it writes nothing, and a probe reserves nothing |
| `has_matching_inventory_guard` | The verdict obtained before the chain |
| API credits | Contributes no check; unaffected |

Recommended: (b). It keeps the guard and D5, and it asks the site nothing for a round
the seller rejects for its own reasons. It would move to (c) if the evaluation order
must stay as the companion states it.

`market-composition`'s "Kit-owned synchronous negotiation runtime" says the runtime
obtains the verdict before every seller decision; under (a) or (b) its wording changes.

### Q6 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Requirements this change modifies**, their deltas written once Q1 to Q5 settle:
  `negotiation-protocol`'s "A round may revise the capacity shape", whose last sentences
  and scenario "A revised shape exceeds the advertised shape" state the cap;
  `storefront-publication`'s "The seller's inventory guard checks a listing against its
  own source", whose second paragraph states what availability asks; and
  `storefront-publication`'s "Bare-metal opening rechecks its listing against its
  source", whose availability paragraph reads the held projection. `market-composition`'s
  "Kit-owned synchronous negotiation runtime" only if Q5 changes when the verdict is
  obtained. No `site-capacity` requirement changes.
- **The requirement this change adds**, to `negotiation-protocol`: "Authoritative
  capacity verification before agreement". It states D1, D3 and D4 for a capacity-backed
  listing: the seller asks its site about the claim the round would reserve, the
  question reserves nothing, and the answer guarantees nothing at settlement.
- **The refusal a buyer reads.** `no_matching_inventory`, which the availability half
  answers with today. Whether a requested shape the site would not admit has a reason
  of its own follows Q1, with `shape_exceeds_advertised`.
- **Where the call lives.** A probe on the guarded capacity path, `CapacityEffects`,
  pinned to the binding's site and asked of the backing delegate, beside reserve and
  commit.
- **The administrator's settle dry-run** uses the same pinned probe in place of the
  aggregate's ranked one. It is a small related fix this change absorbs.
- **A thread that holds a reservation.** Its own hold would count against its probe.
  No thread holds one before acceptance today. `negotiation-time-capacity-hold` judges
  such a thread by resizing its reservation, and states so in its own design.
- **No retry within a round.** A refusal is reported at once; a buyer retries.
- **A counter-offer naming what the site could serve** is deferred. The probe returns
  one match, not a range. It is revisited when `publish-shape-bounds` gives a buyer a
  range to counter within.
- **Companion text.** The `negotiation-protocol` companion's "Evaluation order" and
  "Current limits" stop saying feasibility is not composed. The `storefront-publication`
  companion says what availability asks. `docs/development/ARCHITECTURE.md`, "Capacity
  reservation", gains the probe between reading snapshots and the settlement reserve,
  and "Discovery and negotiation" loses the cap as a stand-in.
- **Test levels.** The runtime's handling of the hook is proven once, in
  `kit/negotiation-runtime`'s unit suite with opaque hooks
  (`openspec/specs/negotiation-protocol/testing.md`). Each storefront proves its check
  at application integration against a site ledger composed in process. One row in each
  compute lane, on mock provisioning: a claim the site would not admit is refused in
  negotiation, and in the VM lane a shape above the advertised one is agreed where the
  site admits it.
- **Hardware.** Nothing here needs a GPU, and nothing touches the Ansible layer or how
  an adapter executes it, so no real-host run is owed.
- **Documents.** `docs/configuration.md`'s row for `has_matching_inventory_guard`, and
  the configuration reference's sentence on an offer alone if Q1 settles on (b).

### Q7 — Implementation cadence

Recommended: one round, one session. The hook and the pinned probe, both storefronts'
checks, the cap's change under Q1, the lane rows and the documents are one slice: none
is useful without the others.

## Verification

Provisional levels are in Q6. Every lane row is mock-provisioning evidence.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 the seller asks the site about the claim a round would reserve | `openspec/specs/negotiation-protocol/spec.md` and `architecture.md`; `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" and "Capacity reservation" |
| D2 the availability half of the listing-source check | `openspec/specs/storefront-publication/spec.md` and `architecture.md`; `docs/configuration.md` |
| D3 a probe, not a hold | `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order" |
| D4 advisory, the race accepted | `openspec/specs/negotiation-protocol/spec.md` |
| D5 admissibility before the site | `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order" |
| D6 the site unchanged, only the listing's own site asked | `openspec/specs/storefront-publication/spec.md`; `docs/development/ARCHITECTURE.md`, "Storefront capacity boundary" |
| D7 the source check's outcomes | `openspec/specs/storefront-publication/spec.md` |
| D8 nothing gates the change | None |
| D9 the change is Goal 2's | `docs/development/ROADMAP.md`, Goal 2 |
| D10 the site authority package dependency is not decided here | None; the change index holds it |
