# Design — unbacked bare-metal listings

## Context

Split out while designing `publish-indicative-listing-rates`, when it became clear
that Goal 7's primary target domain had no owner for the supply the goal exists to
serve. `bare-metal-publication-reads-pool-declarations` refuses unbacked pools and
records unbacked bare metal as a question with no owner; this change is that owner.

A design review on 2026-10-14 revised two of the original decisions and opened eight
questions, all decided with the maintainer; its first outcome was the prerequisite
`encapsulate-capacity-backing`, and a later question produced the second,
`share-site-projection-state`. Both are archived.

The change returned to design on 2026-10-20 for two sets of carried-in items: six
pre-existing defects a local Helm deployment of bare metal beside Bob exposed, and six
Alkahest settlement questions moved here by `share-site-projection-state`'s closeout.
The maintainer chose to design and fix them here rather than hand them on again, so the
change carries four groups of work:

- **A. Unbacked bare metal**, the change's purpose, and the places where designing it
  showed VM and bare metal diverging without reason.
- **B. Alkahest settlement inputs**: what a seller verifies against, what a buyer funds,
  which proposals are accepted, and what an unusable Alkahest configuration does.
- **C. Deployment and test hygiene**: the VM storefront chart's dependency waits, Helm
  test-pod labels, and end-to-end scenarios that pause shared services.
- **D. The provisioning service**: stored pools whose provider no handler serves, and
  failures after authentication.

One carried-in defect, stage events recording a negotiation as their listing, is handed
to a follow-up change (decision 24).

The design review of 2026-10-20 and its triage revised decisions
4, 5, 6, 7, 9, 10, 16, 17, 19, 20, 23, and 25: an Alkahest chain probe now produces the
reachability the hold relies on, a listing is held while any mechanism is unknown, the
storefronts' own dependency preflights go with the init containers, and the placement of
the pool context and the introduction refusal follows each package's responsibility.

Its second round and triage revised decisions 4, 7, 19, and 25: the chain probe and the
client map it rebuilds belong to `kit/alkahest` as a loop each storefront registers, API
credits' seed waits for its dependencies and its CLI goes through the running storefront,
a listing is classified only by the mechanisms its candidate could publish, `kit/site`
carries the view problems it does not read, and a rollout's brief mixed-version window is
recorded as a hold.

Planning re-verifies against the tree the facts each decision marks as "planning
confirms".

## Decisions

### A. Unbacked bare metal

#### 1. Backing is decided by one delegate both domains share

Unbacked listings already exist for VM through `kit/capacity-publication` (a
`PublicationBinding` carrying the unbacked delegate, source reconciliation scoped to
every listing, capacity reconciliation scoped by the delegate) and `kit/resource-pools`'s
declaration reader. Introductions settle through the composition the mechanism kit owns,
so both domains share one implementation of accepted-state interpretation and one
per-origin contact resolution.

Every decision that differs between backed and unbacked supply belongs to the backing
delegate `encapsulate-capacity-backing` introduced. This change makes bare metal accept
unbacked pools with no bare-metal branch on backing: what differs is the delegate's. No
consumer compares the label to make a backing decision; each is asked of the delegate.
Equality checks that decide nothing by backing remain — the pool's immutable
`capacity_backing` tag, `backing_changed`'s comparison of a binding's delegate with its
source's, and the binding column's `CHECK` constraint.

#### 2. Identity is the site and the Physical Resource; host fields are absent when unbacked

An unbacked listing's derivation identity is its site and Physical Resource, the same
identity a backed listing has, with `host_id` and `physical_host_id` absent because
nothing delivers a host for unbacked supply. This is the resource-granular identity VM
adopted when capacity stopped requiring hosts. An unbacked candidate's source envelope
and comparison sets carry no host fields.

#### 3. The site emits the bare-metal view for unbacked supply

The site emits a resource's `bare_metal.v2` view when its declaration enables bare-metal
publication, for a resource in an unbacked pool host or no host. Building the view asks
the pool's backing delegate what stands behind the resource: a backed resource's view
carries its host identity and availability; an unbacked resource's view carries neither.
Nothing is fabricated: the view omits what the delegate says is not there.

- The resource's own `bare_metal_publication` declaration attribute remains the opt-in
  for backed and unbacked pools alike, and is where the view's access methods and
  capabilities come from.
- An unbacked resource is never judged against availability: an enabled, shaped resource
  is a candidate and a disabled one is withdrawn. It never closes as unavailable.
- The region, asking-rate, and override holds apply to an unbacked pool exactly as to a
  backed one, and the shape rules — exactly one `units`, a GPU count and model — are
  unchanged.

Rejected: deriving an unbacked candidate from the capacity declaration rather than from a
view, which would give the storefront a second way to read unbacked resources around the
view.

#### 4. Resource views receive their pool's context and never fail the projection

`InventoryViewProjection.resource_views` receives the context of the resource's pool —
its provider and its resolved declarations, the backing delegate among them — where it
received only the declaration and its pool ID. Building a resource's view with its pool's
context is compute-family work, so it sits where the contributed-view seam already is, and
nothing above the compute family learns of it:

- `compute_provisioning` (`inventory_views.py`), which owns the protocol and its
  composer, gains a frozen pool-context type — pool ID, provider, and the pool's resolved
  declarations. `resource_views(declaration, *, pool)` replaces the `pool_id` argument
  and returns the views it built together with the problems that kept it from building
  one. `provisioning/compute` declares `arkhai-kit-resource-pools-contracts`, whose
  declaration types it now imports.
- The provisioning service, the composition root, reads the `ResourcePool` rows in its
  own resource pass, resolves each pool once through the shared resolver, and passes each
  declaration its pool's context; it interprets none of it. One row-to-context function
  serves both this pass and `load_capacity_pool_metadata`, so the two cannot drift.
- The VM and bare-metal provisioning adapters take the new signature; the bare-metal
  adapter declares `arkhai-kit-resource-pools-contracts` wherever it imports from it.
- `kit/site`'s `resource_pool_projection`, which rebuilds each projected resource from
  named fields, copies the optional per-resource `publication_view_problems` mapping when
  present, as it copies `publication_views`, and neither reads nor interprets it; the
  site-client resource-pool fixture both sides of the boundary test against carries it.
  `kit/resource-pools` and core do not change.

`kit/site` still calls the pool directory and the resource inventory separately, and the
two reads need not agree by construction: a pool's `capacity_backing` and provider are
fixed at creation and a pool is never hard-deleted, so no pool can change backing between
them. A pool created between the two reads has no directory entry; its resources'
views get no term check and are held as unresolvable (decision 6), never refused.

Rejected: `kit/site` passing the pool directory's rows into the resource pass, which adds
no import but is a new use of pool state in an authority kit that knows no market, where
`ARCHITECTURE.md` forbids adding any while the site's edge into the pool authority
stands; merging the two reads into one `kit/site` callable, a `kit/site` interface change
bought to close a race the immutability rules already close.

