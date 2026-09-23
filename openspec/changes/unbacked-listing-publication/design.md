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

### Findings verified against the code, 2026-09-23

The design phase re-traced the plan against the code once all three blocking
prerequisites had archived. These findings shaped the decisions below; each
decision names the finding it answers.

- **The only storefront reader of pool declarations gates on delivery.**
  `_projected_pool_rows` in `domains/vms/listings/reconciler.py` publishes a pool
  only when `pool_delivers_offering_mode(policy_tags, "vm")`. An unbacked pool's
  deliverable set is empty by construction, so it publishes nothing today. The
  bare-metal and API-credit storefronts read no pool tags.
- **The seller's inventory guard reads availability on every round, for any
  listing.** `has_matching_inventory_guard`, prepended unconditionally to the VM
  seller policy, fetches a capacity snapshot from every configured site each round
  and passes if any row anywhere is `available` and matches `region` and
  `gpu_model`. It is not scoped to the listing's source; it compares `region`
  against declaration attributes while the listing's region comes from the pool's
  `region` tag; and it checks no quantity. The binding trace did not cover it.
- **The runtime's round carrier lacks the binding.** `RoundRequest` is the only
  `kit/negotiation-runtime` carrier without the opaque `binding` that
  `ResolvedNegotiation`, `OpeningRecord`, and `Acceptance` carry.
- **Source-publication and capacity-availability reconciliation are one
  predicate.** Both triggers — the site event feed and the publication cycle
  (`publish --watch`) — close a listing when its structural key is absent from
  `available_compute_slices`, whose slices run `range(1, max_member_available + 1)`.
  A removed source and exhausted availability are indistinguishable.
- **Open listings never refresh their payload.** The event reconciler reopens by
  republishing the stored row, and the publication cycle skips candidates whose
  keys are open. A changed `gpu_model`, region tag, or price never reaches an open
  listing, backed or not.
- **Declaration edits reach the event feed; pool edits do not.** A declaration
  upsert emits `reserved`, `released`, or `capacity_changed` by direction. A pool's
  tag change or disablement emits no capacity event. `_projected_pool_rows` reads
  per-resource `enabled` but not the pool's.
- **`derived_compute_listings` is half-retired.** The common binding is a strict
  superset of it, and `migrate-storefront-domains` installs triggers aborting every
  write to it. The reconciler still writes it after close and reopen, and the
  publication cycle's reopen still looks listings up in it. On a migrated database
  the close path's write and the cycle's reopen are expected to abort or collide on
  the binding's `UNIQUE` derivation key. Planning confirmed the abort by test; see
  "Findings verified during planning".
- **A missing GPU count is silent, not fabricated.** `_projected_resource_usage`
  reads `int(capacity.get("gpu_count") or 0)`, so a declaration without it yields no
  slices and no explanation. The `or 1` defaults in `prepare_vm_listing_binding`, the
  structural key builders, and the stored-listing readers are latent: every
  derivation path currently supplies a positive count.
- **A fungible pool's listing key omits the resource's kind.** The key is
  `(site, pool, gpu_count)`. A pool whose members declare different `gpu_model`
  values publishes the first model encountered and sums availability across every
  member. Admission is correct — the claim carries `gpu_model` and `region` and the
  site admits only matching members — so the defect is confined to storefront
  aggregation.
- **The admission predicate is already exported.** `kit/site` exports
  `dict_resource_satisfies_claim` for callers outside the site; the VM storefront
  uses it only as the `most_available` placement matcher.
- **Pools are never hard-deleted.** `delete_pool` refuses and the `DELETE` route
  disables, so a pool ID cannot return with different backing within one site
  database.
- **The binding schema's triggers are created with `IF NOT EXISTS`,** so extending
  the immutability trigger needs a new migration that drops and recreates it. The
  binding table has three writers: two inserts in `core_storefront.sqlite_client`
  and the legacy migration tool's `INSERT OR IGNORE`. (Planning found a fourth; see
  below.)

### Findings verified during planning, 2026-09-23

The planning review re-read the design against the code and settled the "to verify"
list. These findings shaped the decisions under "Decisions added in the planning
review" below; each names the finding it answers.

- **Nothing in a deployed stack runs the publication cycle.** `run_watch_loop`'s
  docstring says `serve` uses it; `serve` does not. The storefront's startup starts the
  negotiation watchdog, settlement servicing, fulfillment resume, the site-projection
  poller, and the capacity-event poller, and nothing else. The only caller is
  `publish --watch`, a separate process that reads the storefront database directly
  and publishes by HTTP to its own storefront. No compose, Helm, or e2e configuration
  runs it: every e2e scenario creates listings through the admin API. So pool-level
  changes, the terms refresh this design adds, and republication of existing listings
  would never run in a deployed stack.
- **A seller's close and a reconciliation close are indistinguishable.** Both go through
  `PublicationRuntime.close` and set `status = 'closed'`. `closed_available_listing_ids`
  reopens any closed bound listing whose slice is available, so the next `released`
  capacity event already undoes a seller's explicit close. `resume` only toggles
  `paused` and republishes; it does not reopen a closed listing.
- **The capacity-event reopen path bypasses the identity rule.** It keys on the
  structural key, which does not capture `gpu_model` or `region`, and republishes the
  stored row, so a listing closed for identity divergence would reopen on the next
  release event and would not carry `capacity_backing`.
- **A paid deal on an unbacked VM listing would reach fulfillment after funding.** The
  VM storefront composes only `alkahest.v1` and `fiat.stripe.v1`, both delivering
  through `fulfill_vm_settlement`; `[pricing].settlements` defaults apply to every
  candidate; and `fulfill_vm_obligation` calls `capacity_binding_for_listing` then
  reserves. The capacity type boundary would refuse only after escrow was funded.
- **Field provenance is decided per listing, not per field.** `resolve_region` takes the
  pool's `region` tag and falls back to the local `compute_capacity_pools.region`;
  `gpu_model` takes the declaration attribute and falls back to the local value. The
  permanent spec already says `region` has no storefront override.
- **Round-zero evaluation runs the inventory guard.** `compute_round_zero_decision`
  (the evaluate-negotiate dry run) runs the full default seller chain, so it is not an
  identity-only consumer.
- **The default seller hook is built through the domain contract.**
  `_default_seller_round_hook` calls `domain.storefront.run_negotiation_policy`, an
  untyped `DomainCallable` in `market_core`, so the VM factory can gain a parameter
  without a core change.
- **The migrated-database abort is confirmed by test.** With the retirement triggers
  `migrate-storefront-domains` installs, `mark_derived_listings_closed`,
  `mark_derived_listings_open`, and `record_derived_listing` each raise
  `IntegrityError: derived_compute_listings is retired`. The event close path raises
  after the listing has already closed at the registries. This change removes those
  writers, so the defect is fixed here rather than recorded.
- **Region at admission is confirmed by reading.** The site's feasibility view merges a
  declaration's attributes with the resource's own facts and never pool tags, while the
  VM claim carries `region` from the listing, which may come from the pool's `region`
  tag. A backed pool that declares region only as a tag cannot admit. Recorded against
  `pools-8-capacity-projection-and-listing-hints`, which owns the region hint.
- **A disabled pool is still projected.** `resource_pool_projection` groups by resource
  and carries the pool's `enabled` in `pool_metadata`; `_projected_pool_rows` never reads
  it, so a disabled pool's listings still publish.
- **Bare metal writes the binding table too.** `arkhai_bare_metal_storefront`'s
  `sqlite_client` constructs `StorefrontListingBinding.from_source_envelope`, and its
  `migrations.py` has a raw `INSERT OR IGNORE INTO storefront_listing_bindings`. That is
  a fourth writer. Bare metal publishes no `capacity_backing` today and its listing model
  has no such field; no other change owns adding it.
- **API credits are unaffected beyond types.** Their registry schema admits extra
  `listing_resource` fields, but they have their own schema identity and every listing is
  quota-backed. With the binding types chosen below, `capacity_binding_from_listing_resource`
  already returns a valid `PublicationBinding`.
- **Mixed site and storefront versions are supported but not reproducible at system
  level.** Sellers self-host sites, which is why the compatibility rule exists, but an
  upgraded provisioning service refuses to start with a pool lacking valid declarations,
  so no current image can emit an old producer's projection. The cardinality-alias
  precedent could simulate skew through the current site; this rule cannot.
- **`cli_logs.py` also reads the storefront database directly.** Out of scope; recorded
  below.

## Goals / Non-Goals

**Goals.** Make an unbacked listing a legal shape. Keep every capacity-admission
path unchanged and unasked. Put backed and unbacked compute supply in one
catalogue a buyer can query together. Leave a seller's supply able to become
capacity-backed later without a new domain, registry, or fabricated site. Fix the
publication-path defects the findings expose where this change rewrites the code
that contains them, rather than rewriting the same code twice.

