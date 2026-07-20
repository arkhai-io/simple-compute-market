## Context

This content was originally designed as part of `pools-7-storefront-
fulfillment-cutover`'s design review (2026-07-17) and split out here —
see that change's `proposal.md`/`design.md` "Scope split" sections for
why. Nothing below reflects new analysis beyond what that review already
settled; it's relocated, not reconsidered.

## `CapacityProjection` schema

```python
class CachedResourcePool(Base):
    __tablename__ = "capacity_projection_pools"

    site = Column(String, primary_key=True)
    pool_id = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False)
    policy_tags = Column(JSON, nullable=False, default=dict)
    synced_at = Column(DateTime, nullable=False)
```

Pull-based sync job (analogous to, but the reverse direction of, the
storefront's existing `sync_site_resources()` push):

```python
async def sync_resource_pools(sites: dict[str, RemotePoolsClient]) -> int:
    """Pull-based mirror of every configured site's pool admin API —
    replaces the storefront's local resources table as the source of
    pool/resource identities used in reservation claims and listing
    publication."""
    ...
```

Must NOT be read by anything in the admission/reservation path
(`AggregateCapacityClient.reserve()`/`probe()`, `PhysicalSettlementScheduler`)
— those continue to use live, per-request data, unchanged. This cache is
for pricing/listing-publication decisions only. See `pools-7`'s
`design.md`, "`CapacityProjection` MUST NOT replace the live per-request
snapshot these policies read," for the reasoning — that constraint is
unaffected by this split; it just now lives in the change that actually
builds `CapacityProjection`.

## Listing-mode hint consumption

```python
# kit/resource-pools — domain-neutral: the key name only.
LISTING_MODE_TAG = "listing_mode"

# domains/vms — VM-domain interpretation + default.
class VmListingMode(str, Enum):
    pooled = "pooled"
    specific_resource = "specific_resource"

def resolve_vm_listing_mode(pool: CachedResourcePool, member_count: int) -> VmListingMode:
    declared = pool.policy_tags.get(LISTING_MODE_TAG)
    if declared in (VmListingMode.pooled.value, VmListingMode.specific_resource.value):
        return VmListingMode(declared)
    return (VmListingMode.specific_resource if member_count == 1
            else VmListingMode.pooled)   # unchanged pools-4 structural default
```

The reconciler-driven publish path (`domains/vms/listings/reconciler.py`,
`cli_publish.py`) already has the structural default above, confirmed
during `pools-4`'s design review. This change's job is narrower than it
might first appear: let an explicit hint override that default, don't
replace it. The reconciler calls `resolve_vm_listing_mode` once per pool
it's about to publish listings for, in the same place the structural
default already lives.

**Extensibility confirmed against `apicredits`, not just asserted:**
since `apicredits` is explicitly in scope for `pools-7`'s broader
`kit`/`CapacityReservation` reshape, the shape only counts as
domain-neutral if `apicredits` can express something VM doesn't need
without touching `kit/resource-pools`. It can:

```python
class ApiCreditsListingMode(str, Enum):
    shared_quota = "shared_quota"     # listing draws from a pooled quota bucket
    dedicated_key = "dedicated_key"   # listing is pinned to one provider API key

def resolve_apicredits_listing_mode(pool: CachedResourcePool) -> ApiCreditsListingMode:
    declared = pool.policy_tags.get(LISTING_MODE_TAG)
    if declared in (ApiCreditsListingMode.shared_quota.value, ApiCreditsListingMode.dedicated_key.value):
        return ApiCreditsListingMode(declared)
    return ApiCreditsListingMode.shared_quota
```

`kit/resource-pools` owns one string key; each domain owns its own enum
and default rule; no cross-domain coupling.

**Enforcement posture:** explicitly a hint, never provisioning-enforced.
`PhysicalSettlementScheduler`'s explicit-`resource_id` eligibility path
(`pools-2`) is unaffected by a pool's `listing_mode` regardless — a
buyer's explicit resource request is honored even against a pool tagged
`pooled`. A storefront that never reads the tag, or one running against a
provisioning service that predates this feature, falls through to the
unchanged structural default. Purely additive.

## Pool-level reservation TTL hint

An operator may want a pool-level limit on how long a
`CapacityReservation` against their resources can sit unscheduled/held.
Same shape and posture as the listing-mode hint: an additive
`ResourcePool.policy_tags` entry (`{"max_reservation_hold_seconds": 900}`),
read and voluntarily respected by a cooperating storefront when it
chooses the `ttl_seconds` it passes to `reserve()` — never enforced by
the provisioning service itself (`reserve()` already accepts a
caller-supplied `ttl_seconds`; no new ledger capability needed, only a
place for the operator to express a preference and a storefront willing
to read it).

## Open question inherited from `pools-7`

`pools-7`'s design review also surfaced, but did not resolve, whether
`AggregateCapacityClient`'s ranked site-fallback (`fill_first`/
`most_available`) is still meaningful once every claim is pool/resource-
pinned (post-`pools-4`) and pool/resource IDs are only unique per site —
a pinned claim's owning site is arguably already known at publish time,
making ranked multi-site fallback for that claim mostly vestigial. This
touches `CapacityProjection` in that a resolution would likely mean
site-tagging every cached pool/resource identity explicitly
(`site_id + pool_id + optional resource_id`) so claims can route
directly rather than being tried in ranked order. Not resolved here;
see `pools-7`'s `design.md`, "Open question surfaced by writing this
table down," for the full analysis. Whoever picks this change up should
check whether `pools-7` (or a further follow-on) has resolved it before
finalizing `CapacityProjection`'s key shape.