A contributed projection never raises on a declaration's content. Declarations arrive
over the site's API from any client, and one declaration a view builder could not handle
answered 500 for the site's whole resource-pool projection, every pool and every domain
with it. A declaration from which no valid view can be built is projected without the
view, and the projection reports why: each projected resource carries an optional
`publication_view_problems` field, keyed by view identifier. A backed declaration naming
no host or no access methods, a missing or invalid `allocation_mode`, a missing
`physical_host_id` attribute, and a private-looking capacity or capability key are all
such cases; the existing no-host rule is one of them. The bare-metal storefront reports
each as a `publication_view_unbuildable` entry in its site derivation (decision 10).

Rejected: refusing a malformed attribute when the declaration is written. Its
backing-dependent rules need a site read of pool state, which `ARCHITECTURE.md` forbids
while the site's edge into the pool authority stands, so a write-time check would be
partial and the projection would still have to tolerate what it missed. Rejected: keeping
the generation failure.

#### 5. Delivery terms are the delegate's decision

Some fields of a listing commit the marketplace to delivering something: on a backed
listing it stands behind them, and on an unbacked one nothing does. These are delivery
terms. Whether a listing carries them is the backing delegate's decision, through two
domain-neutral operations a domain applies to the fields it names as delivery terms:

- `carry_delivery_terms(terms)`, used where the site builds a publication view: a backed
  delegate passes the terms through, an unbacked delegate carries none.
- `delivery_term_constraints(terms)`, used where a model validates: a backed delegate
  requires every term present, an unbacked delegate requires every term absent.

A term is present when it is neither absent nor null; a string or collection term must
also be non-empty, and a boolean term is present as `True` or `False`, since an
unavailable backed host's `available` is a legitimate `False`.

Bare metal names `host_id`, `physical_host_id`, `access_methods`, and, on the view,
`available` as its delivery terms. VM and API credits name none.

| Field | Backed listing | Unbacked listing |
|---|---|---|
| `capacity_backing` | `backed` | `unbacked` |
| `host_id`, `physical_host_id` | required | absent, even where the declaration names a host |
| `access_methods` | required, non-empty, as declared | absent |
| hardware, region, `asking_rate`, durations | as today | as today |

The `["ssh"]` default for `access_methods` is removed from the listing model and the
view carrier: an absent field makes no commitment, and a default would publish one
nothing stands behind. Rejected: publishing a declared host or access methods on an
unbacked listing, which would read as a machine and access the marketplace delivers.

`capacity_backing` is the buyer-visible indicator. The compute registry schema filters it
exactly and every buyer CLI compiles its resource query from that schema, so a buyer can
ask for `capacity_backing=unbacked`; this change's end-to-end evidence proves it.

Every remaining reader of the host fields is on a path an unbacked listing cannot reach:
escrow negotiation, accepted terms, and settlement verification are reached only through
stages that deliver through capacity, which publication never offers an unbacked listing;
capacity effects are refused by the delegate's admission guard; and the fulfillment routes
refuse an introduction deal before loading a fulfillment context (decision 9).

#### 6. The view carries no backing; the shared carrier validates its delivery terms

The `bare_metal.v2` view on the wire carries no backing label. Backing has one source,
the containing pool entry, as pool membership does, so backed views are byte for byte
unchanged and no second copy of backing can disagree with the pool's.

The view's own model, `BareMetalResourceProjection`, therefore makes its delivery terms
optional and checks only their structure. The rule lives one level up, in
`TrustedBareMetalResource`, the carrier in `arkhai_bare_metal` that both the site's view
builder and the storefront use:

- it carries `capacity_backing`, the containing pool's declared label, which its caller
  supplies: `trusted_bare_metal_projection(*, site_id, projection, backings)` takes the
  generation's resolved backing per pool;
- its validator applies that label's delegate's `delivery_term_constraints` to the view,
  so a backed view missing a term and an unbacked view carrying one are both validation
  errors, as a view contradicting its container's `pool_id` already is;
- a pool absent from `backings`, because its declarations do not resolve, has no label,
  so no term check runs; its resources are held as unresolvable.

Resolving a generation's declarations is the reader's job and checking a view against a
backing is the carrier's, so `arkhai_bare_metal` gains no dependency. The right label for
a pool depends on the whole generation — a generation in which no pool carries either
declaration comes from an older producer and reads as `legacy_producer_backing` — and that
rule lives in the per-generation reader the storefront already runs. The storefront
therefore reads the generation's pools before its views, in publication and in the
listing-source check, and passes `SitePoolReading.backings`. The site's view builder
passes its pool context's backing (decision 4); the site is the current producer and
refuses to start while a stored pool lacks valid declarations, so resolving each pool on
its own is correct there and the older-producer rule never applies.

A violation is a malformed view, and `trusted_bare_metal_projection` refuses the site's
whole generation for it, as it does for every malformed view: the storefront then holds
that site's listings as `site_projection_refused` with the validation error. The site
builds its view through the same carrier after `carry_delivery_terms`, so a correct site
cannot emit an inconsistent view; only a site of another build or a misbehaving one can.

