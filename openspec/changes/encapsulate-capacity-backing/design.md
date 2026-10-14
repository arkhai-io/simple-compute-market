# Design — encapsulate capacity backing

## Context

Opened 2026-10-14 from the design review of `unbacked-bare-metal-listings`. That
change needs bare metal to publish unbacked supply, and the review found that every
consumer of backing decides its meaning for itself by comparing the
`capacity_backing` label or testing the binding class. Adding bare metal's unbacked
path the same way would duplicate each decision and keep the places where VM and
bare metal already disagree. The maintainer chose to gather backing's meaning into
one delegate first, as a prerequisite change.

## Decisions

### Encapsulate backing; do not abstract it yet

Two approaches were weighed:

- **Abstract.** Define a backing interface, find every switch on backing, and place
  each branch's logic in an implementing class per category. The label is replaced by
  a delegate in service code and recovered as a string only when projected. This is
  built for a third category.
- **Encapsulate.** Keep the label as the durable and published value, find the same
  switches, and move their logic as it stands into one delegate class that holds all
  knowledge of backing. Divergences between domains are unified as they move.

Chosen: encapsulate. No third category is defined — the only one anticipated, finite
unbacked listings, has no decided source of availability or admission — so an
interface written now would encode guesses. Encapsulation keeps the later extraction
local: once every decision lives in the delegate, splitting it into implementations
changes no caller.

Callers ask the delegate to act and never see what it decided. A delegate exposing
flags (`admits`, `bounded_by_availability`, and the like) for callers to branch on
was considered and rejected: it moves the switches rather than encapsulating them.

### The delegate is a kit, scoped to admitted capacity

Backing is not compute-specific and not universal. It applies to every market whose
listings are admitted against capacity an authority holds — physical capacity for VM
and bare metal, quota for API credits, which already binds every listing as
capacity-backed through `kit/capacity-publication` — and to no market without such
an authority, such as an NFT swap or a software licence market. So it is not core,
which holds only what is universal to every market, and it is not the compute family,
which is narrower than its users. It is a repository-wide kit.

It lives beside the label it interprets, in `kit/resource-pools-contracts`, because
both sides of the provisioning boundary need it: the site's pool declaration rules
and publication views, and the storefronts' bindings, reconciliation, negotiation,
and settlement. `kit/capacity-publication` is storefront-side and the site does not
depend on it. `kit/capacity-publication` consumes the delegate for bindings and
reconciliation scope. It is a contracts package with a package allowlist of
`arkhai-kit-capability-shape` and `pydantic`, which `make check-architecture` holds,
so the delegate may add no dependency.

Compute-family code that touches backing — building a resource's publication view on
the site, and both compute storefronts' candidate derivation — consumes the delegate
and owns none of its logic.

### The label stays; it selects the delegate

The pool's declared `capacity_backing` value selects the delegate. The label remains
what pool declarations, listing bindings, the resource-pool projection, the registry
schema, and the published listing carry, with no wire or persistence change. A value
with no delegate is unresolvable, exactly as an unknown value is today.

### Divergences are unified, not preserved

Backing is not a domain concern, so where VM and bare metal handle a backing concern
differently, the behaviour is unified as it moves into the delegate. Each unification
is recorded below as its own decision when it is made, because it is a behaviour
change in a change that otherwise preserves behaviour.

### Bare metal still publishes no unbacked listing

This change moves logic and unifies divergences; it adds no unbacked bare-metal
supply. `unbacked-bare-metal-listings` lifts bare metal's refusal on top of it.

### What the delegate decides (task 1.1)

An inventory of production code on 2026-10-14 found every place backing is switched on
across core, kit, provisioning, and the VM, bare-metal, and API-credit domains. Sites
that only store, copy, or validate the label without deciding anything stay as they
are. The rest reduce to nine behaviours, each of which becomes one delegate operation:

| # | Behaviour | Where it is decided today |
|---|---|---|
| 1 | Pool declaration rules: a backed pool advertises only what it delivers; an unbacked pool delivers nothing | `pool_declaration_problems` in `kit/resource-pools-contracts`, used by the pool wire models, the pool service, document import, and the startup check |
| 2 | Binding construction from the label | `publication_binding()` in `kit/capacity-publication`, used by VM; bare metal builds `CapacityBinding` directly and refuses anything else; API credits builds `CapacityBinding` from the listing payload |
| 3 | Capacity-effect guard: reserve, commit, release, lease truncation, and fulfilment only where an admission authority stands behind the listing | `CapacityRuntime.require_binding`; VM fulfillment and administrator `isinstance` checks |
| 4 | Hold placement at acceptance | VM skips an unbacked listing with a stage event; API credits always reserves; bare metal holds nothing at acceptance |
| 5 | Feasibility: declared capacity only, or declared and current availability | VM `_judge_members`; bare metal's candidate/unavailable split on the view's `available` |
| 6 | Reconciliation scope: which listings capacity-availability reconciliation may close or reopen | VM's `backed_only` in five places; bare metal and API credits have no split |
| 7 | Source-check availability | VM checks availability only for a `CapacityBinding`; bare metal always checks it |
| 8 | Settlement admissibility: drop mechanisms fulfilled through capacity from an unbacked listing | VM `admissible_settlement_clauses` over a separate declaration map; bare metal holds the same fact as `SellerStage.physical` and applies no filter |
| 9 | Reading a legacy producer: every pool resolves as backed when a site emits no declarations | `read_site_declarations` in `kit/resource-pools` |

