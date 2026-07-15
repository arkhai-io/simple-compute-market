## Context

Recovered from `docs/development/ARCHITECTURE.md`'s "Physical Settlement
Scheduler and FulfillmentProvider Architecture" section and the
pre-migration `TODO.md`'s POOLS-4 item; see `pools-2`'s design.md Context
for the provenance note. Verified and corrected against current code
before writing this down — see proposal.md's "Correction from the original
plan."

## Goals / Non-Goals

See proposal.md.

## Decisions

### 1. `fill_first`/`most_available` placement policies become moot for pool-shaped reservations

Once the ordinary reservation path stops requiring `vm_host` and instead
carries capacity/pool attributes, the storefront's own placement policies
no longer decide *which physical host* — that decision moves to
`pools-2`'s scheduler on the provisioning side. `AggregateCapacityClient`
still decides *which site* to route a reservation to when multiple sites
are aggregated (per `site-capacity`'s multi-site aggregation requirement,
unchanged by this item); it stops deciding host placement within a site.

### 2. Rename is schema + call sites, not a behavior change

`compute_inventory_pools` → `compute_capacity_pools` is a pure rename: same
columns, same foreign-key relationships, same reconciler behavior. Doing it
as part of this change rather than deferring keeps the storefront's
internal naming aligned with the capacity-shaped claim vocabulary this
change also introduces, instead of landing capacity-language reservations
on top of a table still named for the old host-inventory model.

## Risks / Trade-offs

- **Breaking claim-shape change.** Any external caller building
  `vm_host`-shaped reservation claims directly needs to move to
  capacity/pool attributes or the explicit specific-resource path.
- **Ownership-rule prose drift.** The baseline `site-capacity` spec already
  states the provisioning-owns-inventory / storefront-owns-projection rule;
  this change should confirm current prose still matches rather than
  assume it does, since the codebase has moved since this item was
  originally written (see the `SiteLedger` correction above).

## Migration Plan

1. Add the `compute_capacity_pools` rename migration; keep it purely
   additive/renaming, no data reshaping.
2. Update reservation claim models and `RemoteCapacityClient`/
   `AggregateCapacityClient` call sites together, since they share the
   claim shape.
3. Update or add tests asserting the ordinary path no longer requires
   `vm_host` and that the specific-resource path still works for opted-in
   listings.