Rejected: a backing label on the view (a second source of backing and a new cross-check);
a second view kind for unbacked supply (a domain branch on backing); tolerating the
inconsistency in classification by holding a backed view missing a term and dropping an
unbacked view's extra terms with a report (too lenient: what the site's own output gets
wrong should be rejected where it is parsed); rejecting only the inconsistent resource
(two rules for "the site sent a malformed view"); the carrier resolving each pool on its
own through the contracts resolver (an older producer's pools would disagree with the
storefront's own reading); the carrier importing `kit/resource-pools`'s reader (an edge
from the domain vocabulary package into the pool authority, for modules `ARCHITECTURE.md`
already lists as misplaced there).

#### 7. A candidate with no settlement option yields no listing; an open one closes or is held

Bare-metal publication refuses a candidate, backed or unbacked, whose payload carries no
settlement option and no accepted escrow, through a typed refusal. Settlement
admissibility does not cover the unbacked case on its own: it refuses only when it drops
an option, so a contact-only candidate whose origin has no configured contact dropped
nothing and published with no option. This refusal is the guard, for VM and bare metal
alike.

The refusal is recorded in the cycle report with its site, pool, and Physical Resource at
the top level, so it reaches status and the derivation log (decision 10).

For a candidate whose listing is already open, each mechanism of the candidate's
admissible clauses is classified by its readiness blockers, and the classification
decides. The admissible clauses are the ones the candidate could publish: its pool's
override, or the configured clauses where it has none, after admissibility for its
backing. A mechanism outside them could never settle this listing, so its readiness says
nothing about the offer it published. A candidate left with no admissible clause is the
same typed refusal with every mechanism ruled out by configuration, so it closes, where it
had been an untyped failure that left the listing open.

- A mechanism is **ruled out by configuration** when the storefront's own configuration
  excludes it — no clause, a contact-only option whose origin has no contact, or any
  configuration blocker, whatever else it reports: an oracle-gated section with no
  oracle cannot settle even once its chain answers.
- A mechanism is **unknown** when every blocker it reports is a reachability blocker —
  its readiness could not be determined because its chain or service cannot be reached,
  or has not been probed since start (decision 19).

When every mechanism is ruled out by configuration, or no clause is configured, the
listing is closed through reconciliation as `no_settlement_option`. `ARCHITECTURE.md`'s
rule for holding or closing applies: every declaration reads, and the storefront can no
longer say what its policy would sell. A listing closed by reconciliation reopens under
the same identity on the first cycle whose payload builds again.

When any mechanism is unknown, the listing is held: its last terms stand, the derivation
records a hold, and it negotiates normally; settlement fails retryably where it touches
the unreachable dependency. Unknown is not unready, as a site whose projection the
storefront does not hold is unknown, not empty. A mechanism ruled out by configuration
beside it does not change that: a listing published with only an Alkahest option whose
chain is down is held, even where a contact-exchange section that never applied to the
listing's origin is configured, because the offer it published is still one the
storefront would make once the chain answers. Conversely, an unknown mechanism outside
the candidate's admissible clauses holds nothing: an unbacked listing whose only
mechanism, contact exchange, is configured away closes while Alkahest's chain is down,
since admissibility drops Alkahest for unbacked bare metal and the close is due whatever
the chain answers.

Every readiness blocker therefore states whether it is a configuration or a reachability
blocker; each mechanism's preflight sets it, and Alkahest's chain probe is what produces
reachability (decision 19). The core publication runner is schema-opaque, so
`PublicationSource` gains a hook that closes a candidate's open listing with a reason,
which VM and bare metal supply from their reconciliation close paths, and the runner calls
it on a typed refusal in which every mechanism is ruled out by configuration. Other
payload failures keep their behaviour: reported, with the listing left as it is, so a
defect never delists anything. API credits does not publish through the runner; what an
unready Alkahest does to an open API-credit listing is recorded in decision 19.

Rejected: closing whenever any mechanism is ruled out by configuration, which let an
unrelated, unusable mechanism decide whether an outage delists supply; classifying every
configured mechanism, which let an outage on a mechanism the candidate could never use
hold a listing whose close is already due; classifying the mechanisms admissible for the
candidate's backing alone, which misses a pool override that excludes one; deciding per
previously published option, which needs the runner to read a listing's last-published
options; holding every optionless listing, VM's prior behaviour, which fell out of the
runner's control flow and advertised options the storefront could not honour; refreshing
in place with no options, bare metal's prior behaviour, which published an unbuyable
listing; refusing openings on a reachability-held listing, which needs a new seam from
negotiation into settlement readiness for a transient case the chain already refuses.

#### 8. An unbacked listing's recheck reads its held projection, never availability

Bare metal's opening recheck reads the projection the storefront holds for the listing's
site, as `share-site-projection-state` made it, and goes through the binding's delegate,
whose `judge` never asks availability of an unbacked listing. An unbacked listing is
refused only by its declaration: its shape, region, or Physical Resource, or its resource
now in a pool other than its bound one. The recheck finds the resource by its bound pool
and Physical Resource, so a resource moved to another pool answers that the resource is no
longer projected under its pool, a declared mismatch. A site whose projection the
storefront does not hold, or holds unconfirmed, refuses openings as retryable for either
backing. The inventory guard is unchanged.

#### 9. A deal settled by introduction has no settlement or fulfillment, in both domains

A seller stage whose mechanism completes outside settlement and fulfillment — contact
exchange today — declares that it has no settle, delivery, or refund operation, in VM and
bare metal alike. Bare metal adopts VM's model: its contact stage stops recording the
reveal as settlement evidence, which made an introduction look like a settlement with no
delivery. Planning confirms nothing else reads that evidence; retention, deletion, and
re-delivery are the contact-exchange kit's.

Both domains answer from the stage the accepted Agreement selected, through one shared
refusal, deciding by the stage's own declaration and never by comparing a mechanism ID or
the listing's backing. Every seller stage-table entry declares
`completes_outside_settlement`, beside `settles_from_agreement` and `release_models`, and
a stage that omits it cannot be constructed. It is not `fulfils_through_capacity`, which
says whether settling through a mechanism delivers through capacity and decides what an
unbacked listing may publish: the two agree today only because contact exchange is the one
stage that does not fulfil through capacity, and a mechanism that takes settlement without
delivering through capacity, such as hosted settlement over unbacked supply, would be
refused wrongly by a refusal reading it. The answers:

- a settle request answers **409**, "a contact exchange completes by introduction, not
  settlement";
- bare metal's fulfillment status, access, and result reads and its teardown answer
  **404**, naming that the deal settled by introduction and has no fulfillment.

The fulfillment routes check, in order: ownership, against the accepted negotiation
thread's recorded buyer and terminal state, so a stranger cannot learn that a deal was an
introduction; the accepted stage; the refusal; and only then the fulfillment service or
context. An unbacked deal's binding has no host, so loading its context first could fail
on a missing field rather than answer.

The refusal lives in `kit/storefront`, beside its framework-free deal-control route
services and their HTTP-shaped `LifecycleRouteError`, which every storefront already
composes and translates. A shared stage convention belongs to a kit, never to core, whose
stage table is opaque, or to a mechanism package (`market-composition`'s architecture
companion), and this one serves non-escrow mechanisms, so the settlement runtime is no
home either. The domain resolves the accepted stage and passes the kit its declaration
and the reason text: a kit's scope is nothing, so the kit owns the decision and the status
codes but not the wording that names contact exchange, and it imports neither
`core_storefront` nor a stage type.

The two domains' delivery route surfaces differ — VM reports delivery through settle
status, bare metal through negotiation-keyed fulfillment routes — and unifying them is
`kit-owned-listing-and-fulfillment-lifecycles`', which keeps this rule.

Rejected: patching bare metal's fulfillment routes alone; unifying the route surfaces here;
a requirement for a storefront composed without fulfillment, which production composition
cannot build; deciding by `fulfils_through_capacity` with the invariant that a stage not
fulfilling through capacity has no settle operation, which is false once hosted settlement
over unbacked supply exists; housing the refusal in `kit/contact-exchange` (a mechanism
rule it is not), core (stages are opaque to it), or `arkhai-compute` (a vocabulary package
whose contract is lightness).

#### 10. One site-derivation summary, status, and log for both compute storefronts

A storefront's per-site derivation — every hold, refusal, and report a publication cycle
made, each a reason code with its pool or Physical Resource and detail — is kept by one
`kit/capacity-publication` site-derivation log that VM and bare metal both feed:

- **Recorded by publication cycles only.** A real publication cycle records each site's
  summary; a preview records nothing; VM's listing-source checks and capacity-event
  reconciliation no longer record it. Status therefore always reports the last
  publication cycle's derivation, in both domains.
- **Keyed by publication source and site.** Each publication source records its own
  summary of a site, so two sources composed in one process never clear and re-raise each
  other's entries.
- **One status shape.** Both storefronts serve `publication_derivation` from it, per site,
  as `holds`, `refusals`, and `reports`. VM's former categories become entries:
  `regionless_pools` a hold with `pool_region_missing`, `retired_pricing_keys` a report
  naming the keys, and so on. A configured site no publication cycle has derived since
  start is absent, so a site present with empty lists always means a clean cycle.
- **Logged on change.** Each entry is logged as a warning when it first appears in a
  site's summary and at info when it clears; a standing condition is logged once, not
  every cycle, and previews never log.

Bare metal had logged every pool condition every cycle, previews included; VM logged its
whole report again whenever any part changed, from a module-level dictionary that also
served status.

Rejected: bare metal copying VM's rule in its own code (two implementations of one rule);
once per projection generation (repeats standing conditions on unrelated changes);
keeping the two status shapes.

#### 11. This change removes bare metal's temporary refusal of unbacked pools

`encapsulate-capacity-backing` kept one branch on a particular backing outside the
delegate: bare-metal publication's refusal of an unbacked pool, kept deliberately because
it added no unbacked bare-metal supply. This change deletes that check, its
`pool_unbacked` report, and `SitePoolReading.unbacked`, after which bare metal derives
listings from every enabled pool advertising `bare_metal` whatever its backing.

#### 12. Negotiation and settlement compose the existing kit runtimes

Negotiation and settlement for an unbacked bare-metal listing sit on the kit negotiation
runtime and settlement composition `bare-metal-mock-provisioned-deal` composed for bare
metal. Settlement, the reveal, per-origin contact resolution, seller-side delivery, and
retention key only on the listing's origin site and need no change.

#### 13. Bare metal publishes on a loop over held projections

An unbacked listing is never judged against availability, so source reconciliation is the
only reconciliation it gets, and it must run without an operator. `share-site-projection-state`
gave bare metal VM's per-site projection state and publication loop, so a withdrawn
unbacked pool's listings close on the next cycle.

#### 14. The bare-metal evidence is VM's introduction scenario, stage for stage

- A new bare-metal lane scenario, `e2e_bare_metal_unbacked_introduction`, runs VM's Goal 7
  introduction scenario stage for stage and adds what this change introduces:
  - supply: a backed pool with a host-bearing declaration and a rate; an unbacked pool (no
    deliverable mode, advertising `bare_metal`, a configuration-free provider) with a
    host-less declaration that enables bare-metal publication and a rate; and a listing
    that publishes no rate. Contact settlement reaches the unbacked pool through a
    storefront pool override, as in VM's scenario;
  - discovery through the buyer CLI: a rate-bounded `market bare-metal list` returns the
    backed and unbacked listings together and excludes the one without a rate, and a
    `capacity_backing=unbacked` query returns only the unbacked one;
  - the unbacked listing publishes `capacity_backing: unbacked`, no host fields, no
    `access_methods`, and exactly `contact-exchange.v1`;
  - the reveal through the buyer CLI, with the buyer's file sink receiving the seller's
    contact, and seller-side delivery reaching the lane's mail sink;
  - the fulfillment status route answering 404 for the introduction deal.
- The bare-metal lane gains a mail sink and the storefront's delivery configuration for a
  `seller-mail` SMTP sink.
- The stages both domains run identically move into a shared introduction stage module,
  each domain supplying a driver for supply seeding and its CLI verbs, as the compute deal
  stages do; VM's introduction scenario moves onto it. The new scenario holds the
  storefront's loops through the module holds of decision 22.
- Both buyer plugins registered a root-level `settlement` command group, and the core
  buyer application added every installed domain's commands without a duplicate check, so
  with both installed one domain's `settlement contact introduce` could run the other's
  recovery; a pipeline run saw it, decided by entry-point discovery order. Bare metal's
  settlement group moves under `market bare-metal`, beside its `request-introduction`, and
  the core buyer application refuses at startup a root command name two installed domains
  register, naming both. VM's root-level commands stay.
- The existing backed bare-metal introduction scenario stays: its retention and
  operator-deletion coverage is independent of backing.
- **No pipeline scenario runs against the charts here.** Running pipeline scenarios
  against the Helm charts is `helm-e2e-pipeline-parity`'s acceptance, so the unbacked
  introduction scenario runs in its compose lane only. The bare-metal chart can publish
  (it passes configuration through and derives its registry in an umbrella release), so
  that is the only ground.
- **The chart changes this change makes are validated on the local topology.** Decisions
  20 to 22 change Helm-deployed behaviour, which a render test cannot show. Their evidence
  is chart render tests, the VM storefront's degraded-start integration test, and
  `make helm-topology-up` and `make helm-topology-check` passing on the change's commit,
  with Bob's lifecycle loops shown running after the check and no init containers on the
  VM storefront. The maintainer runs the Helm part locally when that round is validated;
  if it has not run by closeout it is recorded as unrun.

#### 15. Goal 7 closes on single-site evidence

The live two-seller scenario — two seller sites behind one storefront — needs one
storefront serving several sites, which is not supported and is not yet a goal. It is
recorded as unowned in the change index for both domains, and Goal 7 closes without it.
The per-origin contact resolution and delivery routing it would exercise are proven at
integration level.

### B. Alkahest settlement inputs

#### 16. Settlement verifies against the plan committed at acceptance

`ARCHITECTURE.md` already states that accepted terms and persisted operation identities
remain authoritative through readiness or configuration changes, and VM's refund follows
it, reading the accepted plan "so a listing changed since acceptance cannot block it".
Settle verification did not: VM's `prepare_vm_settlement`, bare metal's acceptance,
`verify_alkahest`, and `revalidate_alkahest`, and API credits' `_prepare_alkahest_settlement`
re-derived from the listing as stored when they ran. A seller who changed release policy,
wallet, or address book after acceptance made a buyer's correctly funded escrow fail
verification and wait for reclaim.

Every domain verifies and settles an Alkahest deal against the `settlement_plan` committed
at acceptance. `kit/alkahest`'s escrow verification gains a form taking the accepted
obligation rather than a listing, and the three domains call it; bare metal's acceptance
builds its plan from the listing record the opening authorized. Planning confirms the
smaller acceptance question.

Settled in implementation (Section 7): the kit's form matches the escrow to one of the
committed plan's Alkahest obligations on the accepted proposal's chain and escrow
contract, and is the registration's settlement verifier. Bare metal records the
opening's listing record and continues every round, acceptance and force-accept among
them, against it, with the current record's status: the runtime builds acceptance from
the record it resolved, so that record is the one continuation resolves. The dry-run
verify request names only the negotiation, since the plan determines every term the
request used to carry.

Every other reader of a deal's settlement terms after acceptance reads the same plan:

- VM's administrator dry-run verify checks an escrow against the committed plan of the
  accepted deal it names, so the preview and the real verification cannot disagree;
  planning confirms how the dry-run is given the accepted deal;
- the heartbeat interval a VM deal's oracle evidence assumes comes from the committed
  plan's service terms, never the current setting;
- VM's administrator interrupt decides whether a deal is interruptible from the committed
  plan's interruptible term, never the current listing or the current chain address
  configuration.

With the settle paths reading the plan, nothing after acceptance re-materializes under a
listing's `demands`, which VM and bare metal publication refresh in place.

Rejected: handing it to `version-accepted-artifacts`, whose subject is evolving stored
accepted artifacts across releases rather than which reference verification reads; handing
it to `move-escrow-into-alkahest`, which has no design yet.

#### 17. A buyer funds only what it derives from its acceptance and the listing

The seller's accept reply carried derivable settlement data. `accepted_escrow_terms` was a
legacy mirror of the plan, sent by every Alkahest seller through `kit/alkahest`'s
`accepted_escrow_artifacts_from_proposal`, read by VM's and API credits' buyers
in preference to their own derivation, and funded unchecked on the escrow-proposal path
and on resume; a seller naming a different arbiter or recipient than its listing advertised
was funded.

The Agreement and the listing it was accepted against are a deal's settlement inputs, and
what they determine each party derives for itself; a counterparty's copy is compared with
the derivation, never used in its place. Arkhai payments already works this way: the buyer
re-derives the mandate and requires equality.

- `accepted_escrow_terms` is removed from the accept reply models, `kit/alkahest`'s
  producer, the legacy coercions, bare metal's response, and every buyer reader, including
  the back-fill that synthesized it from the plan.
- The buyer always materializes the escrow itself, through `kit/alkahest`, from its
  accepted proposal or selection and the listing's advertised release condition.
- Where the seller sent a plan, the buyer requires its own derivation to equal the plan's
  obligation before funding. The domain-supplied plan check `core/buyer` already declares,
  `AdvertisedPlanValidatorFn`, runs on every branch that receives a plan and on resume
  rather than only on the selection branch, and API credits supplies it as VM does;
  `core/buyer` gains no import of `kit/alkahest`.
- The run-log records the selected listing's advertised release conditions at acceptance.
  A resumed run derives the escrow from the Agreement's selected option and those
  conditions, checking the recorded seller plan against them, rather than refusing or
  funding blindly.
- A run-log that predates the recorded conditions is refused before funding, naming the
  reason: the run was accepted before release conditions were recorded, so a new run is
  needed. Resuming it as before would fund the seller's terms unchecked. Only runs
  accepted but unfunded across the upgrade are affected, and no funds have moved for them;
  a run whose escrow exists resumes, since it derives nothing.

Removing the field is benign for an older buyer, which falls back to its own
`build_escrow_terms` derivation when the reply carries none.

The settlement plan stays in the reply as the seller's committed copy the buyer compares
against, which also detects derivation skew between buyer and seller before funds move.
An Agreement carrying the release condition and expiry, so that a reply carries nothing
derivable, is the end state, recorded in `move-escrow-into-alkahest`.

Rejected: widening the buyer's check of the seller's terms while still funding them;
removing every derived artifact from the reply now, which breaks the negotiate wire in
every domain and overlaps the escrow-carrier changes; resuming an older run-log by deriving
against the listing as the registry now serves it, which adds a registry read to resume
and refuses correct runs whose listing has since changed.

#### 18. An escrow proposal that names no escrow contract is refused

`escrow_shape_guard` read an empty or zero escrow address as "this negotiation carries no
escrow" and passed it, folding an incomplete Alkahest proposal into the no-escrow case.
Such a proposal was then priced from the listing's first accepted escrow on any chain, and
materialized and verified with whatever token it named, so a deal priced in one token could
be escrowed in another.

An escrow proposal that names no escrow contract is refused. The guard refuses it with a
named reason while still passing a negotiation that carries no escrow proposal, and
`kit/alkahest`'s `authorize_escrow_proposal` and `materialize_escrow_terms_from_proposal`
refuse it too, because the guard is a seller policy a seller may omit and the
materialization chokepoint is where `negotiation-protocol` already enforces the release
condition independently of policy. Every unpinned branch goes: first-entry pricing in all
three domains and bare metal's chain-blind fallback, verification's default-kind branch,
and `_accepted_escrow_for_proposal`'s zero-address case. This closes Goal 6's unowned
roadmap gap on how such a proposal is priced: it is refused.

The rationale is the wire, not the clients: no buyer in this repository sends an unpinned
proposal, but the protocol admitted one, and anything the wire admits must be handled
whichever client sent it.

Rejected: resolving an unpinned proposal to the listing's single entry on its chain, with
or without kit enforcement, which keeps an inferred input in the settlement path; adding
only a token check, which leaves first-entry pricing.

#### 19. An Alkahest section that cannot settle makes Alkahest unready

A storefront must not need Alkahest to function: sellers may settle on other rails, and an
unusable Alkahest section should cost the seller Alkahest, not the storefront. Readiness is
the contract every mechanism shares, so each case is an Alkahest readiness blocker:

- an `oracle_gated` section with no trusted oracle;
- a trusted or interruptible oracle equal to the seller wallet;
- an empty seller wallet, including when the storefront composes clients, which previously
  satisfied the check whatever the address;
- an interruptible section with no interruptible oracle; `release_conditions`' fallback to
  the seller wallet as oracle is deleted;
- a configured release model the domain cannot deliver;
- in bare metal, a configured section, enabled or not, missing its seller address, its
  chains, or its wallet key, each named by its blocker.

Release conditions are derived only for ready Alkahest clauses: `kit/alkahest`'s
`publication_release_conditions` takes the clauses' readiness and returns nothing for an
unready mechanism, and VM, bare metal, and API credits call it after readiness. VM had
derived conditions before readiness and refused every candidate per cycle. In API credits
this covers the escrows a listing request supplies as well as those its clauses compile,
so an unready Alkahest yields no API-credit escrow option on either path.

Two startup refusals move to readiness: bare metal's refusal of a configured section
missing its address, chains, or key, and every storefront's refusal of an undeliverable
release model. The second was justified because a configured section owns the deals
accepted under it; since decision 16, settlement verifies against the committed plan, and
no settlement or collection path reads the section's current model: it is read directly
only at publication and at startup, bare metal's indirect read through refreshed listing
`demands` goes with decision 16, and interrupts exist only in VM, which delivers every
model. Bare metal's refusal of Alkahest inputs supplied with no Alkahest section stays:
that is incoherent configuration, not an unusable mechanism, and a service refuses to
start when its own configuration is incoherent.

A section that does not parse still stops startup, as all configuration does. Readiness
governs publication only, so two known limits follow:

- An address, chains, or key removed while Alkahest obligations are open leaves the
  seller unable to service or collect them; a buyer's escrow stays reclaimable at expiry,
  so the exposure is the seller's own. Startup does not refuse on open obligations, which
  would make it depend on stored deal state and restore the dependency on Alkahest; the
  blocker naming the missing input is the operator's signal.
- An API-credit listing's options are fixed when it is created and never re-derived, so
  one whose Alkahest becomes unready keeps advertising its Alkahest option until its
  seller closes it. Deals accepted on it verify against their committed plan and settle
  as before. This widens nothing: the same misconfiguration previously stopped the whole
  storefront while the listing stood in the registry. No change gives API credits a
  re-deriving publication path, so the limit is unowned.

**Readiness blockers state their kind, and Alkahest probes its chains.** `ReadinessBlocker`
gains a required `kind`, `configuration` or `reachability`, set on every blocker: by each
preflight, and by the settlement runtime on the `not_configured` and `disabled` blockers
it builds itself, both configuration blockers since an absent or disabled section is the
seller's configuration. Arkhai payments and contact exchange contact nothing during
readiness, so every blocker they report is a configuration blocker. Nothing parses a status payload through the model,
so the field is wire-safe. Reachability is produced by one chain probe in `kit/alkahest`:

- **What it calls.** For each configured chain it reads the chain ID, then the code at
  each contract address the chain's address configuration requires. An RPC that errors or
  times out is a reachability blocker, `alkahest.chain_unreachable`; a different chain ID
  is the configuration blocker `alkahest.chain_id_mismatch`; a required address with no
  code is the configuration blocker `alkahest.contract_missing`.
  `alkahest.contract_probe_failed`, which could not tell the two apart, and the untyped
  `contract_probe`, `required_addresses`, `observed_chain_id`, and `deployed_contracts`
  resources, which only tests passed, are deleted. Planning confirms the transport: the
  SDK client or a JSON-RPC call against the chain's `rpc_url`.
- **Who owns it.** The probe is one `kit/alkahest` object holding the configured chains,
  a per-chain client constructor supplied at composition, the live client map, each
  chain's last result and when it was taken, and an async step that probes every chain.
  Consumers are handed that map, and the probe updates it in place, so a
  chain whose client could not be constructed is probed like any other and its rebuilt
  client reaches every consumer, rather than being dropped for the life of the process.
  Each storefront composing Alkahest builds the probe beside its clients, passing a
  constructor over the existing factory's per-chain construction, hands it to the
  Alkahest registration as a resource, from which readiness reads its results, and
  registers its step as the `alkahest-chain-probe` loop beside its other loops: one
  registration per domain. `kit/storefront` gains nothing Alkahest-specific, so the
  client factory's later move into the Alkahest registration carries no probe with it.
- **Cadence.** Readiness is evaluated per candidate, per status read, and at startup, so
  the probe runs apart from it: in the `alkahest-chain-probe` loop, whose timer probes
  each chain once per probe interval (a setting, 30 seconds by default), with the pause
  and `run-cycle` step every storefront loop has. The Alkahest preflight reads each chain's
  last result and makes no chain call. A chain not yet probed since start reads as
  reachability, so a fresh storefront holds its open listings rather than closing them.
  A result does not expire: while the loops are held, readiness reads the last result
  however old, as a held scenario expects. Status reports each chain's result and when it
  was taken. Every step probes every chain, so an operator's explicit step always acts on
  the chain as it is; the loop's timer is what bounds how often a chain is called
  (settled in implementation, Section 4, after a step that skipped chains probed within
  the interval made an explicit step a no-op).
- **A disabled section names what it lacks.** "Enabled or not" needs the settlement
  runtime: it built a disabled section's readiness itself and never ran its preflight, so
  a disabled section could report only `disabled`. It now lists, after `disabled`, the
  configuration blockers the mechanism's preflight reports for a disabled section,
  dropping reachability ones. Each preflight decides what that is: Alkahest's seller
  preflight reports its wallet, key, chains, address configuration, and release model,
  and nothing about publication; contact exchange reports its missing profiles or
  contact; Arkhai payments reports nothing; a buyer's preflights report nothing. Settled
  in implementation (Section 5).
- **Status carries readiness.** No storefront's system status reported mechanism readiness,
  so the probe's results had nowhere to appear. Each storefront's status gains a
  mechanism-neutral `settlement` list, each composed mechanism's readiness as its safe
  projection, and Alkahest's projection carries the per-chain probe results; core's status
  model and the storefront client carry the list without interpreting it. Planning settled
  this during implementation (Section 4).
- **Paths that publish once.** Only reconciling paths can wait for a later cycle, so
  API credits' one-shot paths are shaped around reachability:
  - The configured seed no longer runs in startup. It is the `listing-seed` loop step,
    which waits, logging nothing at error level, while the credits service cannot be
    reached for its quota registration or a mechanism its clauses use is unknown; gives
    up, logging once, on a configuration failure; and finishes once the listing exists,
    created or found. A storefront whose dependencies answer publishes its seed within a
    probe interval of start. Settled in implementation (Section 6): the seed waits
    whenever any mechanism it uses is unknown, not only when nothing would publish,
    since a listing's options are fixed at creation; the step retries every 2 seconds,
    or the probe's interval if shorter, so the seed follows the probe's first result
    rather than a whole interval later; and the cycle that gives up fails, so the loop
    controller records and logs it, its report naming a reason code or error type,
    never an error's text.
  - A create refused only because a mechanism is unknown answers 503, naming the
    unreached mechanism and that the create can be retried once it is reached; a
    configuration refusal answers 400 with its blocker codes, as today.
  - The storefront CLI's `publish` and `listings` commands are clients of the running
    storefront's routes, through the typed listing client, which gains a list method,
    rather than building the storefront's services or opening its database in their own
    process. A listing created with no storefront serving it is one no buyer can
    negotiate, and a process with no loops would never have a probe result.
- **Timeouts.** Each RPC call is bounded, 5 seconds by default; a timed-out run records
  an unreachable result and is retried at the next interval, never in a tight loop.

Rejected: one kit startup check refusing every case (makes a seller who does not want
Alkahest depend on its section being usable); per-candidate refusal at publication;
refusing a missing oracle in the configuration model's own validator, which cannot see the
wallet; reporting no reachability and keeping a kind every blocker shares, or dropping the
kind and the hold with it, either of which leaves an undeployed or wrong address book
undetected at readiness; probing inside the preflight, which would call the chain once per
candidate per cycle; refusing API-credit openings on an unready mechanism, a new seam from
negotiation into readiness; scheduling the probe and rebuilding clients in `kit/storefront`'s
client-construction seam, which adds Alkahest behaviour to an edge `ARCHITECTURE.toml`
records as an exception to be removed, against the mechanism neutrality decision 9 keeps
for the same kit; one bounded probe pass at startup before startup publication, and
probing on demand on the create path, both rejected for the seed waiting on its
dependencies and an operator's create getting a retryable error; the CLI probing for
itself, which keeps a create path that needs no running storefront.

### C. Deployment and test hygiene

#### 20. The VM storefront starts degraded instead of waiting in init containers

The VM storefront chart's `wait-for-rpc` and `wait-for-registry` init containers polled
with unbounded `wget` requests; one request hung across a registry restart and the pod
never started. Both init containers are removed, as the bare-metal chart has none: the pod
relies on a `startupProbe`, and the storefront's own loops retry.

The VM storefront starts with its registry and chain unreachable. An unreachable chain
makes Alkahest unready with a reachability blocker from its probe (decision 19); an
unreachable registry shows as a failed publication or convergence cycle in loop status,
retried each cycle. `/health` stays a process check and the degraded state is reported
through system status, as bare metal reports it.

A wait inside the process holds the service back as an init container does, so the same
rule reaches the storefronts' own startup:

- The VM storefront's provisioning preflight and the API-credit storefront's
  credits-service preflight are removed, with their `fail_on_unreachable` and
  `preflight_timeout` settings. Each starts with that service unreachable; fulfillment
  and settlement calls to it fail retryably, and VM's held site projection already treats
  an unreachable site as unknown, so no listing closes for it. Bare metal has no such
  preflight.
- An Alkahest chain whose client could not be constructed at start is rebuilt at its next
  probe (decision 19), so the storefront recovers without a restart. Planning confirms
  whether construction touches the RPC; a construction failure the address configuration
  causes remains the configuration blocker `alkahest.address_config_invalid`.
- The VM storefront chart gains a `startupProbe` mirroring the bare-metal chart's, so a
  slow start is not judged by the liveness probe alone.

A render test asserts no `wait-for-` container renders and the `startupProbe` does,
mirroring bare metal's.

Rejected: bounding each attempt with a timeout, with or without an overall deadline, which
keeps a deployment holding the service back on its dependencies; narrowing the rule to
init containers and keeping the in-process preflights, which leaves a storefront that
exits and restarts while a dependency is slow. A misaddressed dependency is configuration,
but at start it is indistinguishable from an outage, and status reporting the failed calls
says more than a restart loop.

#### 21. Helm test pods carry no selector label of their chart's workloads

Each chart's Helm test pod took its labels from the chart's general helper, which includes
the selector labels its Deployment selects by, so a selector-based `kubectl logs` or
`kubectl logs deploy/…` found the test pod beside the service's. Each chart gains a
test-labels helper carrying chart, version, managed-by, instance, and
`app.kubernetes.io/component: test`, but not `app.kubernetes.io/name`, which every
Deployment selector requires. A render test over both topology releases asserts no Pod
annotated `helm.sh/hook: test` carries all of any Deployment's `matchLabels`. The
bare-metal test pod gains the hook delete policy the others have.

Rejected: adding `component: test` while keeping `name`, which leaves registry and
provisioning matching; adding `component` to every Deployment selector, which is immutable
and forces each release to recreate its Deployments.

#### 22. Scenarios hold shared services for the whole module

Scenarios paused a storefront's loops inside a stage and never resumed them — the VM deal
the Helm deal test runs, six more VM modules on Bob and Alice — and paused provisioning's
lease watchdog, resuming it only at the end of the success path. Compose lanes hid it by
tearing their stacks down; Helm releases persist, and Bob's loops were seen paused after a
passing run.

One mechanism serves every lane, extending the one both lanes already used for fulfillment
convergence:

- one shared helper per pause kind — the storefront's lifecycle loops, fulfillment
  convergence, and the lease watchdog — pauses before the module's first stage, waits until
  each loop reports itself paused at its gate, yields for the module, and resumes in a
  `finally`;
- each lane's conftest exposes one fixture per kind and client (Bob, Alice, the bare-metal
  storefront, the provisioning service) built on those helpers; bare metal's and VM
  introduction's own copies are replaced;
