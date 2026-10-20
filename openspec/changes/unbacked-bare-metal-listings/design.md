# Design — unbacked bare-metal listings

## Context

Split out while designing `publish-indicative-listing-rates`, when it became clear
that Goal 7's primary target domain had no owner for the supply the goal exists to
serve. `bare-metal-publication-reads-pool-declarations` refuses unbacked pools and
records unbacked bare metal as a question with no owner; this change is that owner.

A design review on 2026-10-14, against the tree after
`bare-metal-mock-provisioned-deal` (archived 2026-10-09) and
`pools-9-retire-local-physical-authority` (archived 2026-10-13), revised two of the
original decisions and opened the questions listed at the end, all since decided. Its first outcome is a
prerequisite change, `encapsulate-capacity-backing`.

## Decisions

### Backing is decided by one delegate both domains share

Unbacked listings already exist for VM through `kit/capacity-publication`
(a `PublicationBinding` carrying the unbacked delegate, source reconciliation scoped to
every listing, capacity reconciliation scoped by the delegate) and `kit/resource-pools`'s
declaration reader. Introductions settle through the composition
`compose-contact-exchange-across-compute` promoted into the mechanism kit, so the two
domains share one implementation of accepted-state interpretation and one per-origin
contact resolution.

The review found that adopting those kits is not enough: every consumer still decides
what backing means by comparing the label, and VM and bare metal already disagree
about it. Bare metal handling unbacked supply by adding its own branches would
duplicate each decision. So `encapsulate-capacity-backing` first gathers every
decision that differs between backed and unbacked supply into one backing delegate,
selected by the pool's `capacity_backing` label, and moves VM and bare metal onto it,
unifying where they diverge. This change then makes bare metal accept unbacked pools,
with no bare-metal branch on backing: what differs is the delegate's.

### Identity is the site and the Physical Resource; host fields are optional when unbacked

An unbacked listing's derivation identity is its site and Physical Resource, the same
identity a backed listing has, with `host_id` and `physical_host_id` absent because
nothing delivers a host for unbacked supply. This is the resource-granular identity VM
adopted when capacity stopped requiring hosts, applied to bare metal unchanged. The
payload is decided under "Delivery terms are the delegate's decision".

### The site emits the bare-metal view for unbacked supply

Decided in the 2026-10-14 review, replacing the original decision that an unbacked
candidate is derived from the capacity declaration rather than from a `bare_metal.v2`
publication view.

The site emits a resource's `bare_metal.v2` view only when its declaration enables
bare-metal publication and names a host, and the bare-metal storefront ignores a
resource without the view. A host-less unbacked declaration is therefore invisible to
bare-metal publication today. Rather than have the storefront read unbacked resources
around the view, the site emits the view for a resource in an unbacked pool, host or
no host. Building the view asks the pool's backing delegate what stands behind the
resource: a backed resource's view carries its host identity and availability; an
unbacked resource's view carries neither. Nothing is fabricated: the view omits what
the delegate says is not there, which is what the original decision's objection to a
"fabricated physical view" was guarding against. The view-building logic is
compute-family code shared with the site's other views and consumes the delegate; it
holds no backing branch of its own.

Consequences, also decided:

