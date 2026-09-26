# Design — bare-metal listing shapes

## Context

Found while designing `publish-indicative-listing-rates`, whose asking rate is
declared per capability shape and so has no key on bare metal. Investigating that
showed a larger gap: bare-metal listings nest their hardware under
`listing_resource.capabilities`, so the compute schema's top-level dimension filters
never match them.

What the code does today:

- `available_bare_metal_listings` builds each `BareMetalListing` from one Physical
  Resource's `bare_metal.v2` publication view, merging its `capacity` and
  `capabilities` into one nested `capabilities` mapping. `BareMetalListing` has no
  `gpu_model` or `region` field, and its `site` labels are never populated by
  publication. The registry does not enforce its full listing shape at publish, so
  these listings store successfully and then match no dimension filter.
- A bare-metal declaration's `capacity` is the whole-machine count `{"units": 1}`,
  and both reservation paths (`fulfillment_service.py`, `hosted_lifecycle.py`) claim
  `dimensions: {"units": 1}`. The hardware a seller advertises lives in
  `attributes.bare_metal_publication.capabilities`, an operator-authored map the site
  copies into the view unchecked. It is not a declared attribute and nothing admits
  against it.
- The site's `bare_metal.v2` view copies the declaration's `capacity` but not its
  `attributes`. The projected resource that contains the view carries both.
- The derivation key is `(site, offering mode, domain binding, pool,
  physical_resource_id)` (`sqlite_client.bare_metal_derivation_key`), and
  `compare_bare_metal_listing` treats `capabilities` and `site` as identity fields.
- `VM_CAPABILITY_SCHEMA` lives in `arkhai_vms.compute_requirements`, and the
  bare-metal storefront's import-boundary test forbids importing `arkhai_vms`.
  `kit/capability-shape` states that it knows no family or field name.
- Region is a pool hint read by `market_resource_pools.hints.raw_region`, with no
  trust gate. VM resolves it through `resolve_region`; only SLA is trust-gated.
- The bare-metal storefront has no seller inventory guard: opening validation checks
  duration and access method against the stored listing, not its declaration.

### Direction

The bare-metal and VM storefronts are expected to merge into one compute-family
storefront, as the compute provisioning service already serves both domains. That
merge depends on Goal 4's shell work (`bare-metal-and-credits-domain-stacks`,
`kit-owned-storefront-shell`). Every decision here is taken in its light. What the
two domains share goes to one owner now rather than being copied and reconciled
later. Anything bare metal must add locally is kept thin enough to re-home.

## Decisions

### The compute-family capability schema gets one home: `domains/compute`

A new domain package, `domains/compute` (distribution `arkhai-compute`, import
`arkhai_compute`), holds the compute-family capability schema. It depends on the
standard library and `kit/capability-shape` only. The schema,
`COMPUTE_CAPABILITY_SCHEMA`, holds the families `gpu`, `cpu`, `memory`, and
`storage`, the flat dimension constants, and `gpu_model`. `arkhai_vms` re-exports it
as `VM_CAPABILITY_SCHEMA` and keeps its existing names, so no VM caller changes.

Alternatives rejected:

- **`kit/capability-shape`.** Market-neutral by rule. A named compute vocabulary
  there would make the foundation kit know families.
- **`market_core`.** The market-neutral carrier, which holds no compute vocabulary.
- **A bare-metal schema producing the same flat names.** Two schemas agreeing by
  coincidence are a divergence waiting to happen. This is the choice the design
  already rejected.
- **Importing `arkhai_vms` from bare metal.** Forbidden by the import boundary, and
  wrong in principle: the vocabulary is the compute family's, not VM's.

This is the first piece of the compute-family convergence. It is also the one place
`settle-capacity-claim-vocabulary`'s flat-spelling gate (its task 2.1) later edits,
renaming both domains in one step. This change uses today's spellings: `gpu_count`,
`gpu_model`, `vcpu_count`, `ram_gb`, `disk_gb`. The bare-metal import-boundary test
admits `arkhai_compute` as a domain-neutral compute contract; it is not a VM import.

### `kit/capability-shape` gains a schema-driven inverse of flattening

`unflatten_shape(quantities, attributes, schema)` builds the family-grouped shape
from flat names through a schema. It reports every flat name the schema does not
define, and every problem `shape_problems` would find, including a missing required
field. It is the exact inverse of `flatten_shape`, is market-neutral, and knows no
family, so it belongs beside `flatten_shape`. A bare-metal shape is derived by this
function. A family-grouped digest of a derived shape therefore equals the digest of
the same shape stated by hand. That equality is what makes asking-rate keys and
override comparisons work across stated, generated, and derived shapes.