- a module takes the holds it needs with `usefixtures`, listed first so they are released
  last, after the module's other cleanup; stages assert a hold, through system status for
  loops and the fixture's own state for the lease watchdog, and never pause or resume a
  service;
- a unit check over the scenario source refuses any direct call of a pause route.

A module killed by `helm test`'s timeout runs no finaliser, and only a restart clears its
pause; modules in a lane run serially.

Rejected: an autouse teardown safety net in each lane, which leaves stages pausing and the
window before their pause open; opt-in fixtures alongside stage pauses, which hold twice and
can still leak.

### D. The provisioning service

#### 23. Unserved providers stop startup; failures after authentication are signed

A stored resource pool whose provider no registered handler serves made the provisioning
service's pool list, read, and export raise; the authentication middleware signs only
after a route returns, so the caller got an unsigned 500 that its typed client reported as
missing response authentication, and an exact retry got "in progress" until the dispatch
lease expired. Handlers are fixed by the build and every write refuses an unknown provider,
so such a row comes only from outside the service's write paths, and no pool document can
repair it.

- Startup refuses while any stored pool names a provider no handler serves, naming each
  pool and provider, beside the existing refusal of stored pools with invalid
  declarations. Unavailable dependencies start degraded (decision 20); unreadable own state
  stops startup, because waiting does not repair it.