- The resource's own `bare_metal_publication` declaration attribute remains the
  opt-in for backed and unbacked pools alike, and it is where the view's access
  methods and capabilities come from. An unbacked pool advertising bare metal lists
  only the resources that enable it, as a backed pool does. Its access methods are
  a delivery term, so an unbacked listing does not publish them (see "Delivery terms
  are the delegate's decision").
- An unbacked resource is never judged against availability: an enabled, shaped
  resource is a candidate and a disabled one is withdrawn. It never closes as
  unavailable. This is the delegate's decision, consistent with an unbacked listing
  being inexhaustible.
- The region, asking-rate, and override holds apply to an unbacked pool exactly as to
  a backed one, and the shape rules — exactly one `units`, a GPU count and model —
  are unchanged.

### The site's views receive the pool's delegate here

`encapsulate-capacity-backing` leaves the site's publication views alone, because no
view reads backing until this change publishes an unbacked one. This change therefore
gives views the pool's delegate:

- `InventoryViewProjection.resource_views` receives the pool's context — its provider
  and its resolved declarations, the backing delegate among them — where today it
  receives only the declaration and its pool ID. The provisioning service's resource
  pass resolves each declaration's pool from the pool rows its metadata pass already
  reads; that is the provisioning composition reading its own pools, not a new
  `kit/site` read of pool state.
- The view carries the resource's delivery terms only as the delegate's
  `carry_delivery_terms` passes them (see "Delivery terms are the delegate's
  decision"): a backed resource's view carries its host identity, access methods, and
  availability; an unbacked resource's carries none of them.
- Bare metal's view builder consumes it, so its rule that a declaration naming no host
  gets no view becomes the delegate's decision rather than a branch of its own.

### Delivery terms are the delegate's decision

Some fields of a listing commit the marketplace to delivering something: on a backed
listing it stands behind them, and on an unbacked one nothing does, and neither the
storefront nor the site could verify them. These are delivery terms. Whether a
listing carries them is the backing delegate's decision, through two domain-neutral
operations a domain applies to the fields it names as delivery terms:

- `carry_delivery_terms(terms)`, used where the site builds a publication view: a
  backed delegate passes the terms through, an unbacked delegate carries none.
- `delivery_term_constraints(terms)`, used by a listing model's validation: a backed
  delegate requires every term present and non-empty, an unbacked delegate requires
  every term absent.

Bare metal names `host_id`, `physical_host_id`, `access_methods`, and, on the view,
`available` as its delivery terms. The payload model holds no backing knowledge, and
its rule is that the terms are absent exactly when the listing is unbacked:

| Field | Backed listing | Unbacked listing |
|---|---|---|
| `capacity_backing` | `backed` | `unbacked` |
| `host_id`, `physical_host_id` | required | absent, even where the declaration names a host |
| `access_methods` | required, non-empty, as declared | absent |
| hardware, region, `asking_rate`, durations | as today | as today |

The `["ssh"]` default for `access_methods` is removed: an absent field makes no
commitment, and a default would publish one nothing stands behind. A backed listing
still always carries its declared list, so its behaviour is unchanged. Hardware,
region, rate, and durations remain the seller's description of the supply and its
terms, not a delivery commitment. Rejected: publishing a declared host or access
methods on an unbacked listing, which would read as a machine and access the
marketplace delivers.

`capacity_backing` is the buyer-visible indicator. The compute registry schema filters
it exactly, and every buyer CLI compiles its resource query from that schema, so a
buyer can already ask for `capacity_backing=unbacked`. Nothing proves that across
running services yet, so this change's end-to-end evidence includes it.

Every remaining reader of the host fields is on a path an unbacked listing cannot
reach — escrow negotiation, accepted terms, and settlement verification are reached
only through stages that deliver through capacity, which publication never offers an
unbacked listing, and capacity effects are refused by the delegate's admission guard —
except the fulfillment routes' context loader (open question 5).

### A candidate with no settlement option yields no listing

The prerequisite's settlement admissibility already drops, from an unbacked candidate,
every option whose mechanism bare metal fulfils through capacity, with an operator
notice, and yields no listing for an unbacked candidate left with none. Contact
exchange publishes no option for an origin site with no configured contact, so an
unbacked pool at such a site yields no listing.

Bare-metal publication also accepts a payload with no settlement option and no
accepted escrow today, and publishes a listing nobody can buy, where VM refuses the
candidate. This change makes bare-metal publication refuse any candidate, backed or
unbacked, whose payload carries neither, recording a `refuse` entry in the publication
report that names the candidate and the readiness blockers. Unbacked supply makes the
case likely — a contact-only candidate whose origin has no contact — and the check sits
on the payload path this change edits.

### An unbacked listing's recheck reads its held projection, never availability

`storefront-publication`'s inventory guard says the storefront must neither consult
availability nor contact a site authority for an unbacked listing. Bare metal's recheck
fetched its site's live projection, so this change first decided to scope that rule,
letting an unbacked recheck read its origin site's declarations and accepting that its
openings would be refused as retryable while the site was unreachable.

Superseded on 2026-10-14, after `encapsulate-capacity-backing` was implemented:
`share-site-projection-state` gives bare metal the per-site projections VM holds, and
its opening recheck reads the projection it holds for the listing's site. The inventory
guard is unchanged, and this change carries no delta for it. The recheck goes through
the binding's delegate, whose `judge` never asks availability of an unbacked listing, so
an unbacked listing is refused only by its declaration: its shape, region, or Physical
Resource, or its resource now in a pool other than its bound one. Provenance is the only
check an unbacked listing gets, so the bound pool is tested explicitly. A site whose
projection the storefront does not hold refuses openings as retryable for either
backing.

### A deal settled by introduction has no fulfillment

An unbacked binding keeps its Physical Resource as its source, so the bare-metal
fulfillment routes load its context; they then answer 409 "settlement is not
authoritatively verified" because introduction evidence carries no delivery — the same
answer a backed listing settled by introduction gets today, wrong in meaning because
the introduction is verified and there is simply no fulfillment. On a storefront
composed for introductions only, building the fulfillment service fails first and the
routes answer 500.

Since `encapsulate-capacity-backing`, every fulfillment effect passes `CapacityEffects`,
whose guard refuses an unbacked binding before any site call, so the guard is a
backstop for this decision rather than its mechanism.

Decided: the fulfillment routes resolve the deal's accepted seller stage first, the
entry settlement uses, and when it does not fulfil through capacity they answer 404,
naming that the deal settled by introduction and has no fulfillment, before building
the fulfillment service or loading a fulfillment context. The deciding fact is the
mechanism's, not the listing's backing, because an introduction has no fulfillment
whatever its listing's backing; no unbacked deal reaches fulfillment, since contact
exchange is the only option admissibility leaves an unbacked listing. Delivery routes
for a stage that fulfils through capacity are unchanged.

### The bare-metal evidence is VM's introduction scenario, stage for stage

Decided with the maintainer:

- A new bare-metal lane scenario, `e2e_bare_metal_unbacked_introduction`, runs VM's
  Goal 7 introduction scenario stage for stage and adds what this change introduces:
  - supply: a backed pool with a host-bearing declaration and a rate; an unbacked pool
    (no deliverable mode, advertising `bare_metal`, a configuration-free provider)
    with a host-less declaration that enables bare-metal publication and a rate; and a
    listing that publishes no rate. Contact settlement reaches the unbacked pool
    through a storefront pool override, as in VM's scenario, so the lane's default
    clauses and the mock deal are untouched;
  - discovery through the buyer CLI: a rate-bounded `market bare-metal list` returns
    the backed and unbacked listings together and excludes the one without a rate, and
    a `capacity_backing=unbacked` query returns only the unbacked one;
  - the unbacked listing publishes `capacity_backing: unbacked`, no host fields, no
    `access_methods`, and exactly `contact-exchange.v1`;
  - the reveal through the buyer CLI, with the buyer's file sink receiving the seller's
    contact, and seller-side delivery reaching the lane's mail sink;
  - the fulfillment status route answering 404 for the introduction deal.
- The bare-metal lane gains a mail sink and the storefront's delivery configuration
  for a `seller-mail` SMTP sink.
- The stages both domains run identically move into a shared introduction stage
  module, each domain supplying a driver for supply seeding and its CLI verbs, as the
  compute deal stages already do; VM's introduction scenario moves onto it.
- Both buyer plugins register a root-level `settlement` command group, and the core
  buyer application adds every installed domain's commands without a duplicate check,
  so with both plugins installed one domain's `settlement contact introduce` runs the
  other's recovery. Bare metal's settlement group moves under `market bare-metal`,
  beside its `request-introduction`, and the core buyer application refuses at
  startup a root command name two installed domains register, naming both. VM's
  root-level commands stay.
  Seen in the pipeline: on `feat/orchestrate-change-workflow`, run `39294620474`'s
  e2e-vm lane failed `test_vm_introduction.py::TestStage02_Reveal::test_04_the_buyer_cli_negotiates_and_reveals`,
  the VM buyer's `settlement contact introduce` reaching bare metal's config loader
  (`bare-metal buyer config is required via BARE_METAL_BUYER_CONFIG`). The rerun on
  the next commit, run `39302015924`, passed with no product change between them:
  the collision is intermittent on CI, decided by the order the image's entry points
  are discovered.
- The existing backed bare-metal introduction scenario stays: its retention and
  operator-deletion coverage is independent of backing.
- There is no Helm evidence for bare metal in this change. The bare-metal chart
  forwards no registry, publication clauses, or delivery configuration, so a
  chart-deployed bare-metal storefront cannot publish at all; that is chart work,
  recorded with the chart item in `resolve-compute-family-findings`. An introduction
  involves no provisioning, so the lane's mock provisioning profile does not weaken
  this evidence.

### Permanent documentation

Decided with the maintainer (review question 6). Spec deltas this change carries:

- `storefront-publication`: remove "An unbacked pool yields no bare-metal listing";
  add "Bare-metal publication derives unbacked listings", written to the decisions
  above; scope "A bare-metal listing sells one whole unit" to capacity-backed
  listings; scope the availability refusal in "Bare-metal opening rechecks its listing
  against its source" to capacity-backed listings, written on the held-projection text
  `share-site-projection-state` gives it; add requirements that a bare-metal listing carries
  delivery terms only when backed, that a bare-metal candidate with no settlement
  option yields no listing, and that a deal settled by introduction has no
  fulfillment.
- `physical-provisioning`: "A bare-metal publication view is built from its capacity
  declaration" carries delivery terms only as the pool's delegate passes them; "Domains
  contribute their inventory views" gives resource views the pool's context.
- `resource-pool-management`: "Capacity backing is interpreted by one delegate",
  which the prerequisite made permanent, modified to name delivery terms among the
  delegate's decisions and to state the two delivery-term operations. A separate
  requirement beside it would leave its list of the delegate's decisions incomplete.
- `registry-discovery`: "Compute listings publish their capacity backing" publishes a
  bare-metal listing's binding backing, backed or unbacked.

Promotion at closeout: the publication architecture companion's bare-metal passages
(candidates, the backed-only statement, the one-unit commitment, and the recheck with
its held-projection end state); `ARCHITECTURE.md`'s bare-metal commitment sentence;
the bare-metal seller quickstart's unbacked passage, rewritten as how to list unbacked
machines; `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` for the evidence and topology;
the roadmap's Goal 7 and the change index at completion.

### Goal 7 closes on single-site evidence

This change was assigned the live two-seller scenario — two seller sites behind one
storefront, each revealing its own seller's contact and receiving only its own
seller-side delivery, on both lanes. The topology that supports it today is one
registry with several storefronts, each holding its own site, where each storefront
reveals its own seller's contact by construction. One storefront serving several sites
is a capability of its own, weeks of work, and not yet a goal; the lesser goal for
service-to-service trust and event delivery would precede it.

Decided with the maintainer: Goal 7 delivers without the scenario. It is withdrawn
from this change and recorded as unowned in the change index, for both domains, to be
taken up by whichever change makes one storefront serve several sites. The per-origin
contact resolution and delivery routing it would exercise remain proven at
integration level.

### Negotiation and settlement compose the existing kit runtimes

Negotiation and settlement for an unbacked bare-metal listing sit on the kit
negotiation runtime and settlement composition that `bare-metal-mock-provisioned-deal`
(archived) composed for bare metal. Settlement, the introduction reveal, per-origin
contact resolution, seller-side delivery, and retention key only on the listing's
origin site and need no change.

The original decision called this "a publication change" relying on that composition
for the rest. The review found pieces outside publication that neither change owns —
the opening source check, the capacity-effect guards, and the listing payload's
readers — each decided above.

### Bare metal publishes on a loop over held projections first

Decided with the maintainer on 2026-10-14. An unbacked listing is never judged against
availability, so source reconciliation is the only reconciliation it gets, and
bare-metal publication ran only when an operator invoked it: an unbacked listing whose
pool was withdrawn would stay advertised until someone ran it. Bare metal shares VM's
per-site projection state and publication loop controller instead, through a new
prerequisite, `share-site-projection-state`, carved out of
`kit-owned-listing-and-fulfillment-lifecycles`. This change depends on it. Rejected: a
version watch inside bare metal's publication, which would satisfy the loop's wake but
keep two projection routes and the live recheck.

### This change removes bare metal's temporary refusal of unbacked pools

`encapsulate-capacity-backing` moves every backing decision into the backing delegate
except one: bare-metal publication's refusal of an unbacked pool. It keeps that refusal
deliberately, as an explicit and tested comparison of the pool's backing label in
bare-metal publication's pool reading, because it adds no unbacked bare-metal supply
and the delegate cannot express the refusal — bare metal composes contact exchange, so
the delegate's settlement admissibility would otherwise publish a contact-only
unbacked listing. It is the only comparison of the label that change leaves in the
tree.

This change deletes that check and its `pool_unbacked` report, after which bare metal
derives listings from every enabled pool advertising `bare_metal` whatever its
backing, like every other domain, and nothing outside the delegate compares the label.
No other mechanism replaces it.

## Open questions

Questions 1 to 10, the 2026-10-14 review's and two raised the same day, were each decided
with the maintainer, and those decisions stand. Questions 11, raised 2026-10-19, and 12,
raised 2026-10-20, are open and are to be designed here.

1. **The unbacked listing payload.** Decided: "Delivery terms are the delegate's
   decision".
2. **Backing on refresh and reopen.** Settled by the prerequisite: every domain,
   bare metal included, applies one shared backing comparison first on every refresh,
   reopen, and source check, and backing is no longer a bare-metal term field
   (`encapsulate-capacity-backing`, "Divergence: backing disagreement on refresh and
   reopen"). Nothing further is owed here.
3. **Settlement options for unbacked listings.** Decided: "A candidate with no
   settlement option yields no listing".
4. **The opening source check.** Decided, then revised by question 9: "An unbacked
   listing's recheck reads its held projection, never availability".
5. **The fulfillment routes for an unbacked deal.** Decided: "A deal settled by
   introduction has no fulfillment".
6. **The permanent documentation delta.** Decided: see "Permanent documentation".
7. **The bare-metal system evidence.** Decided: "The bare-metal evidence is VM's
   introduction scenario, stage for stage".
8. **The two-seller topology for both lanes.** Decided: "Goal 7 closes on
   single-site evidence".
9. **Source reconciliation without an operator.** Raised 2026-10-14 after the
   prerequisite was implemented. Decided: "Bare metal publishes on a loop over held
   projections first", which also supersedes the scoped recheck in question 4.
10. **The resource-pool delta's form.** Raised the same day. Decided: a modification of
    the now-permanent delegate requirement ("Permanent documentation").
11. **Defects a local Helm deployment exposed.** Raised 2026-10-19 by
    share-site-projection-state's local Helm run, which deployed bare metal beside Bob as
    a second release of the umbrella publishing to the first release's registry. Each
    predates that change and is to be designed here; none is decided:
    1. A stored resource pool whose provider no registered handler serves makes the
       provisioning service's pool read fail with an unhandled 500 that carries no
       response signature, so the typed client reports missing response authentication
       rather than the pool's problem; and the service's startup does not refuse the
       row. Whether startup refuses it, the read reports it per pool, or both, is open.
    2. The VM storefront chart's `wait-for-registry` init container
       (`helm/charts/storefront/templates/deployment.yaml`) polls the registry's
       `/health` with a `wget` that has no timeout, so one request hung across a
       registry restart and the pod never started.
    3. Stage events record the negotiation id as their `listing_id` when an entry
       names no listing (the fallback in `core/storefront/src/core_storefront/stage_log.py`),
       so a stage-event reader cannot tell a listing from a negotiation.
    4. Helm test pods carry their Deployment's selector labels, so a selector-based
       `kubectl logs` or `kubectl exec` finds the test pod beside the service's.
    5. A VM deal Helm test that fails leaves Bob's loops paused: nothing resumes them
       on failure.
    6. Bare metal logs its notice that a pool states no region on every publication
       cycle; VM logs its derivation warnings once per projection generation.
12. **Settlement questions left open by `share-site-projection-state`.** Raised
    2026-10-20 by that change's closeout, which moved them here from its archived
    [open questions](../archive/2026-10-19-share-site-projection-state/design.md#open-questions); each was raised during its
    implementation and none is decided. The owner resolves each during this change's
    design, as a new change or as an implementation here:
    1. A storefront whose `[Settlement].alkahest` `oracle_gated` release model names no
       trusted oracle, or names the seller wallet as its oracle, starts and then refuses
       every Alkahest candidate. Whether these are startup refusals, as an undeliverable
       release model already is, is open.
    2. A storefront with an empty seller wallet still derives and publishes a recipient
       release condition with no recipient, which every deal then refuses as
       `release_condition_unreadable`. Whether startup or publication refuses it instead
       is open.
    3. An Alkahest escrow proposal that pins no escrow address (the zero address) may
       name any token: the escrow-shape guard skips it and release authorization does not
       read it. Whether such a proposal's token is checked, and against what, is open.
    4. Seller verification, bare metal's acceptance, and the API-credit settle path
       re-derive the release conditions from the listing as it is stored when they run,
       so a deal whose listing's conditions changed after acceptance fails them closed,
       while the VM refund reads the accepted settlement plan. Whether a deal is checked
       against its listing as it is now or as it was accepted is open.
    5. A resumed buyer run that holds only an accepted proposal refuses
       (`escrow_release_condition_missing`), while one that holds the seller's accepted
       escrow terms creates the escrow from them unchecked. Recording the listing's
       release conditions in the buyer's run log would let both be checked.
    6. Only the VM buyer's selection path checks the seller's accepted escrow terms
       against the listing (`validate_selected_escrow_plan`); the shared buyer
       orchestration creates the escrow unchecked for the API-credit buyer and for VM's
       proposal path. Checking every path needs a domain hook, since `core/buyer` cannot
       import `kit/alkahest`.