Comparing a listing's bound backing with its source's on refresh and reopen is not an
operation: it is label equality, the same for any pair of categories, so it holds no
category knowledge to encapsulate. It is a divergence instead — VM refuses refresh and
reopen on a mismatch; bare metal treats backing as a term field and refreshes in place
— unified under task 1.3 as one shared rule beside the delegate.

The inventory also found, each to be closed in this change:

- capacity effects that bypass the backed-only guard: VM's fulfillment-resume recovery
  reserves and commits through the aggregate client, as do bare-metal fulfillment and
  its administrator reserve;
- VM's administrator reserve reports `require_binding`'s refusal of an unbacked listing
  as an unconfigured site;
- VM's mechanism declaration is checked only when an unbacked listing is derived, never
  against the composed mechanisms at startup; bare metal's `physical` is required on
  every stage.

### API credits moves onto the delegate in this change

Decided with the maintainer: the change exists to finish the encapsulation, so API
credits is not left behind. It diverges furthest today: it builds `CapacityBinding`
from the listing payload rather than the durable storefront binding, reads no pool
declarations, reconciles every listing, and always places a hold. Each is unified under task 1.3.

### The storefront's copy of the vocabulary goes; its database check stays

`core_storefront.domain_registry` carries its own `CAPACITY_BACKING_VALUES`, and its
migrations add a `CHECK (capacity_backing IN ('backed', 'unbacked'))`. The `core`
layer itself knows nothing of backing: `core/storefront` is the storefront role's
composition under the carrier directory, recorded as an override in
`docs/development/ARCHITECTURE.toml`, and moving its listing binding and persistence
into kits belongs to `kit-owned-storefront-auth-and-persistence` and
`align-package-paths-with-layers`.

What this change owns is the duplication. Decided with the maintainer:

- `StorefrontListingBinding` validates its label through the backing delegate's
  registry, a composition depending on a kit. The site-client fixture's copy goes the
  same way. When the listing binding moves into the storefront contracts kit
  `kit-owned-storefront-auth-and-persistence` proposes, that kit inherits the edge to
  `kit/resource-pools-contracts`.
- The SQL `CHECK` stays as a database backstop, and a test holds its value set equal to
  the delegate registry's labels so the two cannot drift. SQLite cannot drop a column
  check without rebuilding the table, and a new category needs a migration of that
  table whichever form its validation takes.
- The applied migration that backfilled `'backed'` stays: migration IDs are recorded
  and never reused, and on a fresh database it updates nothing.
- The insert and update triggers know only that the column exists, and need nothing.

### The delegate's operations (task 1.2)

The delegate lives in `kit/resource-pools-contracts`, whose allowlist admits only
`arkhai-kit-capability-shape` and `pydantic`, so it can import no binding type, client,
or effect. Each operation therefore takes the caller's work as an argument and decides
whether and how it runs; the caller never learns the category. Feasibility and the
source check's availability are one decision — judge against the declaration, then
against availability only where availability bounds the supply — so they are one
operation.

| Operation | Shape | Backed | Unbacked | Callers |
|---|---|---|---|---|
| Declaration rules | `declaration_problems(advertisable, deliverable)` returning `PoolDeclarationProblem`s | advertisable within deliverable | deliverable empty | `pool_declaration_problems` |
| Capacity guard | `require_admission(effect)`, raising `CapacityNotAdmittedError` (defined beside the delegate) | passes | refuses | `require_binding`, VM fulfilment, every path that reserves or commits outside it |
| Hold | `place_hold(place)` returning `place()`'s result or `None` | runs `place` | returns `None` | VM and API-credit acceptance; the caller reports a hold not placed |
| Supply judgement | `judge(declared, available)`, both callables returning the caller's verdict | the declared verdict, then the availability verdict when the declaration fits | the declared verdict | VM member feasibility, bare-metal classification, both source checks |
| Reconciliation scope | registry-level `labels_reconciled_by_availability()` | included | excluded | VM's binding query, bare-metal and API-credit reconciliation |
| Settlement admissibility | `admissible_settlement(clauses, fulfils_through_capacity)` returning kept clauses and dropped mechanisms | keeps all | drops clauses whose mechanism delivers through capacity | VM and bare-metal publication |
| Legacy producer | registry-level `legacy_producer_backing()` | is it | | `read_site_declarations` |
| Admitted reservation | registry-level `admitted_backing()` | is it | | a binding synthesized for a reservation with no listing |
| Binding construction | decided by task 1.4 | | | `kit/capacity-publication` |

