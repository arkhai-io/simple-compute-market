## ADDED Requirements

### Requirement: The resource-pool projection is built from capacity declarations

The resource-pool projection SHALL enumerate every capacity declaration and SHALL
NOT read host inventory records. Each projected entry's Physical Resource
identity, pool, resource type and subtype, capacity, reported availability,
attributes, and `enabled` state SHALL come from its declaration alone. Whether a
declaration names a host, and whether a named host is registered, SHALL NOT
affect whether or how the declaration projects.

A generic projected entry SHALL NOT carry host connection identity: no host
identifier, connection address, or tenant-facing address. A domain publication
view MAY carry the host its declaration names where that domain sells a specific
host.

#### Scenario: A declaration names no host

- **GIVEN** a capacity declaration that names no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears with its declared capacity, attributes, and
  Physical Resource identity

#### Scenario: A declaration names an unregistered host

- **GIVEN** a capacity declaration naming a host that has no registered host
  record
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears exactly as a declaration naming no host would

#### Scenario: A generic entry carries no host connection identity

- **GIVEN** a capacity declaration naming a registered host that has a
  connection address and a tenant-facing address
- **WHEN** the resource-pool projection is produced
- **THEN** the entry's attributes carry neither the host identifier nor either
  address

#### Scenario: A disabled host does not change a projected declaration

- **GIVEN** an enabled capacity declaration naming a registered host that is
  disabled
- **WHEN** the resource-pool projection is produced
- **THEN** the entry is projected enabled, matching the declaration

### Requirement: Admission applies the pool provider's host requirement

Where its composition supplies a host requirement for fulfillment providers, a
site authority SHALL treat a capacity declaration that names no host as an
ineligible admission candidate when the provider of the declaration's pool needs
a host. A provider identity absent from a supplied requirement SHALL be treated
as needing a host. A composition that supplies no requirement SHALL NOT apply
one. Probe and reserve SHALL apply the same eligibility.

An ineligible candidate is refused in the ordinary capacity-refusal way: it does
not match, and a claim that no other candidate satisfies receives the same no-
capacity answer as any other unservable claim. Admission SHALL NOT require the
named host to be registered; registration is checked at dispatch.

#### Scenario: A host-requiring pool holds a declaration naming no host

- **GIVEN** a composition supplying a host requirement in which the pool's
  provider needs a host
- **AND** a matching capacity declaration in that pool names no host
- **WHEN** a claim is probed or reserved
- **THEN** that declaration does not match and no hold is created against it

#### Scenario: The pool's provider is absent from the supplied requirement

- **GIVEN** a composition supplying a host requirement that does not name the
  pool's provider
- **WHEN** a claim matches a declaration in that pool that names no host
- **THEN** the declaration does not match

#### Scenario: A composition supplies no host requirement

- **GIVEN** a composition that supplies no host requirement
- **WHEN** a claim matches a capacity declaration that names no host
- **THEN** it is admitted as any other matching declaration is

## MODIFIED Requirements