**Non-Goals.** No published rate — `publish-indicative-listing-rates` owns
comparison. No backing transition on one durable listing — that is
close-and-republish. No new domain, no new registry, no settlement mechanism, no
finite unbacked listings. No automatic storefront-side migration of a listing
whose physical resource changes, and no fix for mixed-kind fungible pools: both
belong to the listing-key completion recorded as an open question in
`publish-multidimensional-listing-shape`. Each is owned elsewhere or deferred with
a reason below.

## Decisions

### Vocabulary

The terms this change is written in are settled. They live here and in
`pool-declared-advertisement-and-backing` rather than in `ARCHITECTURE.md` until
they are true: that change promotes the Terms entries at its closeout, because a
pool declaring its backing is the point at which the concept exists, and this
change promotes the listing-level boundary statements at its own. The alternatives
considered are recorded because they are the kind that get re-proposed.

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

Two domains would also publish identical `listing_resource` vocabulary into one
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
immutability trigger, so a listing cannot change category after binding, and no
writer may omit it; the binding-schema decision below records how both are enforced.

### The derivation key needs no new shape

`build_storefront_derivation_key` takes `site_id`, `offering_mode`, the domain
binding, and an opaque `source_identity`, canonicalizes them, and hashes. Every
input exists for an unbacked listing: the origin site is populated, the mode
resolves from the frozen registration, and the domain binding is unchanged. Its two
guards — non-empty site and mode equality with the durable binding — both hold. So
the existing builder is reused unchanged and the VM domain's versioned source
envelope carries the same fields it carries today.

Backing deliberately does **not** go into the envelope. An earlier reading of
close-and-republish suggested it had to: `derivation_key` is `NOT NULL UNIQUE`, the
binding row is immutable and survives a listing closing, so a republished listing
deriving from the same site, pool, mode, and domain would collide on the unique
index and the transition would deadlock. But backing is fixed at pool creation, so
a supply move between backed and unbacked is a move between *pools*. The `pool_id`
differs, the key differs by construction, and putting backing in the envelope as
well would be redundant encoding of something that cannot vary independently of a
field already there.

An earlier draft also proposed omitting capacity-derived fields from the envelope
for unbacked listings, on the premise that an unbacked pool has no capacity data
and the `or 1` default would silently bake a meaningless quantity into the identity.
That premise was wrong: an unbacked pool's capacity resources declare shape *and*
quantity, and what is absent is availability rather than declared capacity. The
`or 1` defaults are latent rather than live — see Context — and the fix is to make
derivation strict and have a declaration without the quantity visibly yield no
listing, rather than to omit the field; see the enumeration-quantity decision below.

Verified against the code on 2026-09-23: the builder and the envelope are unchanged,
and pool-level backing immutability has landed (`capacity_backing_immutable`). Pools
are never hard-deleted — `delete_pool` refuses and the `DELETE` route disables — so a
pool ID cannot return with different backing within one site database. The one
exception, a site database rebuilt from scratch, is handled by the identity rule below
without an envelope change.

### The concrete binding type, traced

A first draft said the common identity fields stay on the binding, the union is
over admission provenance, and `CapacityBinding` is unchanged. Those three cannot
all hold, because `CapacityBinding` *is* the common identity fields — `site_id`,
`offering_mode`, `source_id`, and nothing else. An `Unbacked` marker beside it
would carry no identity, and `PublicationRuntime`'s durable comparison would lose
the token it compares.

The shape that works, as first drafted, was one type carrying the common identity
fields plus an `admission: Backed | Unbacked` field. The planning review replaced
that field with two sibling classes, because Python cannot make "a binding whose
admission is `Backed`" a type, and because `admission` would have been a second name
for what every other surface calls `capacity_backing`:

```python
@dataclass(frozen=True, slots=True)
class _ListingIdentity:
    site_id: str        # origin site — populated for every listing
    offering_mode: str
    source_id: str

@dataclass(frozen=True, slots=True)
class CapacityBinding(_ListingIdentity):
    capacity_backing: ClassVar[Literal["backed"]] = "backed"

@dataclass(frozen=True, slots=True)
class UnbackedBinding(_ListingIdentity):
    capacity_backing: ClassVar[Literal["unbacked"]] = "unbacked"

PublicationBinding = CapacityBinding | UnbackedBinding
```

What this keeps:

- **One name.** `capacity_backing` is the only spelling of the concept, on the pool
  tag, the binding column, the published listing, and the binding class. Readers take
  it from the binding (`listing_resource["capacity_backing"] =
  binding.capacity_backing`) rather than branching on the class.
- **The type boundary.** `CapacityBinding` keeps its name and every capacity-path
  signature is unchanged. `UnbackedBinding` is a sibling, not a subclass, so the
  existing `isinstance(binding, CapacityBinding)` guards become exactly the backed-only
  check. Nothing type-checks `kit/capacity-publication` today, so the runtime
  `isinstance` check is the enforcement either way; the signature is what documents it.
- **The durable comparison.** Dataclass equality compares classes, so
  `CapacityBinding("s", "vm", "p") != UnbackedBinding("s", "vm", "p")` and
  `_require_persisted_binding` catches a backing mismatch with no change to its body.
- **Fail-closed loading.** A durable row is loaded through an explicit table,
  `{"backed": CapacityBinding, "unbacked": UnbackedBinding}[durable.capacity_backing]`,
  so an unknown value raises rather than defaulting.

A single class with a `capacity_backing` field was the alternative. It loses the
signature-level statement that capacity operations take only backed bindings, needs a
value check inside every capacity method, and renames or aliases every
`CapacityBinding` call site across both domains and API credits. It gains nothing the
sibling classes lack.

`PublicationCandidate.binding` widens to `PublicationBinding`, and the runtime's
comparison stays a comparison of the whole binding, unchanged in behaviour.

**The trace, completed.** Every non-test consumer was classified, and no site needs
both forms — which was the test of whether the separation is right.

Taking `PublicationBinding`: `PublicationCandidate.binding` and `BoundListing.binding`;
`PublicationRuntime._require_persisted_binding`, which compares supplied against
durable; the `PublicationDomainHooks.binding_for_listing` protocol return;
`require_capacity_binding` in the VM negotiation runtime, which compares `site_id`
and `offering_mode` and nothing else; settlement-artifact construction, which
carries site, mode, and source; and the binding constructors in both domains'
capacity clients, `listing_service`, and `publication_service`.

Taking the narrowed backed form: `CapacityRuntime.require_binding`, which validates
the site is a configured capacity site, and its reserve, commit, and release
operations; the reservation binding constructed in the VM admin controller; and the
capacity hold in the negotiation runtime.

Three consequences that were not visible before the trace:

**Two of the VM negotiation runtime's three `isinstance(..., CapacityBinding)`
guards become wrong.** The guard before the capacity hold is correct and stays,
narrowing to the backed form. But the guard before settlement-artifact construction
and the guard on the negotiation opening both protect identity-only work — the
second leads directly into `require_capacity_binding`, which compares site and mode
alone. Left as they are, they would reject every unbacked listing at negotiation
time with "VM negotiation has no frozen capacity binding": a runtime failure on
exactly the path the integration coverage exists to protect. They relax to identity
checks.

**`PublicationDomainHooks` is a protocol**, so widening its return type is a
kit-boundary change that both implementing domains move with.

**`apicredits` is in scope.** It has its own `capacity_binding_from_offer` and
`publication_service`. API credits are capacity-backed by a quota resource, so
nothing about their behaviour changes, but their types and the protocol signature
move.

Naming note: `authority` was considered and rejected for the discriminator,
because the word already carries a specific architectural meaning — which
component is the source of truth for a piece of state — and a type named for it
would read as "which authority admits this," which is what an unbacked listing
does not have. `admission`, used in the first draft of the shape above, was
dropped for the one-name rule.

**Naming consequence, now load-bearing rather than cosmetic.** If the central type
is `PublicationBinding` and capacity is one variant, `kit/capacity-publication`
names a variant rather than the concept. That was an open question when it was
only about the package name; it is now also about what the module's principal type
is called.

**What the trace missed.** Two consumers read listing state during negotiation
without appearing in it. The seller's inventory guard reads live availability on every
round for any listing; its decision is recorded below. Round-zero evaluation
(`compute_round_zero_decision`) resolves the binding and compares site and mode only,
so its own binding use widens with the other identity-only consumers — but the planning
review found that it also runs the full default seller chain, inventory guard included,
so it passes its resolved binding to the default policy exactly as `evaluate` does. The
test of the separation still holds: neither needs both forms. The guard needs the
binding's variant during a round, which is why `kit/negotiation-runtime` forwards the
binding on `RoundRequest`.

### A listing's identity is the physical resource it offers

