# Design — unbacked bare-metal listings

## Context

Split out while designing `publish-indicative-listing-rates`, when it became clear
that Goal 7's primary target domain had no owner for the supply the goal exists to
serve. `bare-metal-publication-reads-pool-declarations` refuses unbacked pools and
records unbacked bare metal as a question with no owner; this change is that owner.

A design review on 2026-10-14, against the tree after
`bare-metal-mock-provisioned-deal` (archived 2026-10-09) and
`pools-9-retire-local-physical-authority` (archived 2026-10-13), revised two of the
original decisions and opened the questions listed at the end. Its first outcome is a
prerequisite change, `encapsulate-capacity-backing`.

## Decisions

### Backing is decided by one delegate both domains share

Unbacked listings already exist for VM through `kit/capacity-publication`
(`UnbackedBinding`, source reconciliation scoped to every listing, capacity
reconciliation scoped to backed listings) and `kit/resource-pools`'s declaration
reader. Introductions settle through the composition
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

### An unbacked listing's recheck reads declarations, never availability

`storefront-publication`'s inventory guard says the storefront must neither consult
availability nor contact a site authority for an unbacked listing, while bare metal's
recheck reads its site's live projection. The "no site call" half generalized VM's
mechanics — VM's guard reads the projection its storefront holds — into a rule; what
the rule protects is that an unbacked listing's origin site is not an admission
authority, so nothing about capacity is asked of it. The origin site is still the
authority for the declaration the listing derives from, and source reconciliation
already reads it.

Decided: the guard requirement is scoped to what it protects. For an unbacked
listing the storefront must not consult availability, and it may read the declarations
it compares against from the listing's origin site. "Bare-metal opening rechecks its
listing against its source" applies its availability refusal to capacity-backed
listings only; an unreachable or unverifiable site remains a retryable refusal for both
backings. While its origin site is unreachable, an unbacked bare-metal listing's
openings are therefore refused as retryable, where VM answers from the projection it
holds.

The preferred end state is a storefront that reads the projections it holds rather
than calling a site, for every domain. Moving bare metal onto held projections is out
of scope here; it belongs with the extraction of VM's held per-site projection state
into the kit (`kit-owned-listing-and-fulfillment-lifecycles`) and the projection item
in `resolve-compute-family-findings`. The scoped requirement holds unchanged once it
lands, and the retryable refusal during a site outage goes away.

### A deal settled by introduction has no fulfillment

An unbacked binding keeps its Physical Resource as its source, so the bare-metal
fulfillment routes load its context; they then answer 409 "settlement is not
authoritatively verified" because introduction evidence carries no delivery — the same
answer a backed listing settled by introduction gets today, wrong in meaning because
the introduction is verified and there is simply no fulfillment. On a storefront
composed for introductions only, building the fulfillment service fails first and the
routes answer 500.

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
  against its source" to capacity-backed listings; scope the inventory guard's
  unbacked rule to availability; add requirements that a bare-metal listing carries
  delivery terms only when backed, that a bare-metal candidate with no settlement
  option yields no listing, and that a deal settled by introduction has no
  fulfillment.
- `physical-provisioning`: "A bare-metal publication view is built from its capacity
  declaration" carries delivery terms only as the pool's delegate passes them; "Domains
  contribute their inventory views" gives resource views the pool's context.
- `resource-pool-management`: the delegate requirement the prerequisite adds gains
  the delivery-term decisions.
- `registry-discovery`: "Compute listings publish their capacity backing" publishes a
  bare-metal listing's binding backing, backed or unbacked.

Promotion at closeout: the publication architecture companion's bare-metal passages
(candidates, the backed-only statement, the one-unit commitment, and the recheck with
its held-projection end state); `ARCHITECTURE.md`'s bare-metal commitment sentence;
the bare-metal seller quickstart's unbacked passage, rewritten as how to list unbacked
machines; `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` for the evidence and topology;
the roadmap's Goal 7 and the change index at completion.

### Negotiation and settlement compose the existing kit runtimes

Negotiation and settlement for an unbacked bare-metal listing sit on the kit
negotiation runtime and settlement composition that `bare-metal-mock-provisioned-deal`
(archived) composed for bare metal. Settlement, the introduction reveal, per-origin
contact resolution, seller-side delivery, and retention key only on the listing's
origin site and need no change.

The original decision called this "a publication change" relying on that composition
for the rest. The review found pieces outside publication that neither change owns —
the opening source check, the capacity-effect guards, and the listing payload's
readers — which are open below.

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

From the 2026-10-14 review. Each is to be decided with the maintainer, after the
prerequisite's delegate operations are known where it depends on them, and recorded
here as a decision.

1. **The unbacked listing payload.** Decided: "Delivery terms are the delegate's
   decision".
2. **Backing on refresh and reopen.** Settled by the prerequisite: every domain,
   bare metal included, applies one shared backing comparison first on every refresh,
   reopen, and source check, and backing is no longer a bare-metal term field
   (`encapsulate-capacity-backing`, "Divergence: backing disagreement on refresh and
   reopen"). Nothing further is owed here.
3. **Settlement options for unbacked listings.** Decided: "A candidate with no
   settlement option yields no listing".
4. **The opening source check.** Decided: "An unbacked listing's recheck reads
   declarations, never availability".
5. **The fulfillment routes for an unbacked deal.** Decided: "A deal settled by
   introduction has no fulfillment".
6. **The permanent documentation delta.** Decided: see "Permanent documentation".
7. **The bare-metal system evidence.** Decided: "The bare-metal evidence is VM's
   introduction scenario, stage for stage".
8. **The two-seller topology for both lanes (task 2.2).** Adding a second site to
   either existing lane breaks single-site assertions and configuration. Decide the
   topology, and whether it stays in this change.
