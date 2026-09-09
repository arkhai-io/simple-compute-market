# Design — unbacked listing publication

## Context

The publication path is built around a promise: a listing cannot overstate what
is sellable. `storefront_listing_bindings.site_id` is `NOT NULL` under an
immutability trigger, every candidate carries
`CapacityBinding(site_id, offering_mode, source_id)`, that binding is reloaded and
compared at publication, reservation, commit, release, and restart recovery, and
publication reconciles against capacity deltas with close-before-reopen
semantics.

A listing whose terms are agreed out of band makes no claim any of that can
check. This design is about representing that honestly rather than about
weakening the promise for listings that do make the claim.

## Goals / Non-Goals

**Goals.** Make an unbacked listing a legal shape. Keep every capacity-admission
path unchanged and unasked. Put backed and unbacked compute supply in one
catalogue a buyer can query together. Leave a seller's supply able to become
capacity-backed later without a new domain, registry, or fabricated site.

**Non-Goals.** No published rate — `publish-indicative-listing-rates` owns
comparison. No backing transition on one durable listing — that is
close-and-republish. No new domain, no new registry, no settlement mechanism, no
finite unbacked listings. Each is owned elsewhere or deferred with a reason
below.

## Decisions

### Vocabulary

The terms this change is written in are settled, and they live here rather than
in `ARCHITECTURE.md` until this change makes them true — task 7.7 promotes them at
closeout. The alternatives considered are recorded because they are the kind that
get re-proposed.

`capacity-backed` was promoted rather than replaced. The document already used the
adjective in a load-bearing sentence — "Every capacity-backed candidate carries
`CapacityBinding(...)`" — without defining it, so naming its negation keeps one
vocabulary instead of introducing a second for the same distinction.

`unbacked` was chosen for that negation over four candidates, each rejected for a
collision rather than a preference:

- **`advisory`** is already used twice with different senses — negotiation-time
  availability is advisory, and `max_reservation_hold_seconds` is an advisory
  upper bound. A third would make the word useless.
- **`loose`** belongs to the registry's loose-listing profile, where it means
  schema sparseness. An unbacked listing carrying a full compute shape is not
  sparse. This is the closest near-collision in the repository and the one most
  likely to be merged by mistake, which is why the distinction is stated in the
  permanent Terms entry rather than only here.
- **`infinite` / `unlimited` / `unmetered`** each imply a real resource with no
  cap, which is the framing that leads back to fabricating an authority that
  admits forever.
- **`manual`** names a settlement mode, and coupling backing to settlement is the
  error the vocabulary exists to prevent.

An earlier draft also defined a `direct` / `projected` pair for listing
origination. Dropped: `direct` would have named the storefront's local-table
derivation, which `pools-9-retire-local-physical-authority` deletes outright, and
defining a term for a category being deliberately eliminated invites its
reintroduction. Unbacked listings do not need the pair either, since they are
projected like every other listing.

### Backing is a listing property, not a domain

The first framing considered was a new compute-family domain for out-of-band
settlement, with a second domain later for the finite, hosted-settled version.
Rejected on two grounds.

The thing traded does not vary — it is compute in every version. The settlement
mechanism does not vary in a domain-shaped way either, because mechanism is
already a composed registration choice; a domain named for how it settles would
be wrong on the first hosted-settled unbacked listing, which is the next version
already anticipated. What actually varies is whether an admission authority
stands behind the listing, and that is a property, not a domain.

Two domains would also publish identical `offer_resource` vocabulary into one
registry schema, which the compute-family schema-identity work exists to avoid.

The same reasoning makes this posture available to any domain. Nothing here is
compute-specific; a market family with no physical supply at all reaches it by
the same route.

### A listing's origin is not its admission authority

An earlier draft of this design had an unbacked listing carry no `site_id`, with
a constraint forbidding one. That was a leftover from a still-earlier draft in
which the storefront authored unbacked listings directly, and it did not survive
the move to projected listings — but the constraint did, and it was wrong.

It was wrong in a way that would have failed at runtime rather than at review.
`StorefrontThreadBinding.site_id` is a non-empty string, and the
`negotiation_domain_binding_complete_insert` trigger is strictly all-or-nothing:
either `domain_listing_id`, `site_id`, `offering_mode`, `domain_identity`,
`contract_major`, and `contract_minor` are all NULL, or all are present. A
listing with a null site could only enter a negotiation by also discarding its
offering mode, domain identity, and contract version. Publication would have
succeeded and the ordinary lifecycle would not.