A caller that judges declared capacity alone for every backing — VM's override
feasibility and the declared half of its source check — keeps doing so by calling only
the declared judgement; that is a caller's choice, not a backing decision. The
per-mechanism fact settlement admissibility takes stays the domain's.

The delegate is `CapacityBacking`, one class with private configuration and two
module-level instances, `BACKED` and `UNBACKED`, each carrying its `label`. The current
`CapacityBacking` literal alias is renamed `CapacityBackingLabel`. A registry function,
`capacity_backing(label)`, returns the delegate for a label and refuses an unknown one,
as the resolver does today. `PoolDeclarations` and `ResolvedPool` carry the delegate.
Any branching stays inside the one class, so a later interface is a subclassing of it
with no caller change.

Rejected: flags on the delegate for callers to branch on, which moves the switches
rather than encapsulating them; and effects performed by the delegate, which the
contracts allowlist forbids and which belong to the storefront and site layers.

### One binding class carries the delegate (task 1.4)

`kit/capacity-publication`'s sibling `CapacityBinding` and `UnbackedBinding` classes,
which encode backing as a type, are replaced by one class,
`PublicationBinding(site_id, offering_mode, source_id, backing)`, whose `backing` is the
`CapacityBacking` delegate. The name is the union alias the kit already exports, so
annotations written against it stand.

- `publication_binding(capacity_backing=label, ...)` resolves the delegate from the
  label; no label-to-type table remains.
- `require_binding` asks `binding.backing.require_admission(effect)`, and every
  capacity effect accepts `PublicationBinding`. Every other test of the binding class
  becomes the delegate operation the inventory assigned it.
- `backing` is a field, so two bindings differing only in backing are unequal, and the
  publication runtime's persisted-binding comparison still catches a backing change.
- A refused admission raises the delegate's `CapacityNotAdmittedError`, which the
  kit's administrator route service answers with 409. `CapacityBindingError` stays for
  identity faults — an unknown site or a changed binding. VM's administrator reserve
  no longer reports a refused admission as an unconfigured site.
- A further category needs no further binding class.

The type checker no longer proves that a capacity effect receives a backed binding;
the runtime guard did that already and remains, now as the delegate's. Rejected:
keeping the sibling classes with the delegate as a class attribute, which still needs
a category-to-class table beside the delegate's own registry and a new class per
category; and keeping the class test as the guard, which is the switch this change
removes.

`kit/capacity-publication` therefore depends on `kit/resource-pools-contracts`, a
downward edge between kits that `make check-architecture` permits. Capacity
publication and resource pools belong together: every market that publishes capacity
does so from capacity declared in pools, as API credits does with its system pool.

### Divergence: admitting unbacked supply (task 1.3)

Today VM derives a listing from every enabled pool advertising its mode, whatever its
backing; bare metal refuses an unbacked pool by name; API credits reads no pool
declaration at all — its service projects none, and its storefront locates a listing's
quota resource through the capacity snapshot and assumes backed.

Unified rule: a domain derives listings from every enabled pool that advertises its
offering mode, whatever its backing, and binds each with the delegate its pool
declares. Everything that differs between backed and unbacked supply follows from the
delegate, including that an unbacked candidate left with no admissible settlement
option yields no listing.

- VM already follows it.
- API credits: the credits service passes its pool directory to the site's capacity
  router, as the compute provisioning service does, so its resource-pool projection
  carries the declarations of the system pool it already seeds and migrates. At
  listing creation the storefront resolves the quota resource's pool through
  `read_site_declarations` and binds with that pool's delegate. An unbacked credits
  pool would yield no listing, because
  every credits mechanism issues against quota — the delegate's settlement
  admissibility decides that, not an API-credit branch.
- Bare metal keeps refusing unbacked pools, because this change adds no unbacked
  bare-metal supply and the delegate cannot express the refusal: bare metal composes
  contact exchange, so settlement admissibility alone would publish a contact-only
  unbacked listing. The refusal stays as an explicit, temporary check in bare-metal
  publication's pool reading — the one comparison of the label left in the tree, with
  a test — and `unbacked-bare-metal-listings` removes it. Rejected: a per-domain
  declaration of the backings each storefront publishes, which would be permanent
  machinery for a state that lasts only until that change lands, after which every
  domain would publish every backing.