### Requirement: Resource-pool projection metadata
The `site_resource_pools` projection MAY carry allowlisted, additive pool-level metadata alongside per-resource inventory: `label`, `enabled`, `mechanism` (the pool's configured provider kind, e.g. `"ansible"` -- never provider credentials or connection configuration), opaque `policy_tags`, and a generic `pool_views` map. A projection producer omitting pool metadata, or a pool absent from a supplied metadata source, MUST yield a resource-pool row with no `pool_metadata` key at all, not an empty one -- older producers and consumers observe no behavioral change. Any change to projected pool metadata MUST advance that projection's existing revision and digest identically to a resource-level change.

`pool_views` is domain-neutral at this layer: the site-capacity projection carries it as an opaque `dict[str, Any]` and MUST NOT interpret its contents or require any provider-specific key names. Domain-owned content lives under a versioned key inside it (mirroring the existing per-resource `publication_views` convention) -- for example, an Ansible-provider pool's configured VM size defaults are published as `pool_views["vm.ansible_pool_defaults.v1"]`, a mapping shaped and populated entirely by the VM provisioning domain, never by the generic site-capacity or resource-pool packages. A view keyed by a domain/mechanism name (for example `vm.*`) MUST only be published for a pool whose `mechanism` actually matches that domain -- a stale or orphaned provider-specific configuration row for a pool that no longer uses that provider MUST NOT surface that provider's view.

A resource-pool row's per-resource `attributes` are the capacity declaration's own declared attributes, except domain view configuration published as a view. An attribute the declaration does not declare MUST be omitted from `attributes`, not published as null.

#### Scenario: Older producer omits pool metadata
- **WHEN** a resource-pool projection is produced with no pool-metadata source configured
- **THEN** every resource-pool row is emitted with the same shape as before pool metadata existed, with no `pool_metadata` key

#### Scenario: Pool metadata changes with unchanged resource inventory
- **WHEN** only a pool's `label`, `enabled` state, `policy_tags`, or `pool_views` content changes and its resource inventory does not
- **THEN** the resource-pool projection's revision and digest advance, identically to a resource-level change

#### Scenario: Provider credentials never enter the projection
- **WHEN** a pool's provider-specific configuration contains connection details or credentials alongside allowlisted fields
- **THEN** the projected `pool_metadata` and `pool_views` contain only the allowlisted fields; credentials and connection configuration are never present

#### Scenario: A stale provider-specific configuration row does not leak its view
- **WHEN** a pool's `mechanism` no longer matches the provider that a leftover provider-specific configuration row belongs to
- **THEN** that provider's versioned view is absent from `pool_views`, regardless of whether the stale row still exists

#### Scenario: An unset host-level attribute is omitted, not published as null
- **WHEN** a capacity declaration declares no GPU model, whether or not the host it names holds one on its host record
- **THEN** the corresponding resource-pool row's `attributes` carries no key for it, rather than a null value or the host record's value

### Requirement: A capacity declaration names the host it is delivered through

A capacity declaration delivered through a host MUST name that host as a `host_id`
field of the declaration, not as one of its attributes, and at most one
declaration MAY name a given host. A declaration delivered through no host names
none; naming a host is not required for a declaration to be valid, stored, or
projected. A registration naming a host another declaration names MUST be refused.
Execution references and a reservation's claim facts MUST take the host from that
field.

#### Scenario: A second declaration names a held host

- **WHEN** a declaration is registered with a `host_id` another declaration names
- **THEN** the registration is refused as a conflict and neither declaration changes

#### Scenario: A reservation is bound to a host

- **WHEN** a reservation is admitted against a declaration that names a host
- **THEN** its execution reference carries that declaration's `host_id`

#### Scenario: A declaration names no host

- **WHEN** a declaration is registered with no `host_id`
- **THEN** it is stored as declared and no host is inferred for it

### Requirement: Projected inventory is internally consistent

Projected physical inventory MUST NOT report attribute values that contradict the
same resource's projected capacity. A projected resource's capacity and its
descriptive attributes MUST derive from one authoritative record for that resource:
its capacity declaration, with every declared attribute projected except domain view
configuration already published as a view. No host inventory record contributes to
a projected resource. A quantity MUST appear only in the projected capacity, never
duplicated as an attribute.

#### Scenario: Declared capacity disagrees with a legacy inventory value

- **WHEN** an operator-declared capacity resource reports a different quantity for a
  dimension than a legacy inventory record holds for the same resource
- **THEN** the projection reports the declared value in capacity, reports no
  attribute carrying the same quantity, and never reports the two disagreeing in one
  projected row

#### Scenario: Categorical hardware identity is projected

- **WHEN** a capacity declaration carries a categorical hardware attribute matched by
  equality rather than by sufficiency
- **THEN** the projection reports it as an attribute rather than as a capacity
  dimension, sourced from the same authoritative record as the capacity

### Requirement: Separate capacity and deal event semantics
Capacity projection events MUST remain anonymous and versioned, while deal-scoped lifecycle events MUST retain the owning deal/storefront reference recorded on the allocation.

#### Scenario: Allocation changes capacity and deal state
- **WHEN** an executor lifecycle transition releases an allocation
- **THEN** projection subscribers can reconcile from the capacity version and the owning storefront can correlate its deal event without either channel exposing the other's private payload

**Evidence**

- Explicit request identity, absence and undeclared-mode refusal, legacy reservation behavior, declaration narrowing, and independent cross-mode accounting: `kit/site/tests/unit/test_ledger.py`.
- Scheduling-time mode enforcement and withdrawal after reservation: `kit/fulfillment/tests/unit/test_scheduler.py`.
- Pre-dispatch enforcement, including a previously prepared operation after declaration withdrawal: `kit/fulfillment/tests/unit/test_fulfillment.py`.
- Durable reservation/settlement/job backfill, quarantine, idempotency, and schema drift: `provisioning/compute/service/tests/unit/test_pool_offering_mode_migration.py`.
- Deployed reservation-boundary refusal before a hold exists: `e2e-tests/tests/e2e/roles/scenarios/vms/test_pool_declared_offering_modes.py`.
- Site-tagged soft-state aggregation and failure isolation: `core/storefront/tests/unit/test_aggregation.py`.
- Storefront-to-site HTTP contract: `kit/site-client/tests/unit/test_client.py`, `kit/site-client/tests/unit/test_opacity.py`.
- “Do not close on ignorance” reconciliation: `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py`.
- Shared feasibility predicate: `kit/site/tests/unit/test_resource_satisfies_requirement.py`.
- Session-scoped settlement assignment, locked reservation reads, and in-session backing-resource lookup: `kit/site/tests/unit/test_settlement_assignment.py`.
- Reservation supersede (`resize_reservation`) and unconditional settlement-abandonment hook invocation across TTL lapse, release, and resize: `kit/site/tests/unit/test_ledger.py`.
- Listing identity normalization and validation: `domains/vms/storefront/tests/unit/test_listing_model_capacity_identity.py`.
- Claim identity precedence and fail-closed construction: `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, `domains/vms/storefront/tests/unit/test_vm_fulfillment_planner.py`, and `domains/vms/storefront/tests/unit/test_fulfill_vm_obligation_error_handling.py`.
- Listing publication and legacy-invalid remediation: `domains/vms/storefront/tests/integration/test_listings_api.py`.
- Per-site/family projection load-state reporting, including partial multi-site failure isolation, never-loaded retry, and `fetched_at` tracking: `core/storefront/tests/unit/test_site_projections.py`, `domains/vms/storefront/tests/unit/services/test_site_projection_cache.py`, and `domains/vms/storefront/tests/unit/services/test_system_service.py`. A genuinely-loaded-empty site is distinguished from a never-loaded one, at both the producer and consumer level, rather than the empty case silently falling back to a different source: `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`. A projected resource's own `available` field is used even when a separately-sourced fallback value is present: `domains/vms/storefront/tests/unit/test_reconciler.py`.
- Resource-pool projection metadata: allowlisting/redaction, deep-copy isolation, digest advancement, and old-shape preservation: `kit/site/tests/unit/test_projections.py` and `kit/site/tests/unit/test_projection_router.py`. Composition (`ResourcePool`/`AnsiblePoolConfig` -> allowlisted metadata, including the provider/mechanism gate): `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`. VM size defaults reachable through the real pool admin API end to end (`ProvisioningClient.create_pool` -> `AnsiblePoolConfigHandler` -> DB -> read-back): `provisioning/compute/service/tests/integration/test_pools_api.py`. The same defaults surfacing through the real projection consumer (`SiteCapacityClient.resource_pool_projection()` over the real in-process app): `provisioning/compute/service/tests/integration/test_capacity_api.py`. Schema migration column addition and idempotency: `provisioning/compute/service/tests/unit/test_database.py`. A declaration's GPU model reaching the projected resource's `attributes`, omitted rather than null when the declaration does not declare one, including when only the host record holds one: `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py` and `provisioning/compute/service/tests/integration/test_capacity_api.py`.
- The real HTTP contract (`HealthResponse` server model through the actual `/api/v1/system/status` route to the real `StorefrontClient`) surfacing this state intact: `domains/vms/storefront/tests/integration/test_admin_api.py`.

Job-kind dispatch and deal-event routing across multiple storefront domains are not established by this capacity baseline.

**Capacity settlement lifecycle**

A **Capacity Reservation** records accepted capacity, the agreement/deal relationship, requested shape or units, lifecycle state, and any hold expiry. A reservation is not itself a concrete provisioning decision.

A **Capacity Settlement Assignment** is the idempotent scheduling decision that maps one unchanged Capacity Reservation to one concrete pooled Settlement Resource. Retrying assignment for the same unchanged reservation returns the existing decision rather than rerunning scheduling policy. An assignment alone does not imply that physical settlement succeeded or that a workload is active.

<a id="relationship-to-fulfillment-scheduling"></a>

**Relationship to fulfillment scheduling**

The site authority admits and persists capacity reservations. The higher-layer [fulfillment capability](../fulfillment/spec.md) binds an admitted reservation to a Settlement Resource and records that assignment through the site boundary before provider dispatch.

A reservation is scoped to the one provisioning authority (database) that admitted it; scheduling does not fall back to another site after admission. Cross-site ranking and any durable record of which site owns what is storefront aggregation policy applied before reservation — not a field this database carries, since one provisioning-service deployment is one site and every row in it already implicitly belongs to that site. Type-only imports from the site authority into fulfillment are prohibited because they would invert the kit dependency hierarchy.

`market_site` exports `resource_satisfies_requirement(resource_kind, available, attributes, required_resource_kind, required_dimensions, required_attributes) -> bool`, the one feasibility check both reservation-time admission and fulfillment's scheduling-time eligibility evaluate against. `required_resource_kind=None` accepts any resource kind, matching reservation admission's claim, where a resource-kind constraint is optional; scheduling always supplies a concrete one.

`CapacityLedgerService` exposes session-accepting entry points (`lock_reservation`, `assign_settlement_resource_in_session`, `backing_resource_id_in_session`, `iter_scheduling_candidates_in_session`) alongside its self-managed-transaction public methods (`get_reservation`, `assign_settlement_resource`, `get_reservation_backing_resource_id`, `reservation_payload_in_session`), so a higher-layer caller composing one transaction across reservation state and another authority's write — for example, fulfillment scheduling's settlement assignment — can open one session, drive both, and commit once. `market_site` remains unaware of what that other write is; the composition happens at the caller, which is why these are the only surface fulfillment scheduling needs from this package to keep the rebind and the settlement assignment atomic.

### Requirement: Site identity ownership boundary
Provisioning-owned site-capacity persistence MUST NOT redundantly store storefront-owned `site_id` on pools, resources, or reservations. The storefront aggregation boundary assigns the trusted site identity associated with a configured provisioning connection. A remote counterparty MUST NOT self-assert that identity in capacity payloads.

#### Scenario: Capacity payload attempts to assert site identity
- **WHEN** a provisioning endpoint returns or accepts a payload containing a caller-selected `site_id`
- **THEN** the storefront ignores that assertion and uses the identity bound to the configured connection
- **AND** provisioning capacity rows remain scoped by the local database authority rather than a redundant site column


**Internal capacity accounting**

A storefront-facing capacity reservation identifies the durable hold by `capacity_reservation_id` and exposes lifecycle metadata, expiry, and reserved dimensions. It does not expose the provisioning authority's initial accounting choice.

Within the site authority, a `CapacityBucket` is the per-declaration multidimensional accounting boundary: one bucket per capacity declaration, keyed by `backing_resource_id`, the declaration's resource id. `host_id` names the host its capacity is delivered through when it has one; a declaration delivered through no host has none. `CapacityReservationDebit` records the reservation's current bucket and debited dimensions. Scheduling may atomically replace that debit when it rebinds a reservation to another eligible resource and then records `settlement_resource_id`.

**Storefront projection families**

The site authority publishes two independent pull projections:

- `site_resource_pools` preserves resource-pool membership and the allowlisted per-resource inventory facts needed for individual-resource listings.
- `site_capacity_buckets` vertically groups resources with identical canonical grouping criteria and currently available dimensions. Each group exposes a deterministic digest-derived `capacity_group_key` and `resource_count`, but no internal capacity-bucket identifiers or duplicated physical-resource identifier list.

Each projection family has its own monotonic revision and canonical snapshot digest. Storefront caches replace complete generations atomically and retain the last complete generation when a refresh fails; unavailable projection state is distinct from an authoritative empty projection.