The correction is a deletion rather than an addition. An unbacked listing is
projected from a site, so it *has* an origin site; `site_id` stays `NOT NULL` and
populated, and the discriminator says only whether that site stands behind the
listing as an admission authority. Nothing about the negotiation binding, the
completeness trigger, or the thread copy changes.

An alternative was considered: a separate `origin_site_id` column beside a
nullable admission site. Rejected — with `site_id` correctly understood as
origin, the second column has no distinct content, and a nullable admission site
would reintroduce the implicit encoding the discriminator exists to avoid.

### Explicit discriminator, never an absent value

The category is a column, not something a reader infers. `site_id IS NULL` is not
available as an encoding and neither is an absent projected field: a consumer that
re-derives the category from missing data reclassifies listings whenever data goes
missing for an unrelated reason. The discriminator is covered by the existing
immutability trigger, so a listing cannot change category after binding.

### The concrete binding type, traced

A first draft said the common identity fields stay on the binding, the union is
over admission provenance, and `CapacityBinding` is unchanged. Those three cannot
all hold, because `CapacityBinding` *is* the common identity fields — `site_id`,
`offering_mode`, `source_id`, and nothing else. An `Unbacked` marker beside it
would carry no identity, and `PublicationRuntime`'s durable comparison would lose
the token it compares.

The shape that works:

```text
PublicationBinding
    site_id         # origin site — populated for every listing
    offering_mode
    source_id
    admission: Backed | Unbacked
```

`CapacityBinding` therefore does change: from "the binding" to "a binding whose
admission is `Backed`". Capacity paths type against that narrowed form, so
reserve, commit, release, schedule, and dispatch refuse an unbacked listing at the
type boundary rather than at a runtime check — which was the point of the union
and survives the correction.

`PublicationCandidate.binding` widens to `PublicationBinding`, and the runtime's
comparison stays a comparison of the whole binding, unchanged in behaviour.

The trace that has to hold before implementation, and the reason this is a
decision gate rather than a design assertion: the same type through
`PublicationCandidate`, the durable `storefront_listing_bindings` row, the
negotiation thread copy, `bind_fulfillment_context`, reservation, release, and
provider dispatch. Each of those either reads only common fields — in which case
it takes `PublicationBinding` — or performs an effect, in which case it takes the
narrowed backed form. Any site that needs both is a site where the separation is
wrong and needs re-examining rather than casting.

Naming note: `authority` was considered and rejected for the discriminator,
because the word already carries a specific architectural meaning — which
component is the source of truth for a piece of state — and a type named for it
would read as "which authority admits this," which is what an unbacked listing
does not have.

**Naming consequence, now load-bearing rather than cosmetic.** If the central type
is `PublicationBinding` and capacity is one variant, `kit/capacity-publication`
names a variant rather than the concept. That was an open question when it was
only about the package name; it is now also about what the module's principal type
is called.

### Offer mode comes from the registration; advertisement is separately declared

An earlier reading held that some new authority had to become responsible for an
unbacked listing's offering mode. That was wrong. The storefront already resolves
the mode from the frozen contribution registry, not from the pool: publication
resolves the registration and takes its binding. Each registration binds a
contribution ID, pool offering mode, exact domain identity, and contract version.

What the pool separately declares is `deliverable_modes`, and two successive
drafts got that wrong in opposite directions. The first called the pool conjunct
vacuous for unbacked listings — which would let a pool proving no VM delivery
advertise VMs, exactly the failure that field exists to prevent. The second split
the same field into advertise- and execute-authorization and scoped only the
latter. That does not survive the contract either: `resource-pool-management` says
an empty declaration "authorizes no mode and MUST NOT be widened by a default", a
set must be "derived only from durable provider, playbook, and registered
requirement-delegate configuration that proves the pool can deliver that mode",
and a declaration wider than its proof is narrowed to empty. For an execution-less
seller the proved set is empty, so reading an advertise job out of that field
authorizes nothing.

`pool-declared-advertisable-modes` adds the second declaration, leaving
`deliverable_modes` untouched and constraining a backed pool's advertisable set to
a subset of its deliverable set. This change depends on it and consumes it: a
listing derived from a pool may advertise only a mode that pool declares
advertisable, backed or not, and `offer_resource.virtualization_type` continues to
equal the recorded offering mode for every listing.

### Absent backing in a projection is a version rule, not an inference