### Divergence: binding construction (task 1.3)

Today VM builds its binding with `publication_binding` from the durable listing
binding's recorded label; bare metal builds `CapacityBinding` directly and refuses a
durable label other than backed; API credits builds `CapacityBinding` from the
published `listing_resource` and records no durable listing binding at all, so it does
not meet `storefront-publication`'s requirement that every storefront listing have one
immutable common mapping.

Unified rule: every domain builds its binding in one place, `publication_binding`,
from the durable listing binding's recorded site, offering mode, source, and backing
label. Nothing builds a binding from a published payload or names a binding category.

- VM already does.
- Bare metal's `binding_for_listing` calls `publication_binding` with the recorded
  label, and its refusal of a label other than backed goes: its pool reading is the
  only place it refuses unbacked supply (see "Divergence: admitting unbacked supply").
- API credits records a durable listing binding at listing creation, through the core
  write VM and bare metal use: the site, the `api_credits` mode, the quota resource as
  source, its pool, the domain identity and version, and the backing label its pool
  declares. Its hold, release, and reconciliation build their binding from that
  record. That closes the requirement's gap for API-credit listings.

API credits has not launched, so there is no upgrade path and no backfill. The
API-credit storefront needs a fresh database, and refuses at startup a database
holding a listing with no binding, naming the remedy, rather than failing later when
a capacity operation finds none — the same posture `ARCHITECTURE.md` takes for
incompatible API-credit evidence and grant schemas.

API credits also records no negotiation-thread binding when an opening is accepted,
which VM and bare metal copy from the listing binding. That is the same requirement's
gap for threads, but no backing decision reads a thread binding, so it is outside this
change; it is recorded as unowned in the change index.

### Divergence: the published label (task 1.3)

Today VM publishes its binding's label, through a listing model that types the field
with its own copy of the vocabulary; bare metal publishes a hard-coded `"backed"`
through a `Literal["backed"]` field; API credits publishes none, and the API-credit
registry schema has no such field.

Unified rule: a listing's published `capacity_backing` is always its binding
delegate's label, nothing else writes it, and no listing model types it with a copy of
the vocabulary — it is `CapacityBackingLabel`. Whether a market publishes the label at
all is its registry schema's decision, which is operator curation rather than a backing
decision: the compute schema carries it, as `registry-discovery`'s "Compute listings
publish their capacity backing" requires, and the API-credit schema does not.

- VM's listing model types the field `CapacityBackingLabel | None`, `None` remaining
  only for rows stored before the field existed.
- Bare-metal derivation sets the field from the candidate's delegate, and
  `BareMetalListing` types it `CapacityBackingLabel`. That publishes no unbacked
  bare-metal supply: pool reading still refuses it, and the payload's unbacked form is
  `unbacked-bare-metal-listings`'.
- `arkhai-bare-metal` and VM's listings package therefore depend on
  `kit/resource-pools-contracts`, a downward edge `make check-architecture` permits;
  planning confirms the VM buyer, which imports the listing models, stays light.
- API credits publishes no label. Its durable binding records one, which is what every
  backing decision reads. Rejected: adding the field to the API-credit schema, which
  would tell a buyer nothing — every published API-credit listing is backed — and
  would change the schema identity buyers match.

### Divergence: backing disagreement on refresh and reopen (task 1.3)

`storefront-publication` fixes a listing's backing for the life of its binding: a
listing whose binding's backing disagrees with its source's is reopened by no path,
and a supply move closes it so a new listing binds. Today VM compares the two first,
before identity, and closes and never reopens on a mismatch; bare metal holds backing
as a term field with no backing outcome and a derivation key that excludes it, so a
pool re-created under the same identifier with the opposite backing would refresh its
listings in place — unreachable only because bare metal refuses unbacked pools; API
credits' availability reopen consults no source.

Unified rule:

- One shared comparison, `backing_changed(binding, source_backing)`, beside the
  binding in `kit/capacity-publication`: whether the binding's delegate differs from
  the delegate the source's pool now declares. It is label equality and holds no
  category knowledge.
- Every domain applies it first on every refresh, every reopen, and every source check
  — VM's listing comparison, bare metal's, API credits' reopen, and all three source
  checks. A mismatch closes an open listing and refuses any reopen or in-place refresh;
  a source check reports it as a declared mismatch.
- Backing is neither an identity field nor a term: bare metal removes it from its term
  fields.
- The published label only restates the binding's (see "Divergence: the published
  label"); VM's refresh of a legacy listing published without the label is that rule,
  not a backing comparison.