- A failure after authentication answers a signed 500 with a fixed, non-revealing detail,
  following VM's administrator middleware, and the error is logged. The two middlewares
  differ in what follows:
  - The provisioning service's records outcomes durably and replays them, so it records
    the signed 500 as the request's outcome and an exact retry gets the same signed answer
    rather than "in progress" until the dispatch lease expires.
  - `kit/site`'s, which the API-credits service uses, keeps reservations and no outcomes:
    an exact retry of a retry-safe route runs again, and one of a route marked unsafe is
    refused with a signed 409 asking for a new request ID. It has only the unsigned-500
    half of the gap, so it answers the signed 500 and records nothing. Outcome recording
    for every authority is `redesign-authenticated-replay-state`'s subject.

Rejected: tolerating the row on reads with a problems field, which adds a pool wire field
and a non-importable export entry; mapping the error in the read routes only.

### Handed elsewhere and recorded

#### 24. Stage events go to a follow-up change

Stage events recorded a negotiation ID as their `listing_id` when an emitter named no
listing, and several emitters passed the listing under another key. Investigating it showed
the mechanism has no contract: it serves both an operator audit trail and the end-to-end
synchronisation seam, with no defined event vocabulary, best-effort writes, no retention,
and an operator CLI in one domain. Nothing here changes; the defect and its evidence go to
a follow-up change, `redesign-storefront-stage-events`, proposed for the "Service-to-service
trust and event delivery" lesser goal beside `replace-polling-with-authenticated-push`.