No permanent specification said which fields make two listings different or what
may change under a stable listing ID. The existing "Commercial mapping identity"
requirement makes derivation keys collision-resistant over `site_id`, `pool_id`,
and `resource_id` and says nothing more. This change adds the rule, because
source-publication reconciliation now updates open listings and every such update
has to fall on one side of it.

**The rule.** A listing's identity is the physical resource it offers: the supply
it draws from (site, and pool or Physical Resource), what the resource is
(offering mode, resource type and subtype, and categorical attributes such as
`gpu_model`), where it is (`region`), and how much of it one listing offers (the
enumerated slice quantity, and every other declared dimension the listing
publishes). Everything else — price and pricing hints, settlement options,
maximum duration, SLA — is a term of sale.

**Why the line falls there.**

1. A listing ID is what a buyer saves, negotiates against, and what accepted terms
   and settlement records reference. Changing what is sold under the same ID
   reinterprets every one of those references. This is the same reason capacity
   backing is fixed at pool creation.
2. Terms of sale are meant to move. Price is what negotiation adjusts, and a price
   change that orphaned buyer references would make every repricing a delisting.
3. The identity fields are what admission matches. The capacity claim carries
   `pool_id` or `resource_id`, `region`, `gpu_model`, and the requested dimensions,
   and the site admits only matching members, so "what the listing is" and "what a
   reservation will look for" are one set of fields.

Capacity backing sits outside this split. It is not a property of the physical
resource but of whether an admission authority stands behind the listing, and it is
fixed on the binding at creation; the backing decisions govern it.

Provenance is not the rule. The pool's `pricing` tag is site-sourced and is a term;
`region` is identity whether it came from the pool's tag or from the storefront's
local fallback. Provenance decides a different question — what the seller's inventory
guard rechecks against the site — and the planning review found it is decided per
listing rather than per field: `region` and `gpu_model` each come from site data when
the site supplies them and from a local fallback when it does not. The guard therefore
compares against a fresh derivation of the listing rather than consulting a per-field
table; see "The inventory guard compares against a fresh derivation" below.

**A listing commits only to the fields it publishes.** A field a listing does not
publish is no commitment: the seller has promised nothing about it, and a buyer
receives whatever the seller supplies. Consequently:

- Reconciliation never adds an identity field to a listing that did not publish
  one. That would make a new commitment under an existing identity. Dimensions a
  later change begins publishing appear only on listings published after it.
- A field the stored listing does not publish is not a divergence from its source
  and never closes it.
- The rule governs fields a listing *describes*. The field a domain *enumerates*
  listings by is different: in the VM domain each listing is "N GPUs of this
  resource", so a declaration omitting `gpu_count` leaves nothing to enumerate and
  yields no listing, rather than a listing that makes no GPU commitment. See the
  enumeration-quantity decision below.

**What this change does when an identity field changes.** The current keys capture
site, pool or resource, and `gpu_count`, not `gpu_model`, `region`, type, or other
dimensions. Building storefront-side migration for the fields the key does not
capture is out of scope, so:

| Change | Behavior |
|---|---|
| A term of sale | The open listing updates in place, locally and at every registry |
| An identity field the key captures (shrink, disable, removal) | The listing closes; a new key publishes a new listing |
| A published identity field the key does not capture | The listing closes and reopening is refused while the difference persists, with a logged refusal naming the source and fields. The operator's path is a new pool or declaration, as for a change of backing |

The seller's inventory guard independently rejects any in-flight negotiation on
such a listing, since its published field no longer matches its source.

A site database rebuilt from scratch is the one way a pool ID can return with the
opposite backing. The storefront sees a live backing value that disagrees with the
bound discriminator and applies the third row. A republish from the recreated pool
computes the same derivation key, so publication finds the existing closed listing by
that key and refuses to reopen it, logging the refusal, rather than binding anything
new. Tests assert that refusal: the listing stays closed, the refusal is logged, and no
new binding is created. The binding's `UNIQUE` constraint remains only a storage
backstop. No envelope change is needed for a site reset.

**The eventual fix belongs to `publish-multidimensional-listing-shape`,** recorded
there as an open question because that change is the first to publish a field that
can differ between members of one pool. The direction: the structural key and the
derivation envelope carry a canonical digest of the resource's kind over the
identity fields the listing publishes, so a kind change is a key change and the old
listing closes while a new one publishes — storefront-side migration arrived at
through the key rather than built as a mechanism; fungible pools derive listings per
kind partition, evaluating members with the site's exported admission predicate,
which removes the mixed-kind summing defect. Write-time refusal of mixed-kind pools
at the site was considered and rejected there: fungibility is a domain-resolved
optional pool tag, so the refusal would need a new site read of pool state, which
`docs/development/ARCHITECTURE.md`'s package-layer section says not to add while the
existing exception stands. Until then this change leaves mixed-kind fungible pools'
derivation unchanged and logs a warning naming the pool and the differing fields.

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

`pool-declared-advertisement-and-backing` adds the second declaration, leaving
`deliverable_modes` untouched and constraining a backed pool's advertisable set to
a subset of its deliverable set. This change depends on it and consumes it: a
listing derived from a pool may advertise only a mode that pool declares
advertisable, backed or not, and `listing_resource.offering_mode` continues to
equal the recorded offering mode for every listing.

That change also owns the `capacity_backing` pool declaration itself. An earlier
split put the two tags in different changes and produced a dependency cycle — the
advertisement change's subset rule is scoped to backed pools, so its normative text
needed a concept owned by the change depending on it. Both tags are declarations a
site makes about a pool; everything that reads them is storefront-side and belongs
here.

**Where this is wired.** The only storefront reader of pool declarations is
`_projected_pool_rows`, which gates on `pool_delivers_offering_mode(tags, "vm")`. It
resolves each pool through `resolve_pool_declarations` instead, under the projection
rule below, gates on `advertises("vm")`, and carries the resolved backing onto the
candidate, where publication records it as the binding's discriminator and the
published `listing_resource.capacity_backing`. The same resolved value selects the
slice range in the reconciliation decision below.

### Absent tags in a projection are a version rule, not an inference

Backing must never be inferred from missing data — but an upgraded storefront will
read older sites whose valid pools predate both new tags, and "no rule" is not an
option. The cardinality rename got a deprecated alias for exactly this; the new
tags initially got nothing.

The consuming rule is only tractable because the producing side guarantees
completeness. `pool-declared-advertisement-and-backing` derives both values for
every existing pool on upgrade and requires that a producer emitting either tag
emits both for every pool it projects. Without that guarantee this rule collapses:
an upgraded site holding legacy pools would emit the tags nowhere and read as an
old producer indefinitely, and the first explicitly unbacked pool an operator
created would turn every other pool into a partially-populated omission and fail
nine working pools closed on a correct operator action.

**Detection is joint, per site, per projection generation.** Each projected pool is
resolved through `market_resource_pools`' `resolve_pool_declarations`. A site's
projection generation in which *no* pool carries *either* tag comes from a producer
that predates them: every pool reads as backed, and `deliverable_modes` serves as
advertisement authorization. Neither is a permissive default; each reproduces the
old contract exactly, because every pool was admissible before the declaration
existed and delivery authorization was the only mode authorization there was. In
any other generation, a pool whose declarations are absent, malformed, or violate a
cross-tag rule is unresolvable.

An earlier draft applied the rule per tag. The two readings differ only for a
projection carrying one tag on some pools and neither elsewhere, which no producer
emits: the prerequisite introduced, migrated, and requires both tags together. The
joint reading matches the resolver, which raises `MissingPoolDeclarationError` only
when every problem is an absent tag; it gives one detection and one operator notice
instead of two; and it makes the two compatibility readings one rule, removed
together.

| Projection from site S | Reading |
|---|---|
| No pool carries either tag | Old producer: every pool backed, delivery authorizes advertisement |
| Every pool carries both tags | Normal |
| Some pools carry both; P3 carries neither | P3 unresolvable |
| P1 carries backing only; P2 and P3 carry neither | Not an old producer: all three unresolvable |
| P1 declares `capacity_backing: "Backed"` | P1 unresolvable — a discriminator gets no tolerant reading |
| P1 is backed and advertises a mode it does not deliver | P1 unresolvable |

Per-site evaluation handles mixed fleets, and per-generation evaluation handles a
producer upgrading in place: the compatibility reading of an old site is exactly what
the prerequisite's migration writes when that site upgrades, so its listings do not
move.

**An unresolvable pool is held, not closed.** It yields no new candidates, and its
existing listings are excluded from both close and refresh until it resolves again.
Closing them would turn a producer defect or a half-finished producer rollout into a
delisting, recoverable but visible churn for something that is not a change to
supply. Holding follows the reconciler's existing rule that an unknown answer is not
an answer of zero. It remains fail-closed where it matters: nothing new is derived
from declarations the storefront cannot read, and a held listing's backing comes from
its immutable binding, never from the unreadable tag. The slice builder reports
unresolvable pools separately from pools that resolved and yielded nothing, so the
stale predicate can tell the two apart.