- API credits compares against its pool's current declaration, which it reads under
  "Divergence: admitting unbacked supply".

The publication runtime's refusal of a supplied binding that differs from the persisted
one, which now includes backing, stays as a backstop. It raises a fault; the shared
comparison runs first so that a backing change is the ordinary close the requirement
describes.

### Divergence: source-check availability (task 1.3)

Today VM's listing-source check compares the listing with a re-derivation over
declared capacity, then reads its site's availability only when the binding's class is
`CapacityBinding`; bare metal's runs publication's classification over the site's live
projection, which folds declaration and availability together and always consults
availability; API credits contributes no listing-source check, and its per-proposal
`credit_quota_guard` always compares the requested quantity with a quota snapshot.

Unified rule: wherever availability gates a seller decision, it goes through
`binding.backing.judge(declared, available)`. Each domain supplies only the two halves'
content, which is domain-specific because a listing's shape originates differently in
each.

- VM: the declared half is today's comparison over declared capacity; the available
  half is today's read at the pinned site. The class test goes.
- Bare metal: its classification splits into a declared half — enablement, shape
  digest, region, pool admission — and an available half, the view's whole-machine
  availability. Publication's classification uses the same split, so publication and
  the guard keep one code path. A backed listing's outcome is unchanged.
- API credits contributes a listing-source check to the negotiation runtime, as VM and
  bare metal do: the declared half confirms that the binding's quota resource is still
  declared in its pool, that the pool is enabled and advertises `api_credits`, and that
  the backing is unchanged; the available half requires at least one available unit,
  the condition listing creation already requires.
- `credit_quota_guard` stays a seller policy, because the runtime's source check sees a
  listing, not a proposal's requested quantity. The round hook supplies its quota
  snapshot through `binding.backing.judge`, so for a listing availability does not
  bound, the guard reports itself not applicable rather than assuming backed.

The domains still obtain projections differently — VM from the projection its
storefront holds, bare metal by fetching the site's live — but that is not a backing
decision, and extracting VM's held per-site projection state into the kit belongs to
`kit-owned-listing-and-fulfillment-lifecycles`. It bears on backing in one place:
`storefront-publication` forbids contacting a site authority when checking an unbacked
listing, which bare metal's live fetch would do. That is decided in
`unbacked-bare-metal-listings`, which publishes the first unbacked bare-metal listing.
API credits' move onto the runtime's listing-source check comes from
`resolve-compute-family-findings`, whose item now names only the projection half.

### Divergence: reconciliation scope (task 1.3)

`storefront-publication` applies source reconciliation to every listing and
capacity-availability reconciliation, with its close-before-reopen sequencing, only to
capacity-backed listings. Today VM scopes its availability paths — capacity events, a
release, a failed deal, an administrator resize, and availability reopen — with a
`backed_only` filter on the durable binding; bare metal folds availability into one
publication pass over per-resource classes and scopes nothing, every listing being
backed; API credits closes and reopens every listing on availability.

Unified rule: whether availability reconciliation may touch a listing is the
delegate's decision, expressed according to how a domain selects listings.

- Where listings are selected in a query (VM), the backed-only filter becomes the
  delegate registry's `labels_reconciled_by_availability()`, and the boolean parameter
  becomes the choice between availability and source reconciliation, only the former
  applying the label set.
- Where listings are judged one by one (bare metal, API credits), availability closes
  and reopens come from the available half of `judge`: bare metal's resources cannot
  classify as unavailable unless their delegate is bounded by availability, and API
  credits judges each listing's quota through its binding's delegate. Source
  reconciliation still applies to every listing.

VM's separate availability paths and bare metal's single pass are structure, not
backing: the requirement constrains which listings each reconciliation may touch, not
how many passes a domain runs. Unifying that structure belongs to the shared
publication pipeline this change leaves out, recorded as unowned in the change index.

### Divergence: hold placement (task 1.3)

Today VM's acceptance skips a hold for an unbacked binding, recording
`capacity_hold_not_applicable`, and otherwise reserves one; API credits always
reserves; bare metal places no hold at acceptance and reserves when settlement starts
fulfillment, as its lifecycle requires.

Unified rule: backing decides only whether a hold can stand behind a listing, and every
domain that places one does so through `binding.backing.place_hold(place)`. Whether a
domain holds at acceptance at all, and for how long, is hold policy, owned by
`default-no-pre-settlement-capacity-hold` and `negotiation-time-capacity-hold`, not by
this change.

- VM's class test becomes `place_hold`; a hold not placed records the same
  `capacity_hold_not_applicable` event.
- API credits places its hold through `place_hold`, so an unbacked binding would never
  reserve; no API-credit listing is unbacked, so behaviour is unchanged.