Backing must never be inferred from missing data — but an upgraded storefront will
read older sites whose valid pools predate the field, and "no rule" is not an
option. The cardinality rename got a deprecated alias for exactly this and backing
initially got nothing.

The resolution distinguishes two cases that a blanket default would conflate:

- A projection whose producer emits `capacity_backing` for **no** pool is an old
  producer. Every pool in it is interpreted as capacity-backed, under a
  compatibility rule that is explicit, logged, and time-limited with a stated
  removal condition. Existing supply is semantically known to be backed, so this
  states a fact about a producer version rather than guessing about a pool.
- A projection that carries the field for some pools and omits it for one is a
  **producer defect**, not an old producer, and that pool fails closed.

That keeps never-infer true at the pool level, which is where the rule matters,
while giving mixed-version deployments a defined behaviour. The alternative —
refusing any projection without the field — is a much harder deployment contract
and would make an upgraded storefront unable to read an unupgraded site at all.

Note this is a different problem from the registry republication below. That one
concerns listings already published; this one concerns the site-to-storefront
contract from which new and reconciled listings are derived.

### Rates are split out, and the goal is not complete without them

Buyers need a rate or the catalogue supports discovery but not comparison. The
rate is nevertheless not in this change, because its *shape* is: the family-grouped
capability shape `capacity-shape-pricing` is building already has three consumers,
and adding a fourth private scalar representation to avoid waiting would be the
expensive kind of shortcut. `capacity-shape-pricing` is itself blocked on
`structured-capacity-requirements`, which is unstarted, so binding this change to
it would block discovery on a two-deep chain.

`publish-indicative-listing-rates` owns the rate and carries that dependency. The
roadmap goal keeps the comparison promise and shows it as an open gap rather than
narrowing to what lands first.

What is settled and recorded here, because it constrains that change: the rate is
a **listing attribute**, not a settlement option rate. The mechanism these deals
settle through declines scalar participation, and its design records the rejected
alternative — encoding exotic contracts as rates was considered and rejected,
because the scalar machinery exists for mechanisms that want it and this class of
terms does not reduce to one number. Un-declining scalar participation would put a
number in a settlement option that the runtime does arithmetic on and an
obligation implies, with nothing behind it for a deal agreed out of band.

### Backing is immutable per durable listing

An earlier roadmap sentence said the same listing becomes capacity-backed later.
That cannot be true alongside a discriminator inside the immutability trigger, and
the trigger is the property worth keeping: moving from "no admission guarantee" to
"this exact authority stands behind this listing" is a material provenance change,
and a buyer holding a listing reference should not have it change meaning
underneath them.

So unbacked to backed is **close and republish**: the old listing closes, a new
one binds with capacity provenance. What the roadmap sentence was actually
arguing survives — no new domain, no new registry, no migration unwinding a
fabricated site — and it is reworded to say that instead.

If stable listing identity across the transition ever becomes a requirement, it
needs an explicit transactional rebinding protocol, not a relaxed trigger.

### Two reconciliation loops, not one and not none

A first draft said an unbacked listing has "no reconciler". That is too strong and
would have left a real defect: nothing would close a published listing whose
source declaration was deleted, whose pool was disabled, or whose shape changed.
An advertisement that outlives its declaration indefinitely is worse than a stale
capacity number, because no later event corrects it.

The two loops separate cleanly:

- **Source-publication reconciliation** applies to every listing. A removed or
  disabled source declaration closes its published listing; a changed shape
  updates it deterministically.
- **Capacity-availability reconciliation** applies only to backed listings, along
  with close-before-reopen. There is no availability to track for an unbacked
  listing, which is what "cannot be exhausted" actually means.

Stating both is what keeps "unbacked cannot be exhausted" true without
accidentally making "deleted unbacked advertisements never disappear" true.

### Backing is filtered exactly, and existing listings are republished

A first draft specified the registry's underreport-friendly convention for the
backing filter. That was a generalization from the wrong part of the profile:
every `offer_resource` filter in `filter-spec.yaml` is `on_missing: fail`, and the
file states that an unknown spec cannot be assumed to satisfy a stated
requirement. `on_missing: pass` appears only on `accepted_escrows` and
`settlement_options` paths, where a seller underreporting what they accept is the
concern being tolerated.

