# Design — bare-metal listing shapes

## Context

Found while designing `publish-indicative-listing-rates`, whose asking rate is
declared per capability shape and so has no key on bare metal. Investigating that
showed a larger gap: bare-metal listings nest their hardware under
`listing_resource.capabilities`, so the compute schema's top-level dimension filters
never match them.

`available_bare_metal_listings` builds each `BareMetalListing` from one Physical
Resource's publication view, merging its `capacity` and `capabilities` into one
`capabilities` mapping. `BareMetalListing` has no `gpu_model` or `region` field. The
registry does not enforce its full listing shape at publish, so these listings
publish and store successfully and then match no dimension filter.

## Decisions

### One shape per Physical Resource, matching it exactly

Each bare-metal listing's shape is its Physical Resource's declared dimensions,
expressed as a family-grouped capability shape. It is derived rather than stated: a
bare-metal seller sells a whole machine, so there is no choice of shape to make.

This reuses `kit/capability-shape` rather than giving bare metal a parallel
vocabulary. It is also the step that would let a pool whose Physical Resources all
share one shape eventually publish a fungible listing, without that being a goal
here.

### Identity stays the Physical Resource

A bare-metal listing's derivation identity remains its site and Physical Resource.
Its shape is a function of that resource's declaration, so it adds no information
to identity; a change to the resource's declared dimensions is an identity change
under the existing listing-identity requirement and is handled by it.

### Joining the override store rather than adding a bare-metal tier

`kit/pool-overrides` is market-neutral and each market contributes its vocabulary
per offering mode. Bare metal contributes one for `bare_metal` rather than
introducing its own storefront-override mechanism.

### Bare metal binds the compute-family capability schema

Bare metal binds the same capability schema VM uses — the families `gpu`, `cpu`,
`memory`, and `storage`, extended with any family bare metal needs — rather than a
bare-metal schema whose fields map to the same wire names. The compute family shares
one registry schema identity, its flat dimension spelling is one decision taken for
both domains (`settle-capacity-claim-vocabulary`), and the two domains converge on
one storefront over time; two schemas producing the same flat names would be a
divergence that later has to be undone.

### Existing listings are closed and republished once

Bare metal is not deployed, so no published listing has buyers holding its reference.
Every bare-metal listing is closed and republished with its shape once, as VM's
upgrade to listing shapes did, rather than left invisible to dimension filters until
it next closes.

### The nested `capabilities` mapping is retired

The top-level shape fields replace `listing_resource.capabilities`; the nested form
is not published beside them. There is no deployed buyer to keep compatible, the
bare-metal buyer in this repository is updated with the storefront, and publishing
both would keep two spellings of one shape alive from the first release.

### Overrides state settlement clauses and terms only

A whole machine has no shape to choose, so the bare-metal override vocabulary is
settlement clauses and commercial terms. The asking rate and the hold rate join the
same record through the changes that define them.

## Open questions

None.
