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

## Open questions

- **Which capability schema.** Whether bare metal binds the VM capability schema —
  the compute family's form factors share one registry schema identity — or its own
  schema whose fields map to the same wire names. Decide before planning.
- **Existing listings.** A published bare-metal listing did not publish the new
  top-level fields; under the listing-identity requirement, a newly published
  identity field is neither added to an existing listing nor a reason to close it. So
  existing listings would stay invisible to dimension filters until they next close.
  Whether to accept that or close and republish each once, as VM's upgrade to listing
  shapes did, is undecided.
- **Whether `capabilities` stays published** beside the top-level fields for
  compatibility with existing bare-metal buyers, and for how long.
- **Which override fields bare metal accepts.** Whether an override may state
  settlement clauses and terms only, given there is no shape choice to override.