For a discriminator, permissive matching is actively wrong. A buyer asking for
unbacked listings would receive every legacy backed listing that simply predates
the field — precisely the category they excluded. So the filter is exact and
fails on missing, and existing listings are republished carrying explicit
`capacity_backed`, since they are semantically known to be backed and should not
depend on an absent field to be classified.

### One registry, not a second profile

Listing shape is a registry-deployment property: one deployment serves one filter
spec, and `schema.id` is what buyer commands match on. That makes "which
registry" look like a schema question, and it produced a wrong inference during
design — that different compute form factors might need different registries.
They do not: `vms.compute` already carries `bare_metal`, `vm`, and `container` in
one enum.

The loose-listing introductions profile is separate for two specific reasons,
neither of which is form factor: it requires option-only listings, and it leaves
`offer_resource` open with no required `gpu_model` or `region` and no vetted
enum, because sellers there describe what they broker in whatever vocabulary
fits. An unbacked compute listing carrying `gpu_model`, `region`,
`virtualization_type`, and a rate fits the compute shape. The compute spec's
`anyOf` already admits an options-only listing, so no structural change is needed
to validate one.

So this change narrows the split rather than widening it. The introductions
profile remains for genuine brokers whose offers do not reduce to compute
vocabulary.

### Unbacked listings are projected; the site is the control plane

An earlier draft had the storefront author unbacked listings directly, and
carried a `direct` / `projected` vocabulary to describe the two origination
paths. Both were dropped.

A seller trading capacity out of band is site-shaped rather than merchant-shaped:
they are the party with something to trade, whether or not they own the hardware.
Declaring through their own site's administration surface means the projection
carries their listings to the storefront and they control those listings with
their own credentials. That matters increasingly as the storefront-to-site
relationship goes from one-to-one to one-to-many: a seller with no storefront
administrative credential otherwise has no way to manage their own listings.

It also removes the cost the authored path would have added — a second
origination path in publication, and a derivation-key shape for listings with no
source identity. The projection supplies a source identity like any other pool.

**What was actually being rejected earlier.** The objection to "going through
provisioning" was to a site authority that admits against infinity, because
admission, commit, release, and restart recovery would then trust that answer. A
site declaring a pool with no capacity is a declaration, not a fabrication:
nothing reserves against it, so nothing is deceived. The distinction is between
lying in the admission path and declining to enter it.

### No source-inventory record

An unbacked listing has no derived-listing row and no storefront-local resource
table. It does have source-publication reconciliation, per the two-loops decision
above; what it does not have is a *capacity* reconciler, because the derivation
pipeline exists so a backed listing cannot overstate what is sellable and an
unbacked listing makes no such claim to check.

This is stated normatively rather than left implicit because of a specific
foreseeable regression. A seller wanting to publish many unbacked listings will
create demand for a storefront-local table to author them from, and that table
would be indistinguishable from the local physical-authority tables
`pools-9-retire-local-physical-authority` is deleting — same columns, same
purpose, reached from the other direction. A reviewer two quarters later would
have no way to tell them apart.

Note what this does *not* claim. The `listings` row and its `offer_resource`
snapshot are storefront-owned market state today and remain so; the authority
table already grants the storefront "listing, negotiation, deal, and seller
policy state — market-facing state, not physical inventory." An unbacked listing
adds no new storage category. What it must not add is an inventory model.

## Risks / Trade-offs

- **[An unbacked listing reaches a capacity path]** → Mitigated by the tagged
  union: a capacity path receiving an unbacked provenance is a type error rather
  than a runtime surprise. Cover the refusal at reservation directly rather than
  relying on it never being called.
- **[Listings decay]** → Accepted for this version. Nothing keeps an unbacked
  listing current: no capacity event contradicts it, and a seller pays nothing to
  leave one standing after the supply behind it is gone. Source-publication
  reconciliation closes a listing whose *declaration* is removed, which is the
  part the system can observe; it cannot detect a declaration the seller simply
  never updated. The intended control is registry curation — an operator
  delisting a storefront whose listings prove unreliable — which sits outside the
  registry service boundary and is not implemented here. Two consequences worth
  keeping straight: the enforcement mechanism does not exist in this repository,
  and because registries are independently operated, buyer-experience feedback is
  a property of a particular deployment rather than of the market. The equivalent
  risk for published rates is carried by `publish-indicative-listing-rates`.
  **Revisit trigger:** the first operator request for a delisting mechanism, or
  evidence that stale unbacked listings dominate a catalogue.
