## Why

`required_attributes=("vm_host",)` in the storefront's capacity-reservation
claim shape forces physical host selection into the storefront for the
ordinary reservation path — verified still present today
(`core_storefront/models/settle_models.py`, `vm_fulfillment_service.py`,
`resource_capacity_validator.py`). The `AggregateCapacityClient`
placement policies (`fill_first`, `most_available`, in
`core_storefront/aggregation.py`) are symptoms of the same layering issue:
the storefront is making a physical-placement decision that
`pools-2-physical-settlement-scheduler` now gives provisioning a formal
way to own.

**Correction from the original plan (verified against current code, not
assumed):** the `SiteLedger`/`SiteResourcesService` rename this item
originally called for has already happened — the site authority is now
`CapacityLedgerService`/`SiteAuthorityPort` in `kit/site/src/market_site/`.
That work is done; it is not part of this change's remaining scope. The
`compute_inventory_pools` table name, however, is still unrenamed
(`domains/vms/storefront/src/market_storefront/utils/{sqlite_client,migrations}.py`,
`domains/vms/listings/reconciler.py`) and remains this change's scope.

## What Changes

- Remove the `vm_host`-specific requirement from the ordinary capacity
  reservation path. A `resource_id` path remains valid only for
  intentionally specific-resource listings, using `pools-2`'s
  specific-resource request shape.
- Update the storefront reservation claim shape to use capacity/pool
  attributes instead of VM-host attributes; update `RemoteCapacityClient`/
  `AggregateCapacityClient` call sites that currently assume physical host
  selection.
- Rename `compute_inventory_pools` to `compute_capacity_pools` in the
  storefront SQLite schema, and update `SQLiteClient`, the listings
  reconciler, and their tests.
- Apply `pools-2`'s reservation-expiry decision (lease-shaped windows,
  watchdog-driven expiry at the site authority) to the storefront-facing
  reservation path: update whatever watchdog/release/TTL wiring the
  storefront side needs to match.
- Confirm and, where prose has drifted, restate the ownership rule already
  expressed in `site-capacity`'s baseline spec: provisioning is the source
  of truth for physical inventory, resource pools, scheduling, and
  settlement resources; the storefront owns capacity offerings/projections
  and market reservations.

## Non-Goals

- Renaming the `SiteResource`/`SiteAllocation` ORM model names — the
  service-level rename is done, but these model names still carry `Site`
  prefixes. Left as naming debt, not blocking.
- Any provider execution or scheduler behavior change — this change only
  changes what the storefront asks for, not how provisioning fulfills it.
- Package extraction (`pools-5`).

## Capabilities

### Modified Capabilities

- `site-capacity`: capacity reservation claims become capacity/pool-shaped
  rather than host-shaped for the ordinary path; the specific-resource path
  remains available for explicit opt-in listings.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler`'s specific-resource
  request shape and reservation-expiry model.
- Independent of `pools-3-fulfillment-provider` — does not require provider
  execution to exist.

## Impact

- **Packages:** `core/storefront`, `domains/vms/storefront`,
  `domains/vms/listings`.
- **Database:** storefront SQLite migration renaming
  `compute_inventory_pools` to `compute_capacity_pools`.
- **API:** reservation claim wire shape changes from host-attribute-based
  to capacity/pool-attribute-based; existing callers assuming `vm_host`
  need updating.
- **Compatibility:** breaking for any caller relying on `vm_host` in the
  ordinary reservation path; the specific-resource path is the intended
  replacement for genuinely host-specific listings.
