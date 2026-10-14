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
declarations, reconciles every listing, always places a hold, and publishes no
`capacity_backing` label, so the registry's backing filter, which fails on a missing
field, excludes every API-credit listing. Each is unified under task 1.3.

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
  `read_site_declarations`, binds with that pool's delegate, and publishes the
  `capacity_backing` label, which also brings API-credit listings within the
  registry's backing filter. An unbacked credits pool would yield no listing, because
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

## Open questions

Each is a decision gate in `tasks.md`.

1. The unified behaviour for each divergence between VM, bare metal, and API credits
   (task 1.3):
   1. the published label — from the binding in VM, fixed to backed in bare metal,
      absent in API credits;
   2. a binding whose backing disagrees with its source's on refresh and reopen;
   3. source-check availability;
   4. reconciliation scope;
   5. hold placement;
   6. capacity-effect guard coverage;
   7. the mechanism fulfilment declaration — VM's separate map, bare metal's
      `physical` on each seller stage.
2. How the site's resource publication views receive the pool's delegate, given that
   `InventoryViewProjection.resource_views` receives no pool today (task 1.5).
