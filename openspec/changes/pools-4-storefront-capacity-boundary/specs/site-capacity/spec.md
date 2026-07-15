## MODIFIED Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a
storefront MUST reach capacity only through the CapacityClient boundary,
MUST treat its own view as a projection, and MUST express ordinary
reservation claims as capacity/pool attributes rather than host-specific
attributes. A `resource_id`-based claim remains valid only for a listing
that has explicitly opted into specific-resource selection.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

#### Scenario: Ordinary reservation omits a specific host
- **WHEN** a buyer reserves through a listing that has not opted into specific-resource selection
- **THEN** the reservation claim carries capacity/pool attributes and the storefront does not require or select a `vm_host`

#### Scenario: Specific-resource listing reserves a named resource
- **WHEN** a buyer reserves through a listing that has opted into specific-resource selection
- **THEN** the reservation claim carries the explicit `resource_id` and the ordinary capacity-attribute path is not required