### The shape is derived from the declaration, never from publication-only data

A bare-metal listing's shape is its Physical Resource's capacity declaration read
through the compute schema:

- **Quantities.** Every declared `capacity` key other than `units` must be a compute
  schema quantity.
- **Attributes.** The compute schema's attribute names (`gpu_model`) are read from the
  declaration's `attributes`, taken from the projected resource that contains the
  view (as `enabled` already is), so the site does not change. Other declared
  attributes, such as `physical_host_id`, `allocation_mode`, and
  `bare_metal_publication`, are site accounting and publication configuration, not
  shape input, and are ignored.
- **`units` is excluded by name.** It is the whole-machine count, not hardware.

A declaration that cannot be read this way is unresolvable. It yields no new listing,
its existing listing is held, and the run reports it by name. This is the rule
`storefront-publication` already applies to a malformed declaration. It covers:

- a capacity key outside the schema;
- a non-positive or non-integer quantity;
- a missing `gpu.count` or `gpu.model` (the compute schema requires the `gpu`
  family, as the compute registry schema requires `gpu_model`);
- a `units` other than exactly 1.

A GPU-less machine therefore cannot publish into the compute schema. That limit is
the registry schema's, not this change's.

Requiring `units` of exactly 1 turns a latent failure into a reported one. A
declaration without it would publish a listing that no bare-metal claim could ever
reserve.

`attributes.bare_metal_publication.capabilities` is retired. It is unchecked,
publication-only data, and a shape sourced from it would be descriptive rather than
declared. `bare_metal_publication` keeps `enabled` and `access_methods`. A site's
declaration that still carries `capabilities` has it ignored and reported, so an
operator is not misled into thinking it publishes.

The seller-facing contract is the one the capacity-definitions documentation already
states: every declared attribute is published to storefronts and claims match them.
Hardware now goes where admission can see it:
`capacity: {units: 1, gpu_count: 8, ram_gb: 2048, ...}` and
`attributes: {gpu_model: H200, ...}`.

### The whole machine is one unit; its dimensions describe that unit

A bare-metal listing is held by exclusive allocation of one unit. The claim continues
to request `dimensions: {"units": 1}` and names its Physical Resource, or its pool
where hosted selection is fungible. Its shape's quantities describe what that one unit
contains. They are not reserved dimension by dimension.

This is why a bare-metal listing has no shape to negotiate. It is also why VM's
commitment rule ("the claim requests exactly its shape's quantities") does not carry
over. The whole unit is the commitment, and exclusivity holds everything the unit
contains.

The claim additionally carries the shape's attributes (`gpu_model`) beside
`units: 1`, so site admission equality-matches the model the listing published. The
shape is then enforced at admission and is not merely descriptive. The value comes
from the storefront's trusted listing record for the accepted listing, never from
buyer input. A declaration whose model changed after publication is refused at
reservation, as VM's is.

### Derivation identity: the resource anchors it, the shape completes it

This amends the earlier "Identity stays the Physical Resource" decision, which could
not hold alongside the decisions below.