- Bare metal places none — a policy difference, not a backing one. Its reservation at
  settlement is a capacity effect, guarded under "Divergence: capacity-effect guard
  coverage".

### Divergence: capacity-effect guard coverage (task 1.3)

`CapacityRuntime` is meant to be the one boundary every capacity effect passes, guarded
before any site call. Five paths bypass it, calling the aggregate capacity client with
no binding and no guard: bare-metal fulfillment's settlement-time reserve and its
commit, bare metal's administrator reserve, and VM's fulfillment-resume recovery
reserve and commit. VM's administrator reserve also synthesizes a backed binding for a
reservation that has no listing.

Unified rule: every storefront capacity effect — reserve, commit, release, lease
truncation — goes through the kit's capacity effects with the listing's
`PublicationBinding`, whose guard is the delegate's `require_admission`. Nothing
reserves, commits, releases, or truncates through the aggregate client. (Amended in
planning: the effects are `CapacityEffects`, which `CapacityRuntime` composes, because
bare metal has no runtime to move onto — see "Bare metal's effects go through
`CapacityEffects`, not a runtime".)

- The five paths move onto the binding-taking effects, with the binding built from the
  durable listing binding. The effects act at the binding's site. Bare metal's durable
  reservation-to-site map stays: it never routed a commit, and it routes every
  fulfillment verb.
- A reservation exists only because a site admitted it, so a binding synthesized for a
  reservation with no listing takes its backing from a registry-level
  `admitted_backing()`, beside `legacy_producer_backing()`, rather than naming a
  category.
- Rejected, except as a fallback planning must bring back for decision: keeping the
  aggregate calls with `require_admission` placed before each, which leaves five
  places that must each remember the guard.

The bare-metal fulfillment routes' unhandled error for a binding with no host is
`unbacked-bare-metal-listings`', since only that change creates such a binding; the
guard here gives it a refused admission rather than a site call.

### Divergence: whether a mechanism delivers through capacity (task 1.3)

Settlement admissibility needs, for each mechanism a domain composes, whether settling
through it delivers through capacity. Today VM keeps that in a map separate from its
seller stage table, checked only when an unbacked listing is derived; bare metal keeps
it on each seller stage-table entry as a required `physical` field, which also gates
admission and evidence at acceptance; API credits declares it nowhere. Where both
exist, the values agree.

Unified rule: it is a required attribute of every seller stage-table entry, named
`fulfils_through_capacity`, and each domain's admissibility callback reads it from the
entry a clause's mechanism selects.

- Bare metal renames `physical`; its admission and evidence gating is unchanged.
- VM declares it on its three seller stages and removes its separate map, its lookup,
  and the undeclared-mechanism error. A stage that does not declare it cannot be
  constructed, so the lazy check goes.
- API credits declares it `True` on both stages, each of which issues against quota;
  that is what makes an unbacked credits pool yield no listing through the delegate.

It is a per-domain convention with one name, read only by each domain's own callback.
No kit protocol is added: core's stage table is opaque by design, and shared stage
conventions were kept out of core and the settlement runtime when settlement routing
by mechanism was designed. Rejected: a separate per-domain map, which can drift from
the stage table it describes.

### Site publication views stay outside this change (task 1.5)

The inventory found no backing decision on the site side beyond the pool declaration
rules: no publication view reads backing, and every bare-metal view is backed by
construction, requiring a host and carrying availability. Giving resource views the
pool's delegate here would add behaviour with no existing switch to replace, whose
only consumer is the unbacked bare-metal view. It moves to
`unbacked-bare-metal-listings`, which publishes that view, together with the delegate
operation the view needs.

## Planning decisions (task 1.6)

Planning read every site the inventory named on 2026-10-14. Two findings changed or
completed a decision and were decided with the maintainer; the rest refine an
operation's contract or record what planning confirmed.

### Bare metal's effects go through `CapacityEffects`, not a runtime

"Divergence: capacity-effect guard coverage" moved the five bypassing paths onto
`CapacityRuntime`. Bare metal composes no runtime. It builds a core
`AggregateCapacityClient` over a `DurableReservationSiteMap` that the aggregate writes on
every reserve and that its `SelectedSiteFulfillmentClient` reads to route every
fulfillment verb, and it runs no capacity-event poller: its publication cycle is its
reconciliation. `CapacityRuntime` builds its own aggregate with no reservation map, so
reserving through it would stop writing the map and break fulfillment routing.

Decided with the maintainer: the guarded effects — `reserve`, `commit`, `release`,
`truncate_lease`, and the guard they share — move out of `CapacityRuntime` into one
class in `kit/capacity-publication`, `CapacityEffects`, composed over any aggregate
client and acting only at the sites that aggregate names. `CapacityRuntime` builds one
over its own aggregate and delegates to it, so VM's and API credits' calls are
unchanged. Bare metal builds one over the aggregate it already has, so the map keeps
being written. The guard still lives in one place.

Rejected: putting bare metal on a full `CapacityRuntime`, which needs an injected
aggregate and a reconcile hook bare metal would never use and pulls its capacity
transport into the runtime's lifecycle, overlapping
`kit-owned-listing-and-fulfillment-lifecycles`; and the design's fallback, a
`require_admission` call before each of bare metal's three aggregate calls.

VM's two resume paths need no such seam: VM already composes the runtime, and the
aggregate its resume runtime calls is `runtime.client()`.

### An API-credit listing's derivation identity is its listing ID

The durable listing binding needs a `derivation_key`, built by
`build_storefront_derivation_key` from site, mode, domain identity, and a source
identity, and the column is unique. VM and bare metal use it to find the listing a
candidate already published. API credits derives nothing: an operator creates each
listing through `publish-from-quota`, and may create several over one quota resource.

Decided with the maintainer: an API-credit listing's source identity in its derivation
key is its listing ID, so every listing binds under its own key. The binding records the
quota resource as `source_id`, with its pool and backing, and those are what every
backing decision reads. Rejected: keying on the quota resource and refusing a second
open listing over it, which would turn a storage constraint into an undecided product
rule. The demo seed's own scan for an existing listing is unrelated and stays.

### Two API-credit defects are fixed where this change already edits

Found while planning; decided with the maintainer to fix in this change rather than
record as unowned, because both sit in code this change rewrites:

- `apicredits_storefront/cli.py` constructs `ListingService` without its required
  `settlement_composition`, so the command fails at construction.
- `POST /api/v1/listings/publish-from-quota` accepts `settlement_clauses` and drops
  them before `publish_from_quota`.

### Operation contracts

Refinements of "The delegate's operations", decided in planning:

- **`judge(declared, available)`.** `declared()` returns the caller's refusal, or
  `None` when the declaration fits. The delegate returns that refusal; otherwise,
  where availability bounds the supply, `available()`'s result, and where it does not,
  `None`. `None` always means the listing stands. An async form, `judge_async`, takes
  coroutine functions and decides identically, because the source checks and the quota
  guard read availability over the network.
- **`place_hold(place)`** is a coroutine: `place` is a coroutine function, and an
  unbacked delegate returns `None` without calling it.
- **`require_admission(effect)`** takes the effect's name for the refusal message and
  returns nothing; `CapacityEffects` calls it before its site check.
- **`labels_reconciled_by_availability()`** returns a frozenset of labels, so a SQL
  filter binds it as parameters rather than naming a label.

### What planning confirmed

- **VM's listing-creation site check.** VM's `listing_service.py` refuses a backed
  listing whose site is not a configured capacity site, and computes unbacked
  settlement terms otherwise. Both become delegate operations: the site check is the
  available half of `judge` — whether an admission authority stands at the site — and
  the settlement terms are `admissible_settlement` for every listing, which keeps every
  clause of a backed one.
- **The quota guard.** The round hook supplies the snapshot as `judge_async`'s
  available half, with a declared half that always fits. For a listing availability
  does not bound, no snapshot is supplied, and `credit_quota_guard` reports itself not
  applicable on an absent snapshot rather than rejecting.
- **Legacy writes.** VM's `domain_migration.py` binds a legacy single-domain listing as
  backed; it takes `legacy_producer_backing()`, since such a listing predates the
  declarations. The applied migrations that backfill `'backed'` — core's and bare
  metal's — stay as written, for the reason core's does.
- **The VM buyer stays light.** `arkhai-vms-listings` gains
  `arkhai-kit-resource-pools-contracts` as a base dependency, which installs only
  pydantic and the shape kit. The buyer's guard test forbids `market_resource_pools`,
  the authority, and still passes.
- **The site-client fixture.** `kit/site-client`, a `client` kind, may depend on a
  `contracts` package, so its resource-pool fixture validates the label through the
  registry. Its default deliverable set — what the pool advertises when that is a
  valid declaration for the backing, otherwise nothing — asks the delegate's
  `declaration_problems` rather than branching on the label.
- **API credits reads its pool.** The credits ledger already projects each resource's
  `pool_id`; with the pool directory passed to `make_capacity_router`, the storefront
  reads the quota resource's pool from the site's resource-pool projection through
  `CapacityRuntime.site_client(site_id)`. The storefront gains `arkhai-kit-resource-pools`
  for `read_site_declarations`, as VM's and bare metal's do, and its `SQLiteClient`
  sets the domain registry core's binding write needs, as bare metal's does.

### Bordering changes, reconciled

- **`inject-site-pool-authority`** moves `site_declarations.py` into
  `kit/resource-pools-contracts`. This change edits that module in place; its move stays
  mechanical, and the delegate is already where the module would move to.
- **`kit-owned-listing-and-fulfillment-lifecycles`** moves the listing lifecycle into
  `kit/capacity-publication` and retires VM's resume pass. It inherits
  `CapacityEffects` and `PublicationBinding`; this change moves the resume pass's two
  effects onto the effects and leaves its structure.
- **`kit-owned-storefront-auth-and-persistence`** moves `domain_registry.py` into
  `kit/storefront-contracts`, which inherits the edge to `kit/resource-pools-contracts`
  that `StorefrontListingBinding` gains here.
- **`align-package-paths-with-layers`** touches no file this change does.
- **`default-no-pre-settlement-capacity-hold`** has open validation tasks over
  `test_two_phase_reserve.py`, whose binding imports this change rewrites; they still
  apply to the rewritten file.
- **`negotiation-time-capacity-hold`** names `_place_capacity_hold`, which keeps its name
  and now places its hold through `place_hold`.
- **`resolve-compute-family-findings`** was reconciled in design ("Divergence:
  source-check availability").

## Implementation notes

Decided or learned while implementing, each within a decision above:

- **`CapacityEffects` addresses the aggregate by site.** Every effect calls the
  aggregate's own `reserve`, `commit`, `release`, or `truncate_lease` with the
  binding's site, after checking the aggregate names that site. The core aggregate
  sends a site-addressed effect straight to that site, so this is the runtime's
  behaviour unchanged, and a storefront's own aggregate keeps whatever it records
  per reservation.
- **VM's listings package compares delegates itself.** `compare_listing` in
  `arkhai_vms_listings`, which the VM buyer imports, cannot depend on
  `kit/capacity-publication`, so it takes the two delegates and compares them by
  identity — the predicate `backing_changed` is. Storefront callers pass the
  binding's delegate and the source's.
- **A listing left with no settlement option is refused whatever its backing.**
  VM's creation refused only an unbacked listing left with none; preserving that
  exactly needs a branch on the label. Refusing any listing with no option
  publishable satisfies "An unbacked listing publishes only settlement options its
  domain does not fulfil through capacity" without one. A backed VM listing with no
  option would have published unbuyable before; no VM suite exercises one.
- **Bare metal's binding builder has its own module.** Fulfillment and deal
  controls build the binding the way publication does, and importing it from
  `publication_service.py` closed an import cycle through `sqlite_client.py`, so
  `bare_metal_listing_binding` lives in `listing_binding.py`, which depends on
  neither.
- **API credits needs no domain registry on its client.** Core's
  `upsert_listing_with_binding` validates without one, so the planned registry is
  not added. Test fixtures write listings through the same binding helper creation
  uses.
- **The API-credit source check reads the site through the aggregate.** As the
  bare-metal check does, through `site(site_id)`; an unconfigured site is
  unverifiable.
- **The API-credit reconciliation rules take a judge.** The domain package keeps
  its pure rules and gains no dependency: each rule supplies the availability half,
  and the storefront judges it through the listing's binding.
- **Provenance is the domain's; admission is the delegate's.** The delegate decides
  whether a binding admits capacity and whether availability is asked. It does not
  decide whether a source is still the one a listing was bound to: each domain's
  declared half checks that against its own durable record. For API credits that
  record names the pool, so the source check and the reopen path read the quota
  resource from that pool only. A resource now in another pool is a declared
  mismatch even if that pool declares the same backing and advertises API credits,
  and reconciliation does not reopen its listing. Both paths read the record once,
  through `api_credit_listing_source`, which returns the capacity binding with its
  bound pool. Creation, which has no record yet, still takes whichever projected
  pool holds the resource.
- **API-credit negotiation reads only the bound site.** The quota guard matches
  snapshot rows by quota resource, so the snapshot a round captures comes from the
  listing's bound site through the aggregate's `site(site_id)`, not from the union
  of every site; another site naming its resource the same way cannot cover the
  quantity. Reconciliation already keys availability by site and resource, so this
  was the one unscoped read. The guard itself is unchanged.
- **The credits projection is proven over the real service.** The pool directory
  reaches the resource-pool projection only through the credits service's own
  router wiring, which no lower test sees. The service's signed-authority suite
  reads the projection through the storefront's typed reader client against the
  real application and resolves the quota resource's pool to backed, enabled, and
  advertising API credits. Without the directory the pool still resolves backed
  but advertises nothing, which that test catches.

## Open questions

None.
