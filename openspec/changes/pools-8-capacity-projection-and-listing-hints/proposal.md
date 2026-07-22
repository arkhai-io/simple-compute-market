## Why

POOLS-7 has landed independent site resource-pool and capacity-bucket projections, pull endpoints, and in-memory storefront caches, but those projections do not yet drive durable commercial publication or claim construction. Storefront-local inventory still mixes market metadata with physical authority, and operator listing/hold preferences are not projected or consumed.

## What Changes

- Persist configured provisioning-site bindings and the last accepted identity/value for each independent projection family so storefront restart retains complete stale-marked generations.
- Define explicit mapping between provisioning-owned projected resource identities and storefront-owned commercial inventory, pricing, settlement options, and listing identities.
- Make listing publication and reservation claim construction consume mapped authoritative projection identity rather than independently authored physical host/pool fields.
- Extend the resource-pool projection with the minimum pool metadata needed for domain-owned hints, including enabled state and opaque `policy_tags`.
- Define a domain-neutral `listing_mode` policy-tag key while VM, bare-metal, and API-credit domains own accepted values and structural defaults.
- Define an optional `max_reservation_hold_seconds` preference that cooperating storefronts cap against their own hold policy; it remains advisory rather than site-enforced.
- Retire only storefront-local physical-authority columns, CSV paths, validators, and readers proven superseded; retain commercial and operational state.
- State: **Planned after rebaseline; producer endpoints and in-memory cache mechanics are completed prerequisites, not implementation scope.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: Persist independently versioned projection generations and expose pool metadata needed for authoritative identity mapping without making projections admission authority.
- `storefront-publication`: Reconcile site projections into commercial publication/claim data and consume domain-owned listing/hold hints.
- `resource-pool-management`: Define domain-neutral policy-tag keys and projection metadata while leaving values and defaults to domains.

## Dependencies and Related Changes

- Depends on completed POOLS-7 projection producer endpoints, independent revisions/digests, stale retention, and storefront cache foundations.
- Coordinates with remaining POOLS-7 selected-site persistence so mapped identities route directly to the authority that produced them.
- `market-platform-bare-metal-10-storefront-composition` consumes the same projection contract with bare-metal-specific listing semantics.
- API credits may consume domain-owned hint values but does not use physical compute identities.

## Non-Goals

- Do not rebuild projection producer endpoints, revision tracking, polling, or in-memory cache replacement already landed in POOLS-7.
- Do not use cached projections for authoritative reservation admission or fulfillment assignment.
- Do not assume provisioning Resource Pools and storefront commercial capacity pools are the same object or namespace.
- Do not delete the entire storefront `resources` table while pricing, accepted settlement mechanisms, operator metadata, or other commercial readers remain.
- Do not let generic kits validate VM, bare-metal, or API-credit hint values.

## Impact

- Storefront persistence gains configured-site/projection generation state and explicit commercial mapping/reconciliation.
- Site projection payloads gain additive pool metadata with independent revision/digest changes.
- VM, bare-metal, and API-credit publication adapters gain domain-owned hint resolvers where applicable.
- Local inventory import, validator, publication, claim-building, migration, and operator paths require reader-by-reader disposition.