A bare-metal listing's derivation source identity is `(pool, physical_resource_id,
shape_digest)` under the site and domain binding. The digest is taken over the
family-grouped form by `kit/capability-shape`'s `shape_digest`, and the binding
records it in the source envelope. The Physical Resource still anchors the listing:

- one resource holds one declaration at a time, so it derives exactly one listing;
- two resources declaring identical dimensions derive two listings with equal shapes
  and distinct keys.

The digest is what makes a corrected declaration a close-and-successor. The existing
listing-identity requirement already provides for this: "where the listing's
derivation identity captures the changed field, the existing listing closes and a
newly derived listing is published." Without the digest, the same requirement's other
branch applies instead. The listing closes and never reopens while its published value
differs, and because the key is unchanged no successor can bind. A corrected
declaration would delist its machine permanently.

This matches VM's "derivation identity includes its shape" requirement.

Region stays outside derivation identity, as it does for VM. A changed pool region
follows the listing-identity requirement's other branch: the listing closes and does
not reopen while its region differs. This change neither adds nor alters that
behaviour.

### Existing listings are replaced once, with no special code

This refines "Existing listings are closed and republished once."

Existing listings' keys carry no digest, so after upgrade they match no classified
resource. Source reconciliation closes each as `source_gone`, and its successor
publishes under a shape-bearing key in the same run. No listing is reopened, so this
does not rest on any reopen rule. Seller close and pause are not carried to
successors, as VM's upgrade does, because bare metal is not deployed and there is no
seller state to carry.

### The nested `capabilities` mapping and the `site` labels are retired

The listing publishes its shape as top-level `listing_resource` fields under the
compute family's wire names. The nested form is not published beside them.

`site` is dropped from `BareMetalListing`: publication never populates it, and region
now has its own field. Both leave `compare_bare_metal_listing`'s identity fields.
`gpu_count`, the other shape quantities, `gpu_model`, and `region` join them. There is
no deployed buyer to keep compatible, and the bare-metal buyer in this repository
reads neither field.

Considered and rejected: publishing a whole host's hardware under the filter-spec's
`host_*` and `total_gpu_count` fields. Those describe the host a VM slice sits on. A
bare-metal buyer receives the whole host's GPUs, so `gpu_count >= 8` must find an
8-GPU machine.

### Region comes from the pool hint; no hint holds the pool

A bare-metal listing publishes `region` from its pool's `region` policy tag through
`market_resource_pools.hints.raw_region`, under the same non-empty-string rule VM's
`resolve_region` applies. This is the same hint VM reads, since region is a site fact
declared on the pool.

A pool with no usable region hint is held: its resources yield no new listing, its
existing listings are neither closed nor refreshed, and the run reports the pool by
name. The compute registry schema requires `region`, and bare metal has no legacy
fallback to substitute.

A region the declaration also states is not compared here. A bare-metal claim names
its resource, and the site has no bare-metal region-matching rule to align.

### Bare metal does not read `listing_shapes` hints

A bare-metal seller sells a whole machine, so there is no shape to choose. A pool
that states `listing_shapes` for `bare_metal` has it ignored, and the run reports it
so an operator is not misled into thinking it applies.

### The opening guard is a domain function the storefront calls

`storefront-publication` requires seller policy to recheck every published field
sourced from a declaration or pool before agreeing terms. Bare metal has no such check
today. This change publishes declaration-sourced shape fields and a pool-sourced
region, so it adds the check at opening, on both the Alkahest and hosted paths.

The substance is a pure function in `arkhai_bare_metal`. It takes:

- an accepted site generation;
- the pool regions the storefront resolved;
- the listing's binding facts: pool, Physical Resource, shape digest, and published
  region.

It classifies the generation with `classify_bare_metal_resources` and returns one of:

- **match** — the bound resource is a candidate or unavailable, with an equal digest
  and region;
- **declared mismatch** — the digest or region differs, or the resource is held for
  an unreadable declaration;
- **absent** — the resource is missing, withdrawn, or its pool no longer admits bare
  metal.

Publication and the guard therefore read declarations through one code path, which is
what "the inventory guard checks a listing against its own source" asks for.

The storefront does only the transport around it:

1. fetch the bound site's live projection through that site's trusted client;
2. resolve pool regions;
3. call the function;
4. refuse a mismatch or absence with 409 and a declared-match reason, and an
   unreachable or unverified site with 503.

It checks declaration, not availability. An availability check at opening is outside
this change.

A storefront with no trusted site authority composed cannot confirm any listing, so
it refuses every opening as retryable. A bare-metal storefront therefore refuses a
negotiation it could never admit. This matches the VM storefront, whose negotiation
already depends on its sites, and was accepted when the implementation surfaced it.

**Sequencing with `bare-metal-and-credits-domain-stacks` §4a.** §4a re-homes bare
metal's opening validation onto the kit negotiation runtime's `validate_opening` hook
and has not started. This change lands first. §4a then calls the same domain function
from the hook and moves only the fetch and the status mapping. That change's design
carries a note saying so.

Revisit trigger: §4a starting before this change completes. The guard would then be
written against the hook directly rather than the current negotiation service.

### Test fixtures follow the real path

The bare-metal publication-view fixture moves `gpu_model` out of the view's
`capabilities` into the containing resource's declared `attributes`, and declares
`units: 1` beside hardware quantities. Tests then exercise the path a site actually
serves.

### Joining the override store moved to `publish-indicative-listing-rates`

An earlier version of this design also joined bare metal to the site-scoped
pool-override store. That work extracted VM's override HTTP handling into a kit route
service and added bare-metal routes, status, and a command. Design review moved it
out, for three reasons:

- nothing in making a bare-metal listing a discoverable shape depends on it;
- extracting live VM HTTP behaviour added regression surface this change does not
  need;
- this change is on Goal 7's critical path, and it reaches review sooner without it.

It is too small to be a change of its own. `publish-indicative-listing-rates` is its
first consumer, because the storefront's final authority over an asking rate needs a
storefront tier on bare metal. It therefore owns the work, with the decisions reached
here recorded in its design: the vocabulary, the framework-free route service,
conditional after-write effects, a durable record of accepted generations for status,
a thin command, and no contribution in the combined shell.

Code already written for it in this change's working tree (the kit route service and
VM's rebinding) was reverted rather than carried, so this change touches neither
`kit/pool-overrides` nor VM's admin controller.

## Decisions taken while planning

Planning named every file each decision touches. Doing so settled the following
points, which the decisions above left to implementation.

### The payload kind stays `bare_metal.v2`

`BARE_METAL_SCHEMA_KIND` is shared by every bare-metal payload: listings, messages,
terms, materializations, receipts, and access results. Bumping it for a listing-only
change would churn all of them and the evidence built on them. Nothing is deployed,
so no stored or published listing needs a new kind to be told apart.

`BareMetalListing` gains required fields, and the kind is unchanged.

### `BareMetalListing` names the schema's flat fields explicitly

The listing model declares:

- `gpu_count` and `gpu_model`, required;
- `vcpu_count`, `ram_gb`, and `disk_gb`, optional;
- `region`, required.

It does not accept arbitrary extra fields. A test asserts that the model's shape
fields equal `COMPUTE_CAPABILITY_SCHEMA`'s flat names. The schema's single home, and
the spelling gate's later rename, then cannot drift from the listing silently.

### The binding's source envelope gains a version

The binding's source envelope moves to `bare_metal.resource-projection.v1` schema
version 2, carrying `shape_digest`. Readers accept version 1 only as an old key that
matches no candidate, which is what closes it.

### Reconciliation matches bindings by resource before key

A resource whose declaration is unresolvable has no shape, and so no key.
Reconciliation therefore finds each open binding's resource by its recorded site,
pool, and Physical Resource first:

1. **Held.** A held resource, or a held pool, leaves the binding untouched.
2. **Candidate.** A candidate whose key equals the binding's is left to publication.
3. **Unavailable.** An unavailable resource whose key equals the binding's closes for
   availability.
4. **Anything else.** A different key (a changed shape, or a version 1 envelope), or a
   withdrawn resource, closes as `source_gone`.

### The bare-metal buyer gains `list --resource`

"A buyer filtering by GPU model finds a bare-metal listing" is only true for this
repository's bare-metal buyer if it can filter. Today `bare-metal list` takes none.

It gains `--resource`, compiled through
`registry_client.query.compile_resource_query` against the registry's filter
specification, as the VM buyer does. This is the shared query grammar, not a new one.

### Bare-metal storefront tests keep their flat layout

`domains/bare_metal/storefront/tests/` is not split into `unit/` and `integration/`.
Restructuring it is outside this change, so new tests join the flat directory,
named by the seam they prove.

## Design review corrections

- **The VM commitment is scoped to VM.** The modified "Every VM listing is a listing
  shape" requirement had widened its opening sentence to mention bare-metal shapes.
  Its Commitment paragraph still said a listing's claim "MUST request exactly its
  shape's quantities", which read as a second, contradictory rule for bare metal.
  The Commitment and VM-default paragraphs now say "VM listing" and "VM pool"
  throughout, and point to the bare-metal whole-unit requirement as the other
  commitment model. `ARCHITECTURE.md`'s "Storefront capacity boundary" carries the
  same sentence and is scoped the same way at promotion.

## Decisions taken during implementation review

- **Negotiation routes verify the body the caller sent.** A signature is
  checked against the request's own body, never a re-serialized model, which may
  drop an explicit `null` a conforming client signed.
- **Negotiation reads are the administrator's.** A listing's threads carry buyer
  principals and agreed terms. Bare metal served them anonymously and unsigned; it
  now serves them only through the administrator's signed contract, as VM does and
  as the canonical client expects. The list's query is bound into the signed
  resource, and any other or repeated parameter is refused.

## Open questions

None.

## E2E debug follow-up

The branch still pins storefront-client 0.20.0 in both storefront locks after
the client moved to 0.21.0. Re-resolve those consumers with a targeted package
upgrade against freshly built internal wheels. Retaining old wheels would hide
the clean-build failure; broad dependency upgrades would add unrelated changes.
This restores the existing wheel packaging contract in
`docs/development/ARCHITECTURE.md#build-packaging-and-initialization` and requires
no new permanent design. Further fixes depend on failures observed through
`make run-e2e` and `make fetch-e2e-logs`.

The next run reached the bare-metal scenarios: seven passed, and hardware
discovery failed because the scenario read `ListingSummary.listing_id`.
The registry list client exposes `id`; the detail client exposes `listing_id`.
Use the existing list model in the scenario without changing either API. The
positive and negative hardware-filter assertions remain the validation boundary.