**Operators see it.** Following the `listing_cardinality_mode_explanations()`
precedent, the storefront's system status reports, per site, that a producer
predating the declarations is being read under the compatibility rule, and per
unresolvable pool, the resolver's problem codes. The log line is emitted once per
site generation rather than on every reconcile.

The compatibility reading is retained until a future change acquires a reliable
signal that no producer relies on it. Sellers self-host their sites, so no release
count is a meaningful removal condition.

This concerns the site-to-storefront contract from which new and reconciled listings
are derived. The registry republication below concerns listings already published and
is a separate problem.

### The seller's inventory guard checks the listing against its own source

`has_matching_inventory_guard` answers "is there free matching hardware anywhere I
sell from?" by comparing `region` and `gpu_model` against every available row in
every site. For an unbacked listing that answer is meaningless: nothing is ever held
against an unbacked pool, so the site always reports its resources `available`. The
guard therefore passes by accident when attributes happen to line up, rejects with
`no_matching_inventory` when the listing's region comes from the pool's `region` tag
(which the guard compares against declaration attributes), and fetches a snapshot
from every site on every round.

Two narrower fixes were considered and rejected. Making the guard a pass-through for
unbacked listings — reading the published `capacity_backing`, or receiving a
"no availability applies" marker — keeps the guard as incomplete as it is and loses
a check buyers need: an unbacked listing's published shape should still match what
its seller declares. Making the guard configurable was rejected outright; it is a
default guard because no seller should be able to publish shapes it stops declaring.

**The guard becomes expressive instead.** Seller feasibility splits into two checks:

1. **Declared match**, for every listing: every published field sourced from the
   declaration or pool is rechecked against that source — the listing's *own* site
   and pool or resource, never any row elsewhere. Categorical fields are equal;
   quantities fit the declared capacity. Fields whose authority is the storefront
   (pricing, a storefront region override) are not rechecked, because the site has
   nothing to confirm.
2. **Availability**, for capacity-backed listings only: the published quantity is
   currently free, from the advisory snapshot today.

The invariant is stated over *published* fields so the guard's coverage grows with
publication. When `publish-multidimensional-listing-shape` publishes vCPU, RAM, and
disk, the guard rechecks them with no guard change. That change is not a
prerequisite.

**Examples**, for an unbacked listing "4× H100, 256 GiB RAM, us-east" derived from
pool `broker-a` and declaration `res-1` = `{gpu_count: 8, ram_gb: 512, gpu_model:
H100}` with pool tag `region: us-east`:

- Normal: `res-1` is present and enabled, model and region equal, 4 ≤ 8 and
  256 ≤ 512. The guard passes without consulting availability.
- The seller shrinks `res-1` to 128 GiB before reconciliation closes the listing:
  the declared match fails and the guard rejects with a reason distinct from "nothing
  free".
- The seller disables `res-1`: the guard rejects, where today a backed H100 in
  another site would have satisfied it.
- A backed listing of the same shape with only two GPUs free: the declared match
  passes, availability fails, and the guard rejects with `no_matching_inventory` as
  today.

In steady state source-publication reconciliation closes a listing its declaration
no longer supports; the guard rechecks the same rule at negotiation time and covers
the window before reconciliation runs, the layer-by-layer recheck the repository
already uses for pool modes and host requirements.

**Mechanics.**

- The guard needs the listing's source identity and binding variant, which only
  the durable binding carries. `kit/negotiation-runtime` forwards
  `ResolvedNegotiation.binding` onto `RoundRequest`, symmetric with the other
  carriers and schema-opaque. Re-resolving the binding inside the VM round hook was
  rejected as a second resolution path that could drift from the one the runtime
  validated.
- The declared match and the availability check are both computed from a fresh
  derivation of the listing's own source; see "The inventory guard compares against a
  fresh derivation" under the planning-review decisions. An unbacked negotiation makes
  no site call; a backed listing's availability comes from its pinned site only.
- `SellerRoundHook` in `kit/policy` is not widened. The VM default-hook factory gains a
  binding parameter and is built per round, in `evaluate` from `RoundRequest.binding`
  and in round-zero evaluation from the binding it already resolved. An
  operator-injected custom hook receives the same inputs as today and owns its own
  availability decision.
- A declared-match failure uses a new reason, distinct from `no_matching_inventory`,
  so that reason keeps meaning "nothing free". `add-harness-scenario-contract` treats
  `no_matching_inventory` as observable and is told of the new reason.
- The API-credit storefront's own guard reads quota rows and is unaffected.

**Relationship to planned work.** `capacity-shape-pricing` task 5.1 planned to extend
the guard to quantitative checks; the declared match lands here, and that task
narrows to checking a *buyer-requested* shape once shapes are negotiable.
`capacity-shape-envelope` adds pool-bounded admissibility beside the guard.
`negotiation-capacity-feasibility-probe` replaces the snapshot as the availability
source. The shared admission predicate is the intended single implementation of
matching across all of them; see the open question in
`publish-multidimensional-listing-shape`.

### Source publication reconciles every listing; availability reconciles backed listings

A first draft said an unbacked listing has "no reconciler". That is too strong and
would have left a real defect: nothing would close a published listing whose source
declaration was deleted, whose pool was disabled, or whose shape changed. An
advertisement that outlives its declaration indefinitely is worse than a stale
capacity number, because no later event corrects it.

The two concerns separate in the requirements:

- **Source-publication reconciliation** applies to every listing. A removed or
  disabled source closes the listings derived from it, and a changed source is
  reflected deterministically according to the identity rule.
- **Capacity-availability reconciliation** applies only to backed listings, along
  with close-before-reopen. There is no availability to track for an unbacked
  listing, which is what "cannot be exhausted" actually means.

**In the code they are one predicate, and that is kept.** Both triggers — the site
event feed and the publication cycle — close a listing whose structural key is
absent from the slice set. The separation is made in the slice builder instead: an
unbacked pool's slices range over its *declared* quantity, a backed pool's over its
*available* quantity. Availability then never enters an unbacked listing's slice set,
so capacity deltas cannot move it, while removing, disabling, or shrinking its source
removes its keys and closes it through the same path a backed listing uses. A second
loop was rejected as more code for the same observable behavior.

Examples, for an unbacked pool `broker-a` whose declaration `res-1` declares eight
GPUs and so publishes eight listings:

| Change | Result |
|---|---|
| A buyer settles on the 4-GPU listing | No reservation, no event, nothing moves |
| The seller disables `res-1` | A `reserved` event; all eight keys are absent; all close. Re-enabling reopens the same identities |
| The seller shrinks `res-1` to four | Slices 5–8 close; 1–4 remain |
| The seller grows `res-1` to eight again | The publication cycle reopens or publishes slices 5–8 |
| The seller edits `gpu_model` | The identity rule's third row: the listings close and are held |
| The operator changes the pool's price | Terms refresh in place on all eight |
| The operator changes the pool's `region` tag | A published identity field the key does not capture: close and hold |

**Terms of sale are refreshed in place, for every listing.** The findings show that
no open listing's payload is ever re-derived. The publication cycle therefore gains a
refresh pass: it re-derives each open candidate and compares it with the stored
listing. An identity-bearing difference the key captures cannot occur on an open key,
because a different envelope is a different key. A difference in terms updates the
listing in place, locally and at every registry, through the existing update request.
A difference in a published identity field the key does not capture follows the
identity rule's third row. This fixes the payload staleness for backed listings as
well; it was accepted as scope because this change rewrites the same functions, and
fixing them once in a forwards-compatible way is cleaner than a separate change
rewriting them again. How the pass is realized, and the full table of outcomes it acts
on, are in "Refresh and reopen flow through the existing publication-source seams" and
"One comparison gates refresh and every reopen path".

**Triggers.** Declaration changes reach the event feed. Pool-level changes (a tag
edit, disablement, a narrowed `advertisable_modes`) emit no capacity event and are
caught by the publication loop, which the planning review moved into the storefront
process; see "Publication runs as a storefront lifecycle loop". The site projects a
disabled pool with `enabled: false` in its metadata rather than omitting it, so
derivation reads that value: a pool declaring `enabled: false` yields no candidates,
and its listings close through source reconciliation like any removed source.

### Publication stops reading and writing `derived_compute_listings`

The requirement "an unbacked listing has no derived-listing row" was written to stop a
specific regression: demand for a storefront-local table to author many unbacked
listings from, which would be indistinguishable from the local physical-authority
tables `pools-9-retire-local-physical-authority` deletes. `derived_compute_listings`
is not that table. It sources no shape or capacity; it records which listing a slice
became, and the common binding already records that and more.