#### 25. Upgrade order cannot matter in the supported deployment shape

`ARCHITECTURE.md`'s "Operators" asks designs to record where upgrade order between sites
and storefronts would matter. This change has two places it would, and neither can arise
in the only deployment shape supported today:

- a new site emits unbacked views without `host_id`, which an older bare-metal storefront
  rejects, refusing the site's whole generation; and an older site emits host fields on a
  host-bearing declaration in an unbacked pool, which the new carrier rejects the same
  way. Each holds every listing at the site as `site_projection_refused`. A bare-metal
  storefront and its provisioning service are deployed by one Helm release, so neither
  version runs beside the other for longer than a rollout: a `helm upgrade` or rollback
  rolls both Deployments concurrently and can briefly pair an old pod with a new one.
  Within that window the site's listings are held, never closed, and the hold clears at
  the first projection poll after both pods are current.
- an upgraded core buyer beside an older bare-metal buyer plugin still registering a root
  `settlement` group, with VM installed, refuses to start. The bare-metal buyer pins
  `arkhai-core-buyer` exactly, so an installer cannot pair them without forcing it.

No mitigation is needed while those hold.

#### 26. Edits to other changes

Made on this branch with this design's recording, as `share-site-projection-state`'s
closeout edited this change:

- `move-escrow-into-alkahest`'s proposal records the end state of decision 17: an
  Agreement carrying the release condition and expiry, and a reply carrying nothing
  derivable from the Agreement and its listing.
