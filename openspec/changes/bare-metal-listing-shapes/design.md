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
- VM's pool-override HTTP routes, admin-identity binding, command-line group,
  migration composition, and status live in the VM storefront. The kit supplies the store,
  service, signed-resource contract, and typed client. `PoolOverrideService`
  expects a cached projection source and a publication loop to wake. Bare-metal
  publication holds neither between its operator-invoked runs.
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
so an operator is not misled into thinking it applies. The pool-overrides
contribution refuses `listing_shapes` for the same reason.

### Bare metal joins the override store through a kit route service

Bare metal contributes a `PoolOverrideContribution` for `bare_metal`:

- **Vocabulary.** Settlement clauses and the terms `min_duration_seconds` and
  `max_duration_seconds`. The asking rate and hold rate join the same record through
  the changes that define them.
- **Shapes.** Any stated `listing_shapes` is refused, and `judge_shapes` returns
  nothing.

Precedence is override, then configuration. An override's clauses replace the
configured `BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES` for that site's pool as a
whole. Its duration bounds replace the configured maximum and the default of no
minimum. Region and backing remain the site's.

The HTTP surface moves into `kit/pool-overrides` as a framework-free route service,
`PoolOverrideRouteService`:

- `replace(body)`, `read(query)`, and `delete(query)` return the kit's response
  models and raise `PoolOverrideRefused` with its status.
- The contract failures, get-versus-list dispatch, and 404 for a missing read move
  there from VM's controller.
- VM's admin controller and bare metal's `api.py` each become a thin FastAPI
  binding. Each authenticates with the kit's `pool_override_contract`, through VM's
  middleware and bare metal's `_admin` respectively.

This follows the precedent the review cited: `kit/contact-exchange`'s
`IntroductionRouteService` is framework-free, and each storefront binds it. A FastAPI
router inside the kit would add a web-framework dependency no storefront-side kit
carries today. It would also bind a routing decision that `kit-owned-storefront-shell`
will make for every shared route at once. This refines the review's "router in the
kit": the logic moves out of VM rather than being copied, and the binding stays with
each storefront until the shell owns it.

Status for bare metal is judged against the last generation each site's publication
run accepted, which the runtime keeps in memory. A site with no accepted generation
since startup is `unknown`. This is the store's existing meaning for a site whose
projection is not held, so nothing is called `orphaned` on an answer the storefront
does not have.

After an accepted write, bare metal has no cache to refresh and no loop to wake. The
write takes effect at the next operator-invoked publication run. The shared
requirement therefore makes those two effects conditional on a storefront that has
them.

### Bare metal gains a `pool-override` command in the same layering

`bare-metal-storefront pool-override` offers `set --file`, `get`, `list`, and
`delete`, with `--mode` never defaulted. It follows the same layering as the routes:

- The kit's `SyncPoolOverrideClient` does the work, over the canonical storefront
  client's authenticated transport. The bare-metal storefront already depends on it.
- The Typer layer is copied from VM's `market_storefront/groups/pool_overrides.py`
  into the bare-metal storefront rather than imported, because bare metal may not
  import the VM storefront. It is copied unchanged, including the infeasible-shape
  warning. That warning never fires for bare metal, since a bare-metal override states
  no shapes, but keeping the two copies identical makes folding them one mechanical
  step when the compute-family storefronts converge.

The command calls the storefront's administrator API and never opens its database,
as VM's does. Bare metal's `publish` and `redeliver-introduction` commands run
in-process against the storefront's database. An override write is different: it must
pass the running storefront's live-site check, and it must be authenticated as an
administrator like any other write to it.

The command signs as the storefront's own marketplace signer, resolved from the same
`BARE_METAL_STOREFRONT_IDENTITY_*` and `ARKHAI_IDENTITY_CREDENTIAL` inputs the server
reads. It pins that signer as the expected responder. As with VM, the signer must
appear in `BARE_METAL_STOREFRONT_ADMIN_IDENTITIES` for the command to act.

The storefront URL is `--storefront-url`, else `BARE_METAL_STOREFRONT_PUBLIC_URL`,
else `http://localhost:8000`, which is the `serve` default. The small admin-session
helper this needs lives beside the command in the bare-metal storefront. It is
bare-metal configuration, not shared logic.

### A minimal seller inventory guard at opening

`storefront-publication` requires seller policy to recheck every published field
sourced from a declaration or pool before agreeing terms. Bare metal has no such check
today. This change publishes declaration-sourced shape fields and a pool-sourced
region, so it adds the minimum at opening, on both the Alkahest and hosted paths:

1. Fetch the listing's own site's resource-pool projection through that site's
   trusted client.
2. Find the bound Physical Resource under the bound pool.
3. Re-derive its shape and region, and compare the shape digest with the binding's
   recorded digest and the region with the published region.

A mismatch, a missing resource, or a disabled declaration is refused with a
declared-match reason, distinct from any availability reason. An unreachable site is
refused as retryable.

The guard deliberately stays this small. `bare-metal-and-credits-domain-stacks` 4a
re-homes bare metal's opening validation onto the kit negotiation runtime's
`validate_opening` hook, and this check moves with it.

### Test fixtures follow the real path

The bare-metal publication-view fixture moves `gpu_model` out of the view's
`capabilities` into the containing resource's declared `attributes`, and declares
`units: 1` beside hardware quantities. Tests then exercise the path a site actually
serves.

## Open questions

None.
