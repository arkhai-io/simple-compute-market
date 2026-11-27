# Design: settle-capacity-claim-vocabulary

## Context

**The resource type today.** `resource_type` is a free string on a capacity declaration
(`kit/site/src/market_site/declarations.py`). The site stores it on the declaration's row
with the column default `compute.gpu` (`kit/site/src/market_site/db.py`); the registration
request, the ledger and the administration client default it to `compute.gpu`
(`kit/site/src/market_site/http_models.py`;
`kit/site-client/src/market_site_client/client.py`); and a capacity-definitions document
requires every entry to write it (`kit/site/src/market_site/capacity_definitions.py`).
Three things read it:

- **Admission.** The VM storefront writes the constant `compute.gpu` on every claim,
  whatever the shape
  (`domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`,
  `compute_capacity_claim_from_order`). The site refuses a declaration whose type differs
  from the claim's, and a claim that names none matches any type
  (`kit/site/src/market_site/ledger.py`, `resource_satisfies_requirement`).
- **Scheduling.** The scheduler takes a reservation's kind from its deal reference, else
  from the scheduling request's `requirements.resource_kind`, else from a default its
  composition configures (`kit/fulfillment/src/market_fulfillment/scheduler.py`,
  `_requirement`). The compute provisioning service configures `compute.gpu`
  (`provisioning/compute/service/src/compute_provisioning_service/container.py`). The
  candidates are the declarations whose stored type equals the kind (`ledger.py`,
  `iter_scheduling_candidates_in_session`), and the round-robin cursor is one row per kind
  (`kit/fulfillment/src/market_fulfillment/db.py`, `SchedulingCursor`), which
  `fulfillment`'s "Scheduling and assignment" requires.
- **Publication.** Every projected pool member carries its type, which `site-capacity`'s
  "Resource-pool projection metadata" requires to be non-empty. The VM storefront holds a
  pool with a member that states none, and judges whether a member can serve a shape with
  the claim that shape would reserve with
  (`domains/vms/listings/src/arkhai_vms_listings/reconciler.py`;
  `domains/vms/storefront/src/market_storefront/services/shape_feasibility.py`).

The same literal has a namesake. On a VM listing resource payload, an explicit
`resource_type` of `compute.gpu` or `token.erc20` says whether the payload is compute or
a token (`domains/vms/listings/src/arkhai_vms_listings/models.py`,
`payload_resource_type`). It decides nothing at a site and is not published.

**The claim's type stops at admission.** Nothing sets a kind on a deal reference, and the
VM storefront schedules with empty requirements
(`domains/vms/storefront/src/market_storefront/delivery_ports.py`), so every VM
reservation is scheduled under the site's configured default. The scheduler reads a
reservation's attributes and dimensions from what admission recorded, on the rule that
what admission accepted governs what scheduling may place; the kind is the exception.