- `kit-owned-listing-and-fulfillment-lifecycles`' proposal records that its unified
  delivery surface keeps decision 9's rule, applied at the stage.
- `resolve-compute-family-findings`' proposal: the bare-metal chart item is corrected (the
  chart passes configuration through and derives its registry; running pipeline scenarios
  against charts is `helm-e2e-pipeline-parity`'s; the negotiation-chain sentence is kept for
  re-verification), and the unmatched-route item is restated as an unsigned 404, never a
  405, which a typed client reports as missing response authentication.
- `redesign-storefront-stage-events` is proposed, on dev.
- `move-escrow-into-alkahest`'s `ARCHITECTURE.toml` exception row excusing
  `arkhai-kit-alkahest`'s undeclared import of `arkhai-kit-config` is deleted: the probe
  settings use `kit/config`'s `PositiveSeconds`, so the kit now declares the dependency and
  the row excuses nothing. The divergence that change owns — the kit reading a user
  configuration file for the best-price timeout — is a content judgement no check sees; it
  stays recorded in `ARCHITECTURE.md`'s "Where the current tree diverges" and in that
  change's proposal, and is unchanged.

### Permanent documentation

Spec deltas this change carries:

- `storefront-publication`: remove "An unbacked pool yields no bare-metal listing"; add
  "Bare-metal publication derives unbacked listings", "A bare-metal listing carries
  delivery terms only when backed", "A compute candidate with no settlement option yields
  no listing", "A deal settled by introduction has no settlement or fulfillment", and "A
  compute storefront reports and logs its site derivation"; modify "A bare-metal listing
  sells one whole unit", "Bare-metal opening rechecks its listing against its source" (on
  its held-projection text), "Complete bare-metal seller lifecycle" (an unpinned opening is
  refused; an unusable Alkahest section is unready), "An Alkahest listing advertises its
  release conditions" (an undeliverable model is unready), and "Publication derives all
  ready settlement options" (no ready mechanism refuses the candidate rather than failing
  publication).
