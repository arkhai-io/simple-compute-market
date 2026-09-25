## ADDED Requirements

### Requirement: Projection rows name their pool `pool_id`

Every pool entry of the resource-pool projection and every bucket row of the
capacity-bucket projection MUST name its Resource Pool in a `pool_id` field, the name the
pool's identifier carries on every other surface.

Within the resource-pool projection, a resource's pool is the pool entry that contains it.
A publication view that repeats the pool's identifier MUST name that same pool, and a
consumer MUST treat a generation where it does not as invalid, holding what it derives
from that site rather than closing it.

#### Scenario: A site produces its projections

- **WHEN** a site produces either projection
- **THEN** each pool entry or bucket row names its pool in `pool_id`

#### Scenario: A publication view names a different pool than its container

- **WHEN** a resource's publication view names a pool other than the pool entry that
  contains the resource
- **THEN** the consumer treats the generation as invalid and holds that site's listings
