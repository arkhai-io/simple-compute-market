# Design

## Context

- `capacity-shape-envelope` resolves, per pool and offering mode, a shape bounds
  declaration from the storefront's override, the pool's `shape_bounds` hint, and the
  storefront's configured default. A declaration holds named constraint sections; only
  `bounds` (family-nested `{min, max}` per quantity field) exists, and later forms such
  as `ratios` relate two dimensions. Only `kit/capability-admissibility` interprets a
  declaration; it is a foundation kit buyers can depend on.
- A published VM listing's `listing_resource` is its commitment, in flat claim names
  (`gpu_count`, `ram_gb`), and is copied into the settlement order at acceptance. It
  also carries `asking_rate`, a term of sale, by precedent.
- The registry stores six top-level carriers and silently discards any other top-level
  field; `listing_resource` is open and stored. `store-registry-listings-as-published`
  is deciding between storing the listing as published and admitting only named
  carriers.
- `settle-capacity-claim-vocabulary` may rename the flat dimension names; whether round 0
  adopts the family form is its question.

## Decisions taken in `capacity-shape-envelope`'s design

- **What is disclosed:** the resolved declaration for the listing's pool and mode, not
  the raw tiers. A buyer evaluates it through the admissibility kit; a buyer whose kit
  does not know a section treats the region as unknown and relies on refusals.
- **Which listings:** VM only.
- **Filtering:** decided with the carrier.
- **Sensitivity:** hardware bounds are not sensitive and buyers should be able to
  discover them, so this is not tied to the rate structure's carrier decision.

## Open Questions

- **How a listing represents its base offering and admissible region.** A listing has a
  base value per dimension, a range around it, and later ratios between two dimensions.
  Two forms were considered and found unsatisfactory:

  ```yaml
  # inside the commitment: two vocabularies in one object, and copied into the deal
  listing_resource:
    gpu_count: 2
    ram_gb: 128
    shape_bounds:
      bounds:
        gpu:    { count: { min: 1, max: 8 } }
        memory: { gib:   { max: 512 } }
  ```

  ```yaml
  # a separate top-level term: clean separation, but the range sits far from its base
  listing_resource:
    gpu_count: 2
    ram_gb: 128
  shape_bounds:
    bounds:
      gpu:    { count: { min: 1, max: 8 } }
      memory: { gib:   { max: 512 } }
  ```

  The range should read in line with the base value. One starting sketch:

  ```yaml
  shape:
    gpu:    { model: H100, count: 2, range: [1, 8] }
    memory: { gib: 128, range: [null, 512] }
  ratios:
    - { of: memory.gib, per: gpu.count, range: [32, 64] }
  ```

  Whatever is chosen must keep the commitment the claim is built from unambiguous,
  translate exactly to and from the declaration the kit evaluates, and fit the registry
  carrier policy and the flat-name question.
- **Where the registry carries it, and whether buyers can filter on it.** A filter on a
  maximum treats a listing that declares none as making no commitment.
- **Whether the disclosed copy needs authority beyond the registry's signature.** The
  storefront judges against the bounds in force when it agrees, not the published copy,
  so a stale copy costs a refusal, not a wrong deal.
