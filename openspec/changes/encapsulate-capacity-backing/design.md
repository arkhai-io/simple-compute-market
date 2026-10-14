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

## Open questions

Each is a decision gate in `tasks.md`.

1. The delegate's operations, their signatures, and the delegate's name (task 1.2).
2. The unified behaviour for each divergence between VM, bare metal, and API credits
   (task 1.3):
   1. admitting unbacked supply — VM derives it, bare metal refuses it, API credits
      reads no declarations;
   2. binding construction — three paths;
   3. the published label — from the binding in VM, fixed to backed in bare metal,
      absent in API credits;
   4. a binding whose backing disagrees with its source's on refresh and reopen;
   5. source-check availability;
   6. reconciliation scope;
   7. hold placement;
   8. capacity-effect guard coverage;
   9. the mechanism fulfilment declaration — VM's separate map, bare metal's
      `physical` on each seller stage.
3. How the sibling `CapacityBinding` and `UnbackedBinding` classes relate to the
   delegate: whether the binding carries the delegate, or the class stays the type
   that capacity effects require (task 1.4).
4. How the site's resource publication views receive the pool's delegate, given that
   `InventoryViewProjection.resource_views` receives no pool today (task 1.5).
5. Where bare metal's refusal of unbacked pools is expressed while this change keeps
   it (task 1.3).