**One type for every VM shape is deliberate.** A VM shape need not state GPUs, and a
shape that states none is declared, claimed and scheduled as `compute.gpu`. A CPU-only
shape therefore lands on any member with the vCPUs and memory free, a GPU host included,
which lets a GPU machine's spare capacity sell
(`openspec/specs/storefront-publication/architecture.md`, "Listing shapes and the
storefront's authority"). A type chosen from the shape and matched against the
declaration would end that: a claim names one type, and a host carries one declaration.
The design that kept the single type recorded where the type is headed instead: the
category of compute shape, apart from the offering mode
(`openspec/changes/archive/2026-10-29-gpu-optional-compute-shapes/design.md`, D4).

**What each party sees.** A buyer sees nothing: the type is not a field of the published
listing resource, and nothing in the registry or a buyer reads it. An operator declares a
machine with no GPU as `compute.gpu` (`docs/operator-handbook.md`, "Capacity
definitions"; `docs/seller-quickstart.md`) and reads it back so in the pool projection.
An operator who writes `compute.cpu` instead gets a member no VM claim matches, reported
as `listing_shape_infeasible` with no mention of the type. A declaration's type can be
overwritten while reservations stand against it; a pool move under obligation is refused,
a retype is not.

**Bare metal.** Operators declare a whole machine as `compute.bare-metal`
(`docs/bare-metal-seller-quickstart.md`). The bare-metal claim names no type: it pins the
Physical Resource, asks one unit, and carries the offering mode and the listing's
attributes (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/claims.py`).
The type is read only at scheduling. The storefront sends
`requirements.resource_kind: compute.bare-metal` beside the pinned resource, because the
site's default would otherwise list no bare-metal candidate, and it refuses a scheduled
resource of any other kind
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/delivery_ports.py`,
`_schedule`). A pinned resource bypasses the cursor. A machine declared under any other
type is admitted and then fails at scheduling, once the deal is settled. The type restates
what the reservation's offering mode and the pool's provider already establish, and no
specification names the string.

**What a pool states.** A Resource Pool's `policy_tags` hold what the pool declares: the
offering modes it delivers and advertises, its capacity backing, and its publication
hints (`kit/resource-pools-contracts/src/market_resource_pools_contracts/hints.py`). A
pool write accepts a tag it does not know (`resource-pool-management`'s "Typed pool
models validate policy hints"), the site projects a pool's tags verbatim
(`kit/site/src/market_site/projections.py`), and both compute storefronts derive their
listings from projected pools. The site decides on four facts of a pool, read through a
port its composition supplies: whether it exists, whether it is enabled, the modes it
delivers, and whether its declarations need a host
(`kit/site/src/market_site/pool_facts.py`). Admission refuses a claim whose offering mode
the pool does not deliver, the reservation records the mode, and scheduling and dispatch
check it again against the pool's current statement (`site-capacity`'s "Offering mode is
enforced through fulfillment"). A pool that states no deliverable mode delivers none.

**What a buyer can find.** A compute listing publishes its offering mode, its capacity
backing and the quantities its shape states, and the compute filter specification
filters each (`core/registry/src/core_registry/filter-spec.yaml`). A listing without GPUs
publishes no GPU field, so a query bounding a GPU field excludes it and a query bounding
none includes it. No query selects only such listings: a filter decides a listing that
states nothing at its path by its missing-value rule before an `exists` test runs, so
`exists:false` matches nothing (`core/registry/src/core_registry/api/filter_eval.py`). A
buyer looking for machines without GPUs asks for vCPUs and memory and is answered with
every GPU listing that states them as well.

**Where the type is held.**

| Form | Where |
|---|---|
| Stored declarations | `capacity_buckets.resource_type` in each provisioning database |
| Operators' documents | capacity-definitions documents, imported again at every start when mounted, and registration calls |
| Site to storefront | each projected member's `resource_type` |
| Storefront to site | the claim's `resource_type`; the scheduling request's `requirements.resource_kind`; the schedule response's `resource_kind` |
| Reservations | the request recorded under a placement key, compared on replay |
| Settlement records | the recorded scheduling requirements, compared on a repeated schedule |
| Scheduling | `scheduling_cursors.resource_kind` |

It is not on a registry, in a retained listing, in an Agreement or in settlement
evidence.

**Released.** `marketplace-v0.4.0` carries every form above as it stands on the
development branch. The compute provisioning contract is at major 3, and a provisioning
service and the storefronts that call it are upgraded and rolled back together
(`compute-provisioning-contract`'s "Explicit contract incompatibility").

## Decisions

### D1 — This change gives the resource type one meaning in both compute domains

The change makes the resource type the category of compute a seller sells: what a pool
states, a claim carries, a reservation records, scheduling reads, a listing publishes and
a buyer filters by, for VM and bare metal alike (D3, D4). It also decides what becomes
of bare metal's type, which restates its offering mode, since the two are one field and
the second cannot be answered before the first says what the field means.

Nothing else is in it. The storefronts' whole-claim key `required_attributes` keeps its
name here; the change index notes it on `kit-owned-storefront-auth-and-persistence`,
which moves the wire models that carry it. The flat dimension names stand (D2). What a
capacity claim is, and how its quantities and attributes are matched, is in
`docs/development/ARCHITECTURE.md`, "Terms", and the `site-capacity` companion. A VM
listing already publishes no null for an absent capacity attribute
(`storefront-publication`'s "Registry repair republishes the domain's candidate"). The
form a buyer states a shape in when opening a negotiation is not decided here.

Rejected:

- Renaming the claim key and deciding the dimension spelling as one vocabulary cleanup.
  The key is on two administrator routes of both storefronts and inside retained VM
  settlement evidence, and no participant reads its name; the spelling is settled by
  what is released (D2). Neither changes what a seller or a buyer can do.
- Closing the change and recording the resource type as unowned. A shape without GPUs
  sells, but a buyer cannot ask for supply by the work it suits, and the type that would
  say so is a constant.
- A change for the resource type and another for bare metal. They edit the same field,
  the same rows and the same two matching functions.

### D2 — The flat dimension names stand

`gpu_count`, `gpu_model`, `vcpu_count`, `ram_gb` and `disk_gb` are the compute family's
flat names and are not spelled after their families. The family and field name a value
where a seller states or prices a shape; the flat name is its wire name in a published
listing, a registry filter, a claim's dimensions and a capacity declaration. The compute
family's companion
says so (`openspec/specs/market-composition/architecture.md`, "The compute family
vocabulary").

The names are in every form `marketplace-v0.4.0` carries: the registry's filter
specification and the listings it retains as published, both domains' capacity
declarations and operators' definition documents, recorded reservations, accepted
Agreements, and the queries and shapes buyers type. Both compute domains bind one schema
(`market-composition`'s "The compute family shares one capability schema"), so they
cannot diverge.

Rejected:

- Respelling them `cpu_count`, `memory_gib` and `storage_gib`. It changes each of those
  forms, for registries, storefronts, sites and buyers at once, and changes nothing any
  of them says.
- Leaving the question open. `publish-shape-bounds` shows a buyer a shape and its bounds
  and has to know which names a listing carries.

### D3 — A category is a seller's label for the work supply suits, published and filterable, and it constrains no shape

A category is a broad label for the kind of work a listing's supply suits. A seller
states it, it travels to the listing, and a buyer narrows a registry query by it, to find
shapes by how they are typically used. Three are documented, and they do not close the
list:

| Category | The listings it tends to hold |
|---|---|
| `compute.gpu` | supply oriented to GPU-heavy work |
| `compute.cpu` | supply oriented to CPU-heavy work |
| `compute.db` | supply oriented to database work, which tends to be bound by disk I/O |

A category constrains nothing about the shapes listed under it. No party checks a shape
against its category: no site refuses a claim or a declaration, and no storefront
withholds a listing, because a shape does not fit a category, and no category is derived
from a shape. `compute.cpu` does not mean a shape without GPUs. A query for it is
answered with the listings their sellers labelled for CPU-heavy work, whatever those
shapes state, and a buyer who needs particular quantities bounds them in the same query
(the published field's name is Q4's):

```sh
market listing list --resource 'category=compute.db disk_gb>=2000'
```

A label is what the published quantities cannot say. A seller knows what its supply is
suited to, and no family of the compute schema separates database work from any other,
so no rule over a shape could define `compute.db`. A name that carries no rule can be
added without one, which is why the list stays open.

Rejected:

- A truer name and nothing more: declarations and claims saying `compute.cpu` for a
  machine without GPUs. It corrects what an operator reads and changes nothing anyone can
  do.
- A category internal to the site, used to keep classes apart in placement and in the
  scheduler's fairness state. A seller already keeps supply apart by pool, and a buyer
  would still be unable to find it.
- A category that fixes what a shape may state, such as `compute.cpu` for a shape
  without GPUs and `compute.gpu` for one with, whether checked at the pool write, at
  publication or at admission, or derived from the shape. It repeats what the published
  quantities already say, has nothing to check for database work, and needs a new rule
  for every name.

### D4 — The pool states the categories it sells, and the claim, the reservation and scheduling carry the one a deal is in

A Resource Pool states the categories it sells in its policy tags, beside the modes it
delivers:

```yaml
pools:
  - id: vm-california
    provider: vm.ansible
    policy_tags:
      deliverable_modes: [vm]
      advertisable_modes: [vm]
      capacity_backing: backed
      categories: [compute.cpu]
```

A claim against that pool carries the category of what is being bought. The site admits
it only where the pool states that category, and records the category on the
reservation, as it records the offering mode. Scheduling reads the category from the
reservation and advances the cursor of that category; which declarations it may then
place the reservation on is Q3's. Scheduling takes a kind from its composition's default
only for a reservation that records none.

Each of these compares or carries a name. The site sets the claim's category beside the
pool's statement and reads nothing of the claim's dimensions against it (D3).

A pool that states no category admits what it admits today, and a statement left as
released behaves as released: a claim naming `compute.gpu` is matched against a
declaration typed `compute.gpu`, a bare-metal reservation is scheduled as it is under
`marketplace-v0.4.0`, and a reservation recorded before the category existed is
scheduled under the default. Omission states no commitment
(`docs/development/ARCHITECTURE.md`, "Omission states no commitment"): a listing of a
pool that states no category publishes none.

The pool is where a site states policy that varies, and it is where a seller already
authorises an offering mode. A pool may state `compute.cpu` over GPU hosts, so selling a
GPU machine's spare vCPUs and memory stays the seller's choice, made per pool. No
declaration is rewritten to adopt a category.

Rejected:

- The category on the declaration, matched by equality, with the claim's derived from its
  shape. A host carries one declaration, so a CPU-only shape could never use a GPU
  host's spare capacity, every operator would retype every declaration, and no category
  is derived from a shape (D3).
- The category on the claim alone, derived from the shape, with no statement by the
  seller. The seller would not choose what its supply is sold as, and a category no
  shape can derive, such as `compute.db`, could not exist (D3).
- A set of categories on each declaration. It puts a commercial choice on the record of
  a machine and repeats it for every machine of a pool.
- Scheduling by the composition's default kind, or by a kind the storefront restates in
  its scheduling request. What admission accepted governs what scheduling may place, and
  a restated kind is a second statement that can disagree with the first.

### D5 — The change is Goal 2's

Goal 2 sells and negotiates full shapes, and a shape need not state GPUs. Finding supply
by the work it suits is the part of that a buyer still lacks, so the change is listed in
Goal 2's campaign and owns three of the goal's gaps: the constant resource type, bare
metal's type, and the listing that publishes no class of compute for a buyer to search
by. That last gap is recorded with a second half, that no query selects exactly the
listings stating no GPU field. A label does not answer it (D3); Q6 says what becomes of
it.

It delivers nothing of Goal 3. A host still carries one declaration and a pool one
provider, so one machine is not sold in two modes by this change.

Rejected: the POOLS capacity and fulfillment foundation campaign. That would be its
place if the category were internal to the site (D3).

## Open Questions

Each is decided in this change's design session.

### Q1 — Whether the names are an open set, and what a name nobody knows does

D3 documents three names and says they do not close the list. It does not say who may
add a fourth, so every alternative below admits those three and differs in how another
arrives.

- (a) An open set. A pool states any non-empty names, the site and the registry carry
  them opaquely, as offering modes are carried, and D3's three are the ones the
  documentation names. A name no buyer asks for is published and matches no query.
- (b) A vocabulary enumerated in `arkhai_compute`, which gains a name in a release. A
  storefront reports a pool stating a name outside it and holds that pool's listings; the
  registry's schema enumerates the names.
- (c) Open at the site and the storefront, enumerated where a registry chooses to: the
  compute filter specification types the published field as a string and may list the
  names it admits, as it lists GPU models, and a registry's operator edits that list.

Recommended: (c). It is how `gpu_model` is governed, it leaves a seller free to state a
class the documentation has not met, and a registry that wants a curated vocabulary has
one. It would move to (b) if a category came to change admission or pricing, since a
name with behaviour needs one owner.

### Q2 — Which category a listing takes when its pool states more than one

```yaml
policy_tags:
  deliverable_modes: [vm]
  advertisable_modes: [vm]
  capacity_backing: backed
  categories: [compute.gpu, compute.cpu]
  listing_shapes:
    vm:
      - {gpu: {count: 1, model: H100}, memory: {gib: 64}}
      - {cpu: {count: 8}, memory: {gib: 32}}
```

D3 bears on this without deciding it: no category is derived from a shape and no listing
is withheld for its shape, so only a statement by the seller can choose among several.
What is open is where the seller makes it.

- (a) Ruled out by D3. Derived from the shape: a shape that names the `gpu` family is
  `compute.gpu`, any other `compute.cpu`, and a listing is published only where its pool
  states the category its shape derives. It derives a category from a shape, withholds a
  listing whose shape does not fit, and can never yield `compute.db`.
- (b) Stated on each listing shape, beside its families: `{category: compute.cpu, cpu:
  {count: 8}, memory: {gib: 32}}`. It reaches any name and changes the listing-shape
  form that pool hints and storefront overrides share. A listing with nowhere to state
  one, which is bare metal's derived shape and the VM default, takes its pool's category
  where the pool states exactly one and publishes none where it states several.
- (c) A pool states at most one category and every listing of it takes that one. A
  seller cannot then label part of a pool's supply for GPU-heavy work and part for
  CPU-heavy work; a host belongs to one pool, so a GPU host's spare vCPUs and memory are
  sold under that pool's one label.
- (d) Every listing of a pool takes every category the pool states, and the published
  field is a list. A query for any of them finds the listing. D4 has a deal in one
  category, so the claim then needs a rule for which one it names.

Recommended: (b). It reaches any name, it lets one pool hold supply under more than one
label, which a pool of GPU hosts that also sells its spare vCPUs for CPU-heavy work
needs, and it gives bare metal and the VM default a category without a form of their
own. It would move to (c) if one label for a pool's whole supply is enough for sellers,
which is the smaller change and leaves the listing-shape form alone; and to (d) if a
category stated on a pool is meant to reach each of that pool's listings whole.

### Q3 — What a declaration's `resource_type` does in a pool that states categories

D4 keeps today's equality between a claim's type and a declaration's for a pool that
states no category. D3 bears on the rest without deciding it. (b) and (c) below compare
type strings, not shapes, so D3 does not rule them out; but D3 gives a category one
effect, reaching the listing for a buyer to filter by, and (b) and (c) give it a second,
deciding which machines may serve a deal. For a pool that states a category:

- (a) Nothing. The site matches the claim's category against the pool's statement and
  does not compare the declaration's type, at admission and at scheduling alike. A
  declaration typed `compute.gpu` in a pool stating `compute.cpu` serves `compute.cpu`
  claims, and the declaration's field is a label an operator may leave as written.
- (b) Both. The pool must state the category and the declaration's type must equal it. An
  operator retypes each declaration to adopt a category, and a GPU host typed
  `compute.gpu` cannot serve a `compute.cpu` claim, which is what D4 keeps available.
- (c) The pool's statement governs matching, and registration refuses a declaration
  whose type is not among its pool's categories.

A claim and the reservation it makes, under (a):

```yaml
# the claim for the second listing of Q2's pool, sold as `compute.cpu`
{resource_type: compute.cpu, offering_mode: vm, pool_id: vm-california,
 dimensions: {vcpu_count: 8, ram_gb: 32}}
# what the site records
{offering_mode: vm, category: compute.cpu, dimensions: {vcpu_count: 8, ram_gb: 32},
 claim_attributes: {pool_id: vm-california}}
```

Recommended: (a). It is the only alternative under which adopting a category edits a
pool and nothing else. Under it, a declaration retyped while reservations stand against
it changes nothing in a pool that states categories, so the missing guard matters only in
a pool that states none, where the released behaviour stands. Under (b) the retype needs
the refusal a pool move has.

### Q4 — What the category is called on each surface

- **The pool tag.** `categories`, a list of unique non-empty strings, validated as
  `deliverable_modes` is.
- **The claim.** (a) The claim's existing `resource_type` carries the category, so a
  claim written by a `marketplace-v0.4.0` storefront reads as category `compute.gpu` with
  nothing translated. (b) A new `category` key beside `resource_type`, which leaves two
  keys saying nearly the same thing on one claim.
- **The published listing field and its filter.** Not `resource_type`: on a listing
  resource payload that key already says whether the payload is compute or a token.
  (a) `category`; (b) `compute_category`; (c) `resource_category`. It holds one name, or
  a list if Q2 settles on (d).
- **Scheduling.** The cursor's key stays `resource_kind`, and holds the category.

A listing and a query, under (a) of each:

```yaml
listing_resource:
  offering_mode: vm
  capacity_backing: backed
  category: compute.cpu
  region: "California, US"
  vcpu_count: 8
  ram_gb: 32
```

```sh
market listing list --resource 'category=compute.cpu vcpu_count>=8'
```

Recommended: `categories` on the pool, `resource_type` kept on the claim, and `category`
on the listing. The compute filter specification is the compute family's own, so the
short name is not ambiguous there.

### Q5 — Bare metal

Both domains state, carry and publish a category by the same rule (D4), and a released
bare-metal declaration keeps working as written. What is open is the string
`compute.bare-metal`.

- (a) The dependence is removed. Scheduling a reservation that pins its resource does not
  filter by kind, and the bare-metal storefront neither sends a kind nor checks the one
  that comes back. A declaration typed `compute.bare-metal` is scheduled as before and
  the string is a label. The scheduling request, today and under (a):

  ```yaml
  {capacity_reservation_id: 0193a1c2, market: bare_metal,
   requirements: {resource_kind: compute.bare-metal}, resource_id: host-ca-h200-01}
  {capacity_reservation_id: 0193a1c2, market: bare_metal, resource_id: host-ca-h200-01}
  ```

- (b) Bare-metal declarations are retyped to a category their pool states and the
  storefront sends that. A declaration has no category of its own to take, since none is
  derived from a machine's shape (D3), so the name is copied from the pool. Every operator
  edits every bare-metal declaration, and a deal reserved before the edit and scheduled
  after it finds no candidate.
- (c) The storefront goes on sending and checking `compute.bare-metal` for a pool that
  states no category, and the category for one that does. Two rules in one domain, and
  neither is VM's.

Recommended: (a). The storefront's checks of the provider, the pool, the host and the
physical machine already establish what was scheduled, no operator edits anything, and no
deal in flight is stranded.

### Q6 — The filter, and what a listing that states no category answers

```yaml
- {name: category, path: $.listing_resource.category, op: in, value_type: string, on_missing: fail}
```

- (a) Missing fails, as for `offering_mode` and `capacity_backing`. A listing of a pool
  that states no category is found by no category query, which is what omission means.
  A seller appears in a search for `compute.cpu` once its pool says so.
- (b) Missing passes. Every listing of a `marketplace-v0.4.0` storefront matches every
  category query, which answers a buyer with supply that claimed nothing.
- (c) Ruled out by D3. The storefront publishes the category a shape derives even where
  the pool states none. It derives a category from a shape, and publishes a statement the
  seller did not make.

The missing-value rule is one question for the filter grammar, and one other change
meets it: `filter-listings-by-capacity-bounds`, for a listing that states no bound.
`publish-shape-bounds` adds no filter and takes that change's answer if one over a
constraint is ever added. The evaluator's ordering, which decides a missing value
before an `exists` test, belongs to the same question. The two changes take one answer,
from whichever is designed first.

D3 bears on the `exists` ordering without deciding it. A category selects what sellers
labelled, not the listings that state no GPU field, so the item this change took, that
no filter can select supply that omits a field, is answered only when `exists:false`
matches such a listing. Either the ordering is repaired here, or by
`filter-listings-by-capacity-bounds` with the missing-value rule, or the item returns to
the change index as unowned.

Recommended, subject to that: (a) for the missing-value rule, and the `exists` ordering
repaired by whichever of the two changes settles that rule, since both are the same
evaluator code. If neither takes it, the item returns to the index and D5's third gap
closes by half.

### Q7 — What an operator edits to adopt a category

Provisional text for `docs/operator-handbook.md`, "Pool definitions", assuming Q3 (a):

> A pool may state the categories of compute it sells, as `categories` in `policy_tags`:
> `categories: [compute.cpu]`. A category is a label for the work the supply suits:
> `compute.gpu` for GPU-heavy work, `compute.cpu` for CPU-heavy work, `compute.db` for
> database work, which tends to be bound by disk I/O. Nothing checks a shape against it.
> Its listings then publish their category and buyers can search by it. A pool that
> states none sells as before and its listings publish no category. State a category only
> once the site and every storefront that reads it run a release that knows categories.
> No capacity declaration changes.

Open: whether a pool write refuses a malformed `categories` value, as it refuses a
malformed mode set, or accepts it and leaves the storefront to report it. Recommended:
the write refuses it, by the same shared check, since the site matches on it.

### Q8 — Compatibility with `marketplace-v0.4.0`

What D4 settles, and what each remaining case needs:

| Case | Behaviour |
|---|---|
| A pool written under 0.4.0, stating no category | As released (D4) |
| A 0.4.0 VM storefront, a newer site, a pool stating none | As released: the claim names `compute.gpu` and scheduling uses the default |
| A reservation recorded before the upgrade and scheduled after | Scheduled under the default; its recorded scheduling requirements compare as before |
| A 0.4.0 registry, a newer storefront | The listing schema admits a property it does not name, so the category is stored and no filter reads it |
| A newer registry, a 0.4.0 buyer | A filter added with known types changes only the specification's ETag, which the buyer refetches |
| A newer registry, a 0.4.0 storefront | Its listings state no category; Q6 decides what they answer |
| A 0.4.0 storefront, a newer site, a pool stating a category | Open, below |
| A newer storefront, a 0.4.0 site | Open, below |

- **A storefront older than the pool's statement.** A 0.4.0 VM storefront reads
  `categories` as a tag it does not know, publishes as before and claims `compute.gpu`.
  Against a pool stating only `compute.cpu` the site refuses that claim when the settled
  deal reserves. (a) The operator instruction of Q7 is the whole answer:
  sites and storefronts are upgraded together, and a category is stated last. (b) The
  site also answers a claim that names a category the pool does not state with a refusal
  naming the pool's categories, so the cause is read from the first failure.
- **A storefront newer than its site.** A newer storefront claims the pool's category
  and, under Q5 (a), sends no kind for bare metal; a 0.4.0 site matches the claim
  against the declaration's type and schedules bare metal under its default. (a) The
  contract's rule that a provisioning service and its storefronts are upgraded together
  covers it, with the site first. (b) The compute provisioning contract takes a new
  major, so a newer storefront refuses a 0.4.0 site by version instead of failing a
  deal.
- **Persistence.** The reservation's category is a nullable column added by a migration
  appended to the provisioning chain and to the API-credit service's, which hosts the
  same ledger (`openspec/specs/site-capacity/architecture.md`, "Current limits"). A row
  without it is a reservation in no category.

Recommended: (b) for the first, and (a) for the second unless the schedule request or
response changes shape, which is then a new major by the contract's own rule.

### Q9 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **Requirements this change modifies**, their deltas written once Q1 to Q8 settle:
  `site-capacity`'s "Resource-pool projection metadata", whose last paragraph and
  scenario "A VM declaration without GPUs keeps the VM kind" state the constant, "Reserve
  replay is keyed by the deal's placement" and "Requested offering mode is required and
  bounded by the pool", beside which the category's own requirement sits;
  `resource-pool-management`'s "The pool authority answers the site's pool facts" and
  "Typed pool models validate policy hints", with a requirement for the pool's stated
  categories beside "Pool-declared deliverable offering modes"; `fulfillment`'s
  "Multidimensional eligibility" and "Scheduling and assignment";
  `storefront-publication`'s "A listing's identity is the physical resource it offers",
  "Every VM listing is a listing shape" and "A bare-metal listing's shape is derived from
  its declaration"; `registry-discovery`'s "The compute listing shape does not require
  GPU fields"; `compute-provisioning-contract`'s "Fulfillment scheduling and acceptance"
  only if Q5 or Q8 changes the request or the response. No `negotiation-protocol` or
  `cli-query-language` requirement changes unless Q6 changes the grammar.
- **Companion text.** `openspec/specs/storefront-publication/architecture.md`, "Listing
  shapes and the storefront's authority", restates why a CPU-only shape may land on a GPU
  host as the pool's choice; the `site-capacity` companion gains why the pool, and not
  the declaration, states the category.
- **`resource_type` and `resource_kind`.** The site and the claim say type; fulfillment
  and the provisioning contract say kind. Both stay, as
  `docs/development/ARCHITECTURE.md`, "One name per concept", names them one
  discriminator.
- **Test levels.** Matching and scheduling are library integration in `kit/site` and
  `kit/fulfillment`; the pool fact is the pool kit's own suite; each storefront proves
  publication and the claim at application integration through its typed clients; the
  filter is registry application integration; a category search and purchase runs in
  the VM lane, beside its deal without GPUs, and a bare-metal deal in a pool that states
  a category runs in the bare-metal lane, both on mock provisioning. One storefront test
  publishes and sells a shape that states GPUs under `compute.cpu`, which shows no party
  checks a shape against a category (D3).
- **Hardware.** Nothing here needs a GPU, and nothing touches the Ansible layer or how
  an adapter executes it, so no real-host run is owed.
- **Documents.** Both seller quickstarts and the operator handbook's pool and capacity
  definitions, which say what each documented category is for and that it constrains no
  shape; `docs/buyer-quickstart.md` for the search and the same three names.

### Q10 — Implementation cadence

Recommended: two rounds. First the site half: the pool's statement and the pool fact,
the claim's category at admission, the reservation's record, scheduling by it, and bare
metal's scheduling, with their kit and application integration tests, one session. Then
the market half: both storefronts' claims and publication, the registry field and
filter, the buyer's query, the lane rows and the documents, one session.

## Verification

Provisional levels are in Q9. Every lane row is mock-provisioning evidence.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 one meaning for the resource type in both compute domains | `openspec/specs/site-capacity/spec.md` and `architecture.md`; `docs/development/ARCHITECTURE.md`, "One name per concept" |
| D2 the flat dimension names stand | `openspec/specs/market-composition/architecture.md`, "The compute family vocabulary" |
| D3 a seller's label for the work supply suits, published and filterable, constraining no shape; `compute.gpu`, `compute.cpu` and `compute.db` documented | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/registry-discovery/spec.md`; `docs/operator-handbook.md`, "Pool definitions"; `docs/buyer-quickstart.md` |
| D4 the pool states it; the claim, the reservation and scheduling carry it | `openspec/specs/resource-pool-management/spec.md`; `openspec/specs/site-capacity/spec.md` and `architecture.md`; `openspec/specs/fulfillment/spec.md`; `docs/operator-handbook.md`, "Pool definitions" |
| D5 the change is Goal 2's | `docs/development/ROADMAP.md`, Goal 2 |