- **[Unbounded free settlement against one listing]** → An unbacked listing
  cannot be exhausted, which closes the capacity-exhaustion vector but moves the
  cost rather than removing it. Where settlement reveals seller contact details,
  every settlement is a reveal, and the stated control is that an address costs
  one completed negotiation under a signing identity. Identities are free and
  gasless, so that price is low and deliberately so. Sellers are expected to
  protect themselves at the address they reveal; a severable alias per storefront
  needs no code today, while a per-deal alias would need the contact payload to
  become a resolver rather than a static configuration value.
- **[A goal that cannot be completed by its own changes]** → Splitting rates out
  means Goal 7 has a gap it cannot close until `structured-capacity-requirements`
  and `capacity-shape-pricing` land, neither of which this campaign owns. That is
  a scheduling cost accepted deliberately, so discovery is not blocked behind an
  unstarted chain. It is recorded in the roadmap's gap table rather than hidden by
  narrowing the goal.
- **[Republication misses a listing]** → A listing left without an explicit
  backing value is invisible to an exact filter in both directions. Verify by
  counting listings without the field after republication rather than by
  sampling.
- **[Rollout order is not globally enforceable]** → Storefronts and registries are
  independently operated, so "republish, then add the filter" is advice to one
  operator rather than a transaction anyone can guarantee. The order still matters
  because the failure modes differ: a registry deploying the filter first
  under-returns backed listings until republication catches up, which is
  fail-safe; a permissive filter would have misclassified instead, which is not.
  Document the property rather than implying the sequence is enforceable.

## Open questions

- **Does `kit/capacity-publication` keep its name, and what is its principal type
  called?** Now more than cosmetic: if the central type is `PublicationBinding`
  with capacity as one admission variant, the package and the type both name a
  variant rather than the concept. Deferred; no task renames either.
- **What is the `derivation_key` shape for an unbacked listing?** Expected to
  fall out of the projection's source identity, since these listings are
  projected, and the column is `NOT NULL UNIQUE` so it needs an answer before
  anything binds. A decision gate in `tasks.md` rather than an ordinary
  implementation step, because choosing it quietly would settle a collision-safety
  property in a place no reviewer looks.
- **Does an unbacked pool still have to name a fulfillment provider?**
  `PoolCreate` requires one. `pool-declared-advertisable-modes` removes the reason
  that was blocking — an execution-less seller no longer needs a provider that
  *proves a deliverable mode* — but the pool still names a provider it must never
  dispatch to. Deferred rather than resolved with a publication-only provider
  kind, which that change rejects for putting a no-op executor in the fleet; the
  fail-closed guard in `project-capacity-resources-without-hosts` is what makes it
  safe in the meantime.
- **When is the absent-backing compatibility rule removed?** It is time-limited by
  design, and this repository has no fleet-wide deployment signal to gate removal
  on, since sellers self-host their own site and storefront deployments. Same
  shape as the cardinality alias's removal question, and deliberately not
  prescribed in `tasks.md`.
- **Does a rate arbitrageur with no hardware run a site service?** The model
  assumes site-shaped sellers deploy one, which is materially lighter with no
  hosts — no executor connections, no playbooks, no watchdog — but is still a
  service. If that proves too heavy, a storefront-hosted path returns as a
  separate question, and with it the broker-identity problem this design avoided.
- **Where does the seller's contact payload live under one storefront serving
  several sellers?** Not this change's concern while settlement is out of scope,
  but the current one-static-payload-per-storefront shape is coherent only at one
  seller per storefront. Named here because the constraint is invisible from
  inside `compose-contact-exchange-across-compute`.

## Migration Plan

1. Add the backing discriminator to the binding schema, covered by the existing
   immutability trigger. Additive; existing rows are capacity-backed. `site_id`
   is untouched and stays `NOT NULL`.
2. Introduce the admission-provenance union with `CapacityBinding` unchanged as
   one variant.
3. Scope site-pinned routing and capacity reconciliation to backed listings, and
   split pool advertise-authorization from execute-authorization.
4. Add the projected property and publish backing.
5. Republish existing listings carrying explicit `capacity_backed`, then add the
   exact registry filter. In that order — a filter added first would exclude every
   legacy listing from backed queries in the window before republication
   completes.

Existing listings bind, negotiate, reconcile, and route exactly as before at every
step. Rollback before step 5 is a code rollback; the discriminator column remains
and is ignored by the restored reader. Rollback after step 5 leaves the published
backing field in place, which a restored reader ignores.