Keeping the requirement literal would have added a backing branch to every close and
reopen path, and broken this design's own reopen for unbacked listings: the
publication cycle's reopen looks listings up in that table, so an unbacked listing
with no row could not be reopened and would instead collide on its derivation key.

**Decision.** The requirement is restated to its purpose, and the table's retirement
is finished on the paths this change rewrites:

- An unbacked listing is derived only from the site projection; no storefront-local
  table sources its shape or capacity. Its storefront-local records are its listing
  row and its immutable binding.
- The publication cycle finds a closed listing by the candidate's derivation key in
  `storefront_listing_bindings`, which is exact and needs no structural-key
  reconstruction.
- Close and reopen stop writing `derived_compute_listings`, and fresh databases stop
  maintaining it — the end state migrated databases already have.

This makes the rule hold for every projection-derived listing without a backing
branch, and gives the later kind-digest key a home: once the envelope carries the
digest, the same binding lookup works unchanged. The requirement stays scoped to
unbacked listings because backed listings can still be authored from local tables
when `use_site_projection_for_listings` is false; making "no local authoring source"
true of every listing is `pools-9-retire-local-physical-authority`'s origination
statement, which is why that change is this one's completion dependency.

`multi-domain-storefront-composition` marks its task 4.5 ("shared binding lookup
replaces domain mapping authority") complete. It receives a correction note recording
the remaining reads and writes and that this change removes them; the task is not
un-checked. This change's delta also restates the permanent "Commercial mapping
identity" requirement, which still names `derived_compute_listings` as the VM
mapping.

### A declaration with no enumeration quantity yields no listing, visibly

The live defect is silence rather than fabrication: a declaration without `gpu_count`
publishes nothing and says nothing. The `or 1` defaults are latent. Three cases are
distinguished, following the commitment rule and the projection rule that an unknown answer is not
an answer of zero:

| Declaration | Meaning | Behavior |
|---|---|---|
| `gpu_count` absent | Determinate: nothing the VM domain can enumerate | No listings from this member; existing ones close through source reconciliation; an operator notice names the member |
| `gpu_count: 0` | Declared zero, for example maintenance | No listings; existing ones close; no notice |
| `gpu_count` malformed | Unknown, indicating version skew or a producer defect | The member is unresolvable: no new candidates, existing listings held |

Every `or 1` and `or 0` on the derivation path becomes strict. On the candidate side —
the binding envelope, the skip keys, the slice-key builders — a missing or non-positive
count raises, because every derivation path produces a positive one and a raise is a
programming error surfacing. On the stored-listing side, a stored listing with no usable
count is excluded from keyed reconciliation with a notice rather than keyed as a 1-GPU
slice, which could collide with a real one. The `allocated_gpu_count or 1` in the admin
controller reads a site reservation response on the backed path and is out of scope.

Nothing here depends on backing, as a rule about derivation integrity should not.

### The binding discriminator is added in two migrations: expand, then contract

The design's principle is "explicit discriminator, never an absent value". SQLite
cannot change a column's nullability or default without rebuilding the table, and a
column added `NOT NULL` needs a default that would then silently classify any insert
that omits it. The column is therefore added in steps, with the final requirement
enforced by a trigger:

1. **Expand** (one migration): add `capacity_backing TEXT CHECK (capacity_backing IN
   ('backed', 'unbacked'))`, nullable with no default; backfill every existing row as
   `backed` (every existing row is backed by construction, since no earlier version
   could publish an unbacked listing); then drop and recreate
   `storefront_listing_binding_immutable` with `capacity_backing` in its `UPDATE OF`
   list and `WHEN` clause. The backfill must precede the trigger's recreation or the
   new trigger would refuse it. The binding-schema migration that created the trigger
   stays frozen.
2. **Contract** (a second migration): a `BEFORE INSERT` trigger refusing a row whose
   `capacity_backing` is `NULL`. With no column default, a writer that omits the column
   fails loudly instead of being classified; the extended immutability trigger already
   refuses any later update.

The effect equals `NOT NULL` with no default, without the full table rebuild (copy,
rename, and recreating the indexes plus the five triggers across two tables that
reference the table by name). `negotiation_threads` gains no column; negotiation reads
the binding variant from the immutable listing binding.

Application writers name the column: `StorefrontListingBinding` gains a required field
with no default; both inserts in `core_storefront.sqlite_client`, the legacy
migration tool's `INSERT OR IGNORE`, and the two bare-metal writers found in planning
write it explicitly (`RAISE(ABORT)` is not
suppressed by `OR IGNORE`); and the post-insert equality check includes it, so a second
bind of the same listing with the opposite backing is refused rather than absorbed by
`ON CONFLICT … DO UPDATE SET last_reconciled_at`.

**Rollback.** `docs/development/ARCHITECTURE.md` says non-additive schema changes use
expand/contract across releases; the contract step is non-additive for writers, since
pre-change code omits the column. Both migrations nonetheless ship in this change,
recorded here as a deliberate exception. There is no fleet-wide deployment signal to
gate a later contract release — the same reasoning that left the compatibility-rule
removal and `pools-9-retire-local-physical-authority` without a trigger — so a
deferred contract step would in practice never land. Once any unbacked listing exists,
rollback is already unsafe, because pre-change code ignores the column, treats the
listing as backed, and attempts reservations the site refuses. The only window the
contract step costs anything in is upgraded, no unbacked listing published, then rolled
back, and there the documented rollback is dropping the one required-insert trigger.
The separate migration IDs keep that step identifiable.

### Rates are a separate change, not a blocked one

Buyers need a rate or the catalogue supports discovery but not comparison. The rate
is nevertheless not in this change, because it is a distinct buyer-facing surface
with its own decisions about periods and assets.

An earlier version of this section said the rate was *blocked* behind
`capacity-shape-pricing` and transitively behind the unstarted
`structured-capacity-requirements`. That was corrected: those changes price a shape
a buyer proposes during negotiation, while a published asking price prices a
listing's fixed advertised shape, which is one number.
`publish-indicative-listing-rates` depends only on this change.

What is settled here, because it constrains that change: the rate is a **listing
attribute**, not a settlement option rate. The mechanism these deals settle through
declines scalar participation, and its design records the rejected alternative —
encoding exotic contracts as rates was considered and rejected, because the scalar
machinery exists for mechanisms that want it and this class of terms does not reduce
to one number. Un-declining it would put a number in a settlement option that the
runtime does arithmetic on and an obligation implies, with nothing behind it for a
deal agreed out of band.

That is a statement about what the system constructs from the number, not about how
much a buyer should believe it. Like every other published field, a rate is a seller
assertion; what distinguishes it is that no settlement option or obligation is
derived from it.

### An unbacked pool still names a provider, and that is accepted

`PoolCreate` requires a provider, so an execution-less seller's pool names a
fulfillment provider it must never dispatch to. This is an accepted decision rather
than an open question, because leaving it open would misrepresent something we are
knowingly shipping.

What made it a problem is gone. The blocking reason was that a pool could only
authorize a mode its provider *proved* it could deliver, so an execution-less seller
authorized nothing; `pool-declared-advertisement-and-backing` removes that. What
remains is a named provider that is never reached, and three things make that safe:
the pool declares no admission authority, so no capacity path is reachable;
`project-capacity-resources-without-hosts` makes admission and placement refuse a
capacity declaration that names no host when its pool's provider needs one, and makes
dispatch fail closed for a host with no registered record; and a configuration-free
provider already exists, so naming one requires no fabricated configuration.

The alternative — a publication-only provider kind — is rejected in that change for
putting a no-op executor in the fleet, where every dispatch path would depend on a
handler doing nothing rather than on a declaration saying nothing.

**Revisit trigger:** the first time a dispatch path is reached for an unbacked pool,
or the first operator confusion about which provider to name.

### Backing is immutable per durable listing

An earlier roadmap sentence said the same listing becomes capacity-backed later.
That cannot be true alongside a discriminator inside the immutability trigger, and
the trigger is the property worth keeping: moving from "no admission guarantee" to
"this exact authority stands behind this listing" is a material provenance change,
and a buyer holding a listing reference should not have it change meaning
underneath them.

So unbacked to backed is **close and republish**: the old listing closes, a new one
binds with capacity provenance. Because a pool's backing is itself fixed at
creation, this is not a listing-level mechanism the storefront invents — a supply
move is a move between pools, and the new listing derives from a different pool with
a different derivation identity. What the roadmap sentence was actually
arguing survives — no new domain, no new registry, no migration unwinding a
fabricated site — and it is reworded to say that instead.

If stable listing identity across the transition ever becomes a requirement, it
needs an explicit transactional rebinding protocol, not a relaxed trigger.

### Every published field is a seller assertion, including on backed listings

Two earlier drafts of this design tried to make an unbacked listing's published
capacity weaker than a backed one's — first as "declared rather than admitted",
then as "untested rather than falsifiable". Both were wrong, and the code says so
plainly. `compute_capacity_claim_from_order`'s docstring, describing the **backed**
path, calls the dimension map "the listing's fixed, seller-declared shape, so
admission checks that every requested dimension fits". Reservation checks that what
a buyer asked for fits inside what the seller declared and that the site has an
unreserved unit matching it. Nothing verifies that a host has the RAM. An Ansible
run can still hand over less than advertised.

So a published shape is a seller assertion on every listing, and the marketplace
has no mechanism that makes one assertion stronger than another. A buyer misled
about a backed listing's RAM and a buyer misled about an unbacked seller's
inventory discover it the same way — by inspecting what they got, cancelling, and
reporting the storefront to the registry. Registry curation is the control in both
cases, out of band, and this goal adds none.

"Admitted" was the specific error. It is capacity-reservation vocabulary — whether
a request to reserve is granted — and stretching it into a claim-strength property
imported a guarantee that does not exist. It should not appear in this campaign's
language.

**What actually differs** is narrower: a backed listing's published quantity is
additionally bounded by the availability its site projects, so it moves as capacity
is reserved and released. An unbacked listing's does not move, because reservations
are no-ops and any number of buyers can settle against it. That is exhaustibility,
and the published backing value already tells a buyer which kind of listing they
are looking at. Publishing a second field to restate it would be exactly the
redundant encoding this campaign has removed everywhere else, so no such field is
added.

**What survives, on independent grounds.** No derivation substitutes a quantity a
declaration does not carry. That is derivation integrity — a fabricated value entering
the durable and published record — and it has nothing to do with claim strength; the
enumeration-quantity decision below records what happens instead.

**The refusals in this change are guards, not controls.** Capacity operations
rejecting an unbacked listing at the type boundary, and claim construction refusing
one, exist so a no-op cannot silently succeed and leave a reservation record with
no authority behind it. They protect the system from a bug in itself. They are not
controls on what a seller may publish and do not imply the marketplace verifies
anything.

### Backing is filtered exactly, and existing listings are republished

A first draft specified the registry's underreport-friendly convention for the
backing filter. That was a generalization from the wrong part of the profile:
every `listing_resource` filter in `filter-spec.yaml` is `on_missing: fail`, and the
file states that an unknown spec cannot be assumed to satisfy a stated
requirement. `on_missing: pass` appears only on `accepted_escrows` and
`settlement_options` paths, where a seller underreporting what they accept is the
concern being tolerated.

For a discriminator, permissive matching is actively wrong. A buyer asking for
unbacked listings would receive every legacy backed listing that simply predates
the field — precisely the category they excluded. So the filter is exact and
fails on missing, and existing listings are republished carrying explicit
`capacity_backing: backed`, since they are semantically known to be backed and should not
depend on an absent field to be classified.

**Republication is the refresh pass.** Open listings gain the explicit value when the
publication cycle's terms refresh reaches them, and closed ones when they reopen. The
identity rule forbids adding a new commitment to an existing listing, and this is not
one: backing is not a property of the physical resource but of whether an admission
authority stands behind the listing, it is fixed on the binding rather than derived
per read, and every listing published before the field existed was admissible.
Publishing `backed` discloses what the binding already records and changes nothing a
buyer relied on.

### One registry, not a second profile

Listing shape is a registry-deployment property: one deployment serves one filter
spec, and `schema.id` is what buyer commands match on. That makes "which
registry" look like a schema question, and it produced a wrong inference during
design — that different compute form factors might need different registries.
They do not: `compute.market` already carries `bare_metal`, `vm`, and `container` in
one enum.

The loose-listing introductions profile is separate for two specific reasons,
neither of which is form factor: it requires option-only listings, and it leaves
`listing_resource` open with no required `gpu_model` or `region` and no vetted
enum, because sellers there describe what they broker in whatever vocabulary
fits. An unbacked compute listing carrying `gpu_model`, `region`,
`offering_mode`, and a rate fits the compute shape. The compute spec's
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

## Decisions added in the planning review

The planning review of 2026-09-23 re-read this design against the code (see "Findings
verified during planning") and settled the following with the user, one at a time.
They are accepted decisions, not open questions. Where one supersedes text earlier in
this document, that text has been amended to point here.

### An unbacked listing publishes only settlement options its domain does not fulfil through capacity

**Finding answered:** a paid deal on an unbacked VM listing would reach fulfillment
after funding.

A domain that can publish unbacked listings declares in its settlement composition,
for every mechanism it composes, whether settling through that mechanism delivers
through the domain's capacity-backed fulfillment. Bare metal and API credits publish
only backed listings and owe no declaration. Each is set explicitly when the mechanism is composed; nothing defaults.
In the VM storefront, `alkahest.v1` and `fiat.stripe.v1` both deliver through
`fulfill_vm_settlement`. `contact-exchange.v1`, once
`compose-contact-exchange-across-compute` composes it for VM, does not.

For an unbacked candidate, publication drops every option whose mechanism the domain
fulfils through capacity and reports an operator notice naming the pool and the dropped
mechanisms. If no option remains, the candidate yields no listing, with the same notice.
Backed candidates are unaffected. The rule is re-evaluated on every publication cycle,
so a change in composition reaches open listings as an ordinary change to a term of
sale. The capacity type boundary stays behind it as the backstop.

**Why the domain rather than the mechanism.** Whether settling an option reaches
capacity-backed fulfillment is a fact about how a domain composes a mechanism, not about
the mechanism. The same mechanism can be composed differently in different domains, and
the anticipated hosted-settled unbacked listing composes Stripe without VM provisioning.
A declaration on `MechanismRegistration` would have meant changing `kit/alkahest` and
`kit/hosted-settlement` to carry a domain fact. Neither those packages, the Alkahest
contracts, nor the hosted settlement service change.

**Consequences.** Until the VM storefront composes contact exchange, every unbacked VM
candidate yields no listing and a notice: the feature is present but inert for VM. This
change's system evidence (tasks 6.7 and 6.8) therefore waits on
`compose-contact-exchange-across-compute` Sections 1–3 and 3b, which in turn wait on
`contact-payload-retention`. That change's "composition is independent of backing"
still holds: a backed listing may settle by introduction, and no pool-level or
listing-level field names a mechanism.

### Publication runs as a storefront lifecycle loop

**Finding answered:** nothing in a deployed stack runs the publication cycle.

The storefront process runs publication as a timer-driven loop. Each cycle derives
candidates from the configured sites, publishes new ones, refreshes terms on open ones,
closes stale ones, holds unresolvable ones, and reopens reconciliation-closed ones behind
the identity comparison below. It calls the storefront's publication services in-process:
no HTTP to itself, and no database access outside the storefront's repository.

**Why autonomous.** Operator-invoked publication was the status quo, not a recorded
decision, and this design depends on the opposite. "Unbacked listings are projected; the
site is the control plane" has a seller declare supply at their own site and the
projection carry it to the storefront. One storefront publishing for several seller
sites, whose sellers hold no storefront credential, is what task 6.8 proves. Without an
autonomous loop, a site's declaration never becomes a listing unless the storefront
operator runs a command.

**Controls,** following the storefront's existing lifecycle conventions:

- The loop is registered and gated like the other storefront loops, under the route
  name `publication` in `ADVANCE_LOOP_NAMES`. `POST /api/v1/admin/lifecycle/pause` and
  `.../resume` hold and release it with every other loop, without affecting trading.
- `POST /api/v1/admin/lifecycle/publication/run-cycle` runs exactly the cycle the timer
  runs, and works while paused.
- `POST /api/v1/admin/lifecycle/publication/dry-run` reports the planned publish,
  refresh, close, reopen, and hold decisions with their reasons and applies none; two
  consecutive dry runs report the same thing, as the capacity-event dry run does.
- The typed storefront client already addresses both routes by loop name in its sync
  and async variants; e2e scenarios hold the loops with `pause_storefront` and advance
  explicitly.

A change in a site's resource-pool projection generation wakes the loop; a held loop
stays held.

**The command becomes a client.** `market-storefront publish` calls the loop's controls
through the typed client: a one-shot run is `run-cycle`, `--dry-run` is `dry-run`, and
`--abort-all` is a seller close of every open listing through the API. `--watch`,
`--poll-interval`, `--db`, `--settlement`, `--max-duration-seconds`, and `--inventory`
are retired, and `run_watch_loop` with them. CSV import remains available through
`POST /api/v1/admin/portfolio/resources/import` until
`pools-9-retire-local-physical-authority` retires it.

**Accepted consequences.** Every derivable slice of every advertisable pool publishes at
the storefront's resolved terms. A hand-authored listing on a derivable slice is managed
by the loop, which was already true on reopen, since reopening writes the freshly
derived payload; an admin create for a slice the loop has published is refused with
`ListingSourceAlreadyBound`. E2e scenarios that create listings through the admin API
either hold the loop first or advance it and assert on what it derives, as
`docs/development/TESTING.md` requires.

**Bare metal stays operator-invoked.** Its image does not publish autonomously today and
`docs/development/DEPLOYMENT_AND_CONFIG.md` records it as not release-qualified. That is
recorded rather than extended here.

**Alternatives rejected.** Starting `run_watch_loop` from `serve`: it has no pause gate,
publishes by HTTP to its own storefront, reads the database directly, and carries the
non-durable command tier below. A narrower `serve`-side reconciliation of existing
listings only: it is a strict subset of this loop and would be rewritten when the loop
landed.

### Terms come only from durable sources

**Finding answered:** the command-level term inputs cannot be reproduced by
reconciliation.

Settlement clauses resolve field by field through the pricing hint chain
(`resolve_gpu_pricing`). `--settlement` was not a tier of its own; it replaced the bottom
two tiers for the life of one process:

| Precedence | Source | Durable |
|---|---|---|
| 1. Storefront per-pool override | `compute_capacity_pools.settlements`, home site only | Yes |
| 2. Pool-declared hint | the pool's `pricing` policy tag at the site | Yes |
| 3. Per-model default | `[pricing.defaults.gpu.<model>].settlements`, replaced by `--settlement` | Configuration |
| 4. Flat default | `[pricing].settlements`, replaced by `--settlement` | Configuration |

`--max-duration-seconds` sat the same way below `default_max_duration_seconds`.
Reconciliation re-derives a listing from its sources, and an argument that lived only in
one invocation cannot be re-derived, so the loop would have reverted command-sourced
terms on its next pass.

**Decision.** Both arguments are retired. The configuration keys stay: they are durable,
survive restart, and are the default tier of the hints pattern. Per-pool clauses have
two durable homes — the site's pool `pricing` tag, and the storefront per-pool override
row whose write path `pools-9-retire-local-physical-authority` owns.

**Why not a durable replacement.** The storefront has no settings API to attach one to:
storefront-wide settings come from configuration files, and the only API-mutable runtime
state is the in-memory negotiation and loop pause flags. A settings API built for this
one value was rejected. What sellers lose is changing storefront-wide clauses without a
configuration edit and restart.

### A seller's close is durable

**Finding answered:** a seller's close and a reconciliation close are indistinguishable.

Every close records who closed the listing, `seller` or `reconciliation`, on the common
`listings` row; reopening clears it. No reopen path — the capacity-event reconciler,
the publication loop, and the identity-gated reopen — reopens a listing its seller
closed. Listings in the other non-open states the storefront already uses after a deal
(`refunded`, `reclaimed`) record no closure reason and keep their existing handling. Because the derivation key stays bound to a seller-closed
listing, the loop finds that binding and publishes no replacement for the slice.

A seller re-lists with `resume`: on a seller-closed listing it reopens the listing,
clears the reason, and publishes; the loop then reconciles it like any open listing.
`resume` on a reconciliation-closed listing returns a conflict naming the reason, since
its source does not currently support it and reconciliation owns it. `--abort-all`
becomes a seller close of every open listing.

**Enforcement.** A nullable `closed_by` column with a `CHECK` over the two values, and a
trigger requiring it to be present exactly when the listing is closed, so no close path
can omit it. The migration backfills existing closed rows as `reconciliation`. Under the
previous code every closed listing was reopenable by the capacity-event path, so this
reproduces existing behaviour for rows whose closer was never recorded; it is not an
inference about any new row. `PublicationRuntime.close` takes the reason as a required
argument, and a reconciliation plan's closes are reconciliation closes. The column is in
the common table, so API-credit and bare-metal close paths name it too.

**Alternative rejected.** Reusing the durable `paused` column, which would conflate a
listing the seller withdrew with one held but still bound.

### One comparison gates refresh and every reopen path

**Findings answered:** the capacity-event reopen path bypasses the identity rule; open
listings never refresh.

The VM domain owns one comparison of a stored listing against a fresh derivation of its
own source and against its binding. Its outcomes are: unchanged; a term of sale differs;
a published identity field the key does not capture differs; the published backing is
missing; the live pool's backing disagrees with the binding; the source is unresolvable;
the source is absent. Each reconciliation path acts on it:

| Stored listing | Outcome | Action |
|---|---|---|
| Open | Unchanged | Nothing |
| Open | Term differs, or published backing missing | Update in place, locally and at every registry |
| Open | Identity field differs, or live backing disagrees | Reconciliation close; reopen refused and logged while the difference persists |
| Open or closed | Source unresolvable | Held: neither closed, refreshed, nor reopened |
| Open | Source absent | Reconciliation close |
| Closed by reconciliation | Unchanged or term differs | Reopen with the freshly derived payload (loop) |
| Closed by reconciliation | Identity field differs, or live backing disagrees | Stays closed; refusal logged |
| Closed by the seller | Any | Nothing |

The capacity-event reconciler applies the same gate before it reopens. It republishes
the stored terms rather than re-deriving them, because terms refresh is the loop's job,
and the published `capacity_backing` is always stamped from the binding on every publish
of a VM listing, on every path.

### Refresh and reopen flow through the existing publication-source seams

`publish_round` in `core_storefront.publication_runner` already hands a source's
`reopen_existing` the fully re-derived candidate, including its settlement terms, before
creating anything. The refresh is realized there, domain-side: a source stops treating an
open listing as covering its slice, so the candidate reaches `reopen_existing`, which
reconciles the existing listing under the candidate's derivation key according to the
comparison above. Core never compares payloads and stays schema-opaque.

Core gains one outcome: `reopen_existing` may report that the existing listing is
unchanged, which the runner counts as skipped rather than failed.

The additional reconciliation-plan lane in `kit/capacity-publication` considered earlier
in the review is not needed, because the loop runs in-process through the same runner.

### Bare metal publishes backing and applies the identity rule

`BareMetalListing` gains a required `capacity_backing: Literal["backed"]`, set explicitly
by the deriver. Bare metal reads no pool tags, and every listing it derives is backed by a
selected-site Physical Resource. The bare-metal domain has never been public, so the
field is required on read with no compatibility reading, and existing development
listings are refreshed on the next operator-invoked publication cycle. Both of its
binding writers name `capacity_backing = 'backed'`.

The listing-identity and source-publication requirements are not scoped to VM, so bare
metal applies them through its own `PublicationSource`. Its key is (site,
`physical_resource_id`); `host_id`, `physical_host_id`, `capabilities`, and site labels
are identity; durations, access methods, and settlement options are terms of sale.

API-credit listings do not publish `capacity_backing`. Their registry schema would accept
the field, but API credits have a separate schema identity, no backing filter is added
there, and every API-credit listing is quota-backed. Only their types move.

### The inventory guard compares against a fresh derivation

**Findings answered:** provenance is per listing; round zero runs the guard.

- **Declared match.** The guard derives the listing's own source now, through the same
  derivation publication uses, ranged over declared quantity. Published categorical
  identity fields must equal the derivation's and the published quantity must lie in its
  range. Whether a field came from site data or a local fallback falls out per listing.
  A failure reports `no_matching_declaration`, distinct from `no_matching_inventory`.
- **Fungible pools.** A fungible listing matches if some enabled member has equal
  categorical attributes and a declared count of at least the published `gpu_count`. An
  unbacked fungible pool's slices run to the largest single member's declared count, not
  the sum, because a reservation lands on one member.
- **Malformed members.** One malformed member holds a whole fungible pool, because the
  pool's range cannot be computed; in a specific-resource pool it holds only its own
  listings.
- **Availability,** for backed listings only, is the same derivation ranged over the
  pinned site's availability. Only the pinned site's snapshot is fetched.
- **Source selection** is the one publication uses, projection or local tables. Unbacked
  listings exist only on the projection path, so this matters only for backed listings.
- **How the binding reaches the policy.** The VM default-hook factory gains a binding
  parameter and is built per round: in `evaluate` from `RoundRequest.binding`, and in
  round-zero evaluation from the binding it already resolved. Custom hooks are unchanged.

## Findings during implementation

Recorded as implementation found them. Each is either fixed here, because this change
rewrites the code it sits in, or corrects a statement earlier in this document.

- **Reopen did not reopen at the registries.** `PublicationRuntime.reopen` reopened a
  listing locally and republished it, but a registry's publish updates a listing's
  payload and leaves its status alone, so a listing a registry recorded as closed stayed
  closed there. The retired CLI path had sent an explicit status update; the kit path
  never did, and the e2e scenarios check only storefront-local status. Fixed:
  `core_storefront.registry_publication` gains `reopen_listing_in_registries`, and the
  kit's `reopen` sends it after a successful publish.
- **Bare metal's reconciliation close named no reason.** `mark_derived_bare_metal_listings_closed`
  set `listings.status = 'closed'` directly. The closure-reason trigger refused it the
  first time a test exercised the path; it now records `reconciliation`, which is what
  both of its callers are.
- **The loop compared against unparsed JSON, and its failures were invisible.**
  `load_listing` returns `listing_resource` as stored text for the domain model to
  parse, so the loop's first comparison raised; the shared runner recorded that as a
  failed candidate and nothing reached the cycle report. Both are fixed: the loop decodes
  the stored shape, and a failure is reported as a `fail` action with its reason.
- **The reopen gate lives in the shared predicate.** `closed_available_listing_ids` is
  used by the capacity-event reconciler, the admin release handler, and failure
  handling, so the identity and backing comparison sits there rather than in each
  caller.
- **The guard's inputs are computed by the storefront.** The policy-layer guard in
  `domains/vms/negotiation` interprets a source check the storefront computes from the
  round's durable binding (`services/listing_source_check.py`). The default hook takes
  that check instead of a capacity client, so the policy module imports no storefront
  code and no any-site snapshot path remains.
- **One gated projection accessor.** Publication, capacity reconciliation, and the
  guard read the projection through `listing_source_projection()`, which honours
  `use_site_projection_for_listings`, so they never disagree about which source applies.
- **The legacy migration tool writes backing.** `migrate-storefront-domains` creates
  the binding table through the frozen schema function, so it now applies the two
  backing migrations first and writes `backed` explicitly.
- **An unloaded site projection is unknown, not empty.** The guard's first source
  check read a site whose bucket projection had not loaded as a site with no
  buckets, which made a fungible pool look fully taken. A site missing from a
  projection is now unknown: its buckets fall back to member availability, and a
  site whose pool projection has not loaded confirms no declaration rather than
  falling back to the local tables, which are not that listing's source.
- **The binding trigger's name** is `storefront_listing_binding_immutable`; the text
  above is corrected.

## Findings recorded, not fixed here

- **Region at admission.** Confirmed by reading during planning: the capacity claim
  carries the listing's `region`, which may come from the pool's `region` tag, while the
  site's feasibility view matches claim attributes against declaration attributes and
  the resource's own facts only. A backed pool that declares region only as a tag cannot
  admit. Pre-existing; recorded in `pools-8-capacity-projection-and-listing-hints`, which
  owns the region hint, and not fixed here.
- **Mixed-kind fungible pools** publish the first model encountered and sum availability
  across members. Owned by the listing-identity open question in
  `publish-multidimensional-listing-shape`; this change only logs a warning.
- **`registry-discovery/spec.md` is structurally invalid.** Two requirements sit outside
  its `## Requirements` section, so OpenSpec reports that archiving this change's
  `registry-discovery` delta would be refused until they are moved. This is a closeout
  prerequisite for this change.
- **`market-storefront logs` reads the storefront database directly.** `cli_logs.py`
  opens the SQLite file rather than going through the storefront API, the same pattern
  this change removes from `publish`. Out of scope here; no change owns it yet.

## Risks / Trade-offs

- **[An unbacked listing reaches a capacity path]** → Mitigated first by
  publication: an unbacked listing carries no settlement option its domain fulfils
  through capacity, so no ordinary deal on it reaches fulfillment. Behind that, the
  binding types: a capacity path receiving an `UnbackedBinding` refuses at the
  `CapacityBinding` boundary before any effect. Cover the refusal at reservation
  directly rather than relying on it never being called.
- **[Autonomous publication surprises a seller]** → Accepted. Every derivable slice of
  every advertisable pool publishes without a command. The site's `advertisable_modes`
  declaration is the seller's authorization to advertise, a seller's close is durable,
  and the loop can be held and previewed. **Revisit trigger:** the first operator request
  to curate which derivable slices publish.
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
- **[Discovery lands before comparison]** → Splitting rates out means a window in
  which buyers can find unbacked supply but not compare it on price.
  `publish-indicative-listing-rates` depends only on this change, so the window is
  a sequencing gap rather than an open-ended one.
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
- **[The refresh pass changes backed listings' behavior]** → Accepted. Open backed
  listings begin reflecting term changes, and a published identity field that
  diverges from its source now closes a listing that previously stayed open and
  stale. Both are corrections; the integration coverage asserts each.
- **[Held pools hide a real withdrawal]** → A pool that becomes unresolvable at the
  same time its supply is withdrawn keeps its listings open until it resolves. The
  guard's declared match still rejects negotiation against a withdrawn declaration,
  and admission still refuses, so the exposure is discovery-only. **Revisit
  trigger:** a pool observed unresolvable for longer than a projection poll cycle in
  normal operation.
- **[The contract migration blocks a pre-change writer]** → Accepted and bounded;
  see the binding-schema decision.

## Open questions

- **Does `kit/capacity-publication` keep its name?** The principal type is settled by
  the planning review: `PublicationBinding` is the union of `CapacityBinding` and
  `UnbackedBinding`, so the module's central name is no longer a variant. The package
  name still names one variant. Deferred; no task renames it.
- **Does a rate arbitrageur with no hardware run a site service?** The model
  assumes site-shaped sellers deploy one, which is materially lighter with no
  hosts — no executor connections, no playbooks, no watchdog — but is still a
  service. If that proves too heavy, a storefront-hosted path returns as a
  separate question, and with it the broker-identity problem this design avoided.

**Resolved during the design phase.** When the absent-tag compatibility rules are
removed, and whether together: they are one joint rule, retained until a future change
acquires a reliable signal that no producer relies on it.

**Resolved since drafting.** Where the seller's contact payload lives under one
storefront serving several sellers is no longer open:
`compose-contact-exchange-across-compute` owns resolving it per listing origin, and
Goal 7 is complete for discovery but not for introductions across sellers until that
lands. Recorded here rather than deleted because this change's system coverage
publishes from two seller sites, which is what made the constraint visible.

## Verified during planning

The pre-planning "to verify" list is settled; each result is in "Findings verified
during planning" and, where it changed the design, in "Decisions added in the planning
review".

- Bare metal did not publish `capacity_backing`; it now does.
- `serve` never ran the publication cycle; publication now runs as a storefront loop.
  The site projects a disabled pool with `enabled: false`, which derivation now reads.
- The migrated-database abort is confirmed by test and fixed by the retirement.
- Region at admission is confirmed and recorded against `pools-8`.
- API credits need type changes only, and their registry schema is not touched.
- Mixed versions are supported; system-level coverage of the compatibility rule is not
  reproducible with current images, so it is covered at integration level through the
  canonical site client against a recorded older-producer projection, and that decision
  is recorded in the tasks rather than omitted.

## Migration Plan

1. **Expand the binding schema** (first migration): add the nullable
   `capacity_backing` column with its `CHECK`, backfill every existing row as
   `backed`, then recreate the immutability trigger to cover it. `site_id` is
   untouched and stays `NOT NULL`.
2. **Contract the binding schema** (second migration): install the trigger refusing
   an insert whose `capacity_backing` is `NULL`. Every writer names the column,
   including both bare-metal writers.
3. **Record who closed a listing** (third migration): add `closed_by` to `listings`,
   backfill existing closed rows as `reconciliation`, and install the trigger requiring
   it exactly when a listing is closed. Every close path names it.
4. Introduce `CapacityBinding | UnbackedBinding` as `PublicationBinding` and widen
   `PublicationCandidate.binding` to it; forward the binding on `RoundRequest`.
5. Resolve projected pool declarations jointly per site generation and read pool
   enablement; gate publication on advertisement; range unbacked slices over declared
   quantity; drop settlement options the domain fulfils through capacity from unbacked
   candidates; find closed listings by derivation key; stop reading and writing
   `derived_compute_listings`.
6. Start the publication loop in the storefront process with its controls, and reduce
   `market-storefront publish` to a client of them.
7. Publish backing. Open listings gain explicit `capacity_backing: backed` through the
   loop's refresh, and closed ones when they reopen. This is a disclosure of the value
   their binding already records, not a new commitment: every listing was admissible
   under the old contract, so publishing `backed` changes nothing any buyer relied on.
8. Add the exact registry filter, after republication. A filter added first would
   exclude every legacy listing from backed queries in the window before
   republication completes.

Existing listings bind, negotiate, reconcile, and route as before, except where the
refresh and the identity rule correct stale payloads and where autonomous publication
fills derivable slices. Rollback before step 2 is a code rollback; the discriminator
column remains and is ignored by the restored reader. Rollback after step 2
additionally drops the required-insert trigger, and is safe only while no unbacked
listing has been published. Rollback after step 3 additionally drops the closure-reason
trigger; the column remains and is ignored. Rollback after step 8 leaves the published
backing field in place, which a restored reader ignores.