- `physical-provisioning`: modify "A bare-metal publication view is built from its capacity
  declaration" and "Domains contribute their inventory views"; add "A failure after
  authentication is answered signed".
- `resource-pool-management`: modify "Capacity backing is interpreted by one delegate";
  add "A service refuses to start while a stored pool names an unserved provider".
- `registry-discovery`: modify "Compute listings publish their capacity backing".
- `negotiation-protocol`: modify "An Alkahest obligation uses exactly the release
  condition its listing authorizes" (an unpinned proposal is refused); add "The accept
  reply carries no escrow terms".
- `settlement-servicing`: add "Settlement verifies against the accepted plan".
- `settlement-configuration`: add "An Alkahest section that cannot settle makes Alkahest
  unready", "Readiness blockers state their kind", and "Alkahest probes its chains apart
  from readiness".
- `buyer-orchestration`: add "A buyer funds only what it derives" and "Two domains may not
  register one root command".
- `deployment-state`: add "A deployment does not wait on a service's dependencies" and
  "Helm test pods carry no workload selector labels".
- `test-compatibility`: add "Scenarios hold shared services for the whole module".

Promoted at closeout:

- `docs/development/ARCHITECTURE.md`:
  - "Authority boundaries": anything a counterparty can send is handled on its own terms,
    whatever client produced it;
  - "Settlement configuration": what an Agreement and its listing determine, each party
    derives for itself; and a configured settlement mechanism whose section parses but
    which cannot currently settle is unready, its options unpublished, while a section that
    does not parse stops startup;
  - "Holding or closing a listing": the same test applies to settlement — a listing left
    with no option is held while any mechanism's readiness could not be determined, and
    closed only when the storefront's configuration rules every mechanism out;
  - "Composition from above and below": where two domains handle one concern differently
    and nothing in their markets requires it, one behaviour is chosen for both rather than
    patching the domain that showed the defect;
  - the bare-metal commitment sentence and the "Storefront capacity boundary" passage on
    the delegate's decisions.
- `docs/development/DEPLOYMENT_AND_CONFIG.md`: a deployment does not hold a service back
  with init containers that wait for or validate its external dependencies, and the
  service reports them degraded, and no service waits for one in process either; a
  service refuses to start when its own configuration or stored state is incoherent; a
  Helm test pod carries no selector label of its chart's workloads; the removed
  `fail_on_unreachable` and `preflight_timeout` settings and the Alkahest probe interval
  and RPC timeout; system status's `settlement` readiness in "System status";
  the rewritten `publication_derivation` passages; the bare-metal lane's mail sink and
  delivery configuration.
- `docs/development/TESTING.md`: the module-hold guidance, in the wording the maintainer
  agreed; the bounded topology render assertion; the new scenario and shared introduction
  stages; the `alkahest-chain-probe` loop in each storefront's row of the loop table, and
  `listing-seed` in the API-credit row.
- The `storefront-publication` architecture companion: bare-metal candidates, delivery
  terms, the one-unit commitment, the recheck, the site-derivation log, the no-option
  close or hold, and a bare-metal negotiation continuing, accepting, and force-accepting
  against the listing record its opening authorized (decision 16's Section 7
  paragraph).
- The `physical-provisioning` and `resource-pool-management` companions where their
  passages describe the view contract, the resource pass's pool context, and the
  delegate's operations.
- The `market-composition` companion: the `completes_outside_settlement` stage-table
  declaration beside `fulfils_through_capacity`, and the introduction refusal in
  `kit/storefront` as the first shared stage convention.
- The `settlement-configuration` companion: why the Alkahest chain probe runs apart from
  readiness, and what each blocker kind tells the publication runner.
- The bare-metal seller quickstart's unbacked passage, rewritten as how to list unbacked
  machines; both seller quickstarts' `publication_derivation` passages.
- `docs/development/ROADMAP.md`: Goal 7's current state and gap row; Goal 6's unowned row
  on unpinned proposals, closed here; and a new Goal 6 row, "An API-credit listing's
  options are fixed at creation, so an unready mechanism's option stays advertised until
  the seller closes it", owned by "Unowned — needs a new change".
- The change index at completion.

The `TESTING.md` guidance agreed for decision 22:

> A scenario that needs a shared service's timer held — a storefront's lifecycle loops,
> provisioning's fulfillment convergence or lease watchdog — takes that lane's hold fixture
> for the whole module with `usefixtures`, listed first so it is released last. A hold is
> taken before the module's first stage and waits until each loop is at its gate, and is
> released in a finaliser whatever the module's outcome. Stages assert a hold; they never
> pause or resume a service themselves, and a source check enforces it.

### Implementation cadence

Three rounds, each one implementation session, reviewed and validated before the next, then
closeout. The order follows what each group relies on, so nothing is written twice:

1. **Round 1 — groups B and D.** Alkahest settlement inputs (decisions 16 to 19, including
   the readiness blocker's kind and the Alkahest chain probe) and the provisioning service
   (decision 23). Both later rounds rely on decision 19: decision 20 on an unreachable
   chain being non-fatal and reported by the probe, and decision 7 on the blocker's kind.
2. **Round 2 — group C.** Deployment and test hygiene (decisions 20 to 22). Its validation
   includes the local Helm topology observations of decision 14, run by the maintainer.
3. **Round 3 — group A.** Unbacked bare metal and its unifications (decisions 1 to 14),
   written on round 2's module holds.

## Open Questions

None. Questions 1 to 10 of the 2026-10-14 review, the carried-in items 11 and 12, and the
2026-10-20 review's findings are decided above; work deferred to other changes is
recorded in decisions 9, 17, 23, 24, and 26.
