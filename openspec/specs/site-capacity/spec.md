# Site Capacity Specification

## Purpose

Define authoritative site ledgers, storefront capacity projections, reservations, aggregation, and event delivery.

## Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a storefront MUST reach capacity only through the CapacityClient boundary and MUST treat its own view as a projection.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

### Requirement: Storefront capacity-claim identity
VM compute listings MUST normalize surrounding whitespace and carry at least one valid `pool_id` or `resource_id`. Every supplied identity MUST begin with an alphanumeric character, contain only letters, digits, `.`, `_`, `:`, or `-`, and contain at most 128 characters. A pool-only listing produces a pool-scoped reservation claim. A listing carrying `resource_id`, whether alone or with `pool_id`, produces a resource-specific claim and excludes `pool_id`. Ordinary pool-scoped claims MUST NOT require or select a `host_id` or `resource_id`.

Claim construction MUST reject a missing, empty, or malformed settlement order and any extracted claim lacking both identities before probing or reserving capacity. Stored listings that violate the identity invariant MUST fail closed on publication or republication. Resuming such a listing MUST return an actionable conflict before changing pause state or contacting a registry; the seller-authenticated close operation MUST remain available without implicit identity backfill or automatic unpublication.

#### Scenario: Pool-only listing creates an ordinary reservation
- **WHEN** a buyer reserves through a listing carrying `pool_id` without `resource_id`
- **THEN** the claim carries `pool_id` and capacity/shape attributes without requiring or selecting a specific host or resource

#### Scenario: Resource-only listing creates a specific reservation
- **WHEN** a buyer reserves through a listing carrying `resource_id` without `pool_id`
- **THEN** the claim carries the explicit `resource_id` and does not require pool-scoped matching

#### Scenario: Listing carries both capacity identities
- **WHEN** a listing carries both `pool_id` and `resource_id`
- **THEN** the claim carries `resource_id` and drops `pool_id`

#### Scenario: Listing carries neither capacity identity
- **WHEN** a compute listing is created without `pool_id` or `resource_id`
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Listing carries a malformed capacity identity
- **WHEN** a supplied identity is empty, whitespace-only, malformed, or too long
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Settlement order is absent or malformed
- **WHEN** VM fulfillment receives no valid non-empty settlement order
- **THEN** fulfillment fails before probing or reserving capacity rather than constructing an unscoped claim

#### Scenario: Legacy-invalid listing is resumed
- **WHEN** an operator resumes a stored listing that lacks a valid capacity identity
- **THEN** the storefront returns an actionable conflict without changing pause state or contacting a registry

#### Scenario: Legacy-invalid listing is explicitly closed
- **WHEN** the operator invokes the seller-authenticated close operation after the validation conflict
- **THEN** the storefront removes it from active registry discovery without inventing a capacity identity

### Requirement: Requested offering mode is explicit and bounded by the pool

Every capacity probe and reservation claim MUST carry a non-empty canonical `offering_mode` naming the requested offering mode, and that key MUST be required. It is the same value a Resource Pool declares as deliverable, the same value the durable listing binding records, and the same value the published listing carries; no surface may name it `executor_kind`, `offering_type`, or `virtualization_type`. The site authority MUST persist that exact value on the Capacity Reservation and MUST NOT infer it from `host_id`, `physical_host_id`, resource kind, market name, matched-resource attributes, or any default. A matching Resource Pool MUST currently declare the requested mode before a new hold is created.

The claim's site-inventory discriminator remains a separate field and a separate axis. Naming the offering mode consistently MUST NOT merge the two.

`executor` MUST NOT be used as vocabulary for the offering mode, for the machine, or for the delivery handler. The machine is a host, the handler is a provider, and the mode is an offering mode.

Legacy reservations, settlement assignments, and executor jobs that predate the field MUST be backfilled only when durable request, settlement, provider-input, or executor-reference evidence proves exactly one mode. A reservation persisted under the retired key MUST be migrated to the settled one rather than read through a compatibility mapping, so that a search for the retired name is trustworthy evidence no surface still produces it. An active row with no proof or conflicting proof MUST be quarantined from execution; a completed row keeps its terminal lifecycle state while recording the quarantine. A settlement or request identity that conflicts with an already explicit reservation identity is schema drift, not a precedence choice.

#### Scenario: Claim omits the requested mode

- **WHEN** a capacity probe or reservation claim omits `offering_mode`
- **THEN** the site authority rejects it before matching resources and does not infer `vm` from a matched resource

#### Scenario: Claim names the requested mode under a retired key

- **WHEN** a capacity probe or reservation claim carries the requested mode under `executor_kind`
- **THEN** the claim is treated as carrying no offering mode and is refused

#### Scenario: Pool does not declare the requested mode

- **WHEN** a Physical Resource matches the requested shape but its Resource Pool does not declare the claim's offering mode
- **THEN** reservation is refused with the mode and pool identified before a Capacity Reservation or debit exists

#### Scenario: Legacy identity has one durable proof

- **WHEN** a legacy reservation has no recorded offering mode and durable provider or placement fields prove exactly one mode
- **THEN** migration records that mode on the reservation and propagates it to its settlement and executor job

#### Scenario: Legacy identity is unproved or conflicting

- **WHEN** a live legacy reservation or executor job has no single provable mode
- **THEN** migration moves it to the durable unmanaged or failed quarantine path without selecting `vm` or another fallback

### Requirement: Offering mode is enforced through fulfillment

The same pool-declaration membership predicate MUST be applied independently when the site authority admits a reservation, when fulfillment schedules a Settlement Resource, and immediately before provider dispatch. Scheduling and provisioning MUST re-read the selected Resource Pool's current declaration, including on an idempotent retry or a previously prepared provider operation. Withdrawing a mode after a hold or assignment therefore blocks new execution in that mode without mutating the historical requested mode.

Pool mode authorization and cross-mode physical accounting are independent checks. Declaring both `vm` and `bare_metal` authorizes both delivery paths but does not permit an exclusive whole-host allocation to overlap a live shareable slice; conversely, conflict-free capacity does not authorize an undeclared mode.

#### Scenario: Mode is withdrawn after reservation

- **WHEN** a Resource Pool removes the reservation's mode before scheduling
- **THEN** scheduling refuses the reservation without selecting another pool, mode, site, or executor

#### Scenario: Mode is withdrawn after provider input is prepared

- **WHEN** a Resource Pool removes the assignment's mode before a prepared create operation is dispatched
- **THEN** fulfillment refuses before provider I/O and does not treat the snapshot as permanent permission

#### Scenario: Pool declares both physical modes

- **WHEN** a Resource Pool declares `vm` and `bare_metal` but a shareable VM slice already holds the Physical Resource
- **THEN** an exclusive bare-metal request is still refused by cross-mode physical accounting

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

### Requirement: Reservation scheduling view
A capacity reservation MUST expose its identity, lifecycle state, hold expiry, reserved dimensions, resource kind, and generic scheduling constraints through the site-authority boundary. Scheduling MUST reject a missing or expired reservation and any request that conflicts with the reservation's generic physical requirements. Commercial agreement identity and terms remain at the storefront and MUST NOT be required by generic scheduling.

#### Scenario: Reservation is missing
- **WHEN** scheduling references a `capacity_reservation_id` that the site authority does not know
- **THEN** scheduling reports a missing-reservation error before policy selection

#### Scenario: Reservation hold expired
- **WHEN** scheduling references an uncommitted hold whose expiry has passed
- **THEN** scheduling reports reservation expiry before policy selection

#### Scenario: Request exceeds reserved dimensions
- **WHEN** a scheduling request asks for more of a dimension than the reservation holds
- **THEN** scheduling reports a request mismatch before assignment or provider execution

### Requirement: Reservation lifecycle
Capacity reservation MUST use a hold/commit/release lifecycle keyed by durable allocation identity, support expiry of uncommitted holds, and be idempotent for retries.

`reserve()` itself is idempotent by `deal_ref`'s `escrow_uid` when present: a repeat call for an escrow_uid with an existing reservation in any held state (`reserved`, `provisioning`, `leased`, `releasing`, `release_failed`, `unmanaged`) returns that reservation rather than admitting a second one. This closes the retry gap `commit`/`release` already closed for their own calls: a caller retrying `reserve()` itself after a crash — before it durably recorded the first reservation's identity elsewhere — does not double-reserve capacity for the same deal. An escrow_uid whose prior reservation already expired or was released is not matched (it has moved out of the held states), so a genuinely new attempt after expiry still admits fresh.

#### Scenario: Two buyers reserve the same final unit
- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

#### Scenario: Reserve is retried for the same deal before its identity is durably recorded elsewhere
- **WHEN** `reserve()` is called again with the same `deal_ref.escrow_uid` while the first reservation is still in a held state
- **THEN** the existing reservation is returned and no additional capacity is admitted

#### Scenario: Reserve is retried after the prior hold expired
- **WHEN** `reserve()` is called again with an `escrow_uid` whose only prior reservation has already expired or been released
- **THEN** a new reservation is admitted, exactly as if no prior attempt had occurred

### Requirement: Multi-site aggregation
A storefront MAY aggregate multiple site clients as soft state but MUST route each reserve to one authority and MUST NOT create cross-site hard-state capacity of its own.

#### Scenario: One site cannot satisfy a request
- **WHEN** another configured site can satisfy it
- **THEN** the aggregator may reserve at the eligible site and records which site owns the allocation

### Requirement: Capacity and deal events
Site authorities MUST publish anonymous versioned capacity deltas for projection subscribers and MUST route deal-scoped execution events to the owning storefront. Capacity deltas for multidimensional resources MUST report the per-dimension availability change so consumers do not infer one dimension from another.

#### Scenario: Capacity is released
- **WHEN** an allocation release commits in the site ledger
- **THEN** subscribers can observe a capacity version advance and reconcile listings idempotently

### Requirement: Cross-mode physical accounting
Shareable VM slices and exclusive bare-metal allocations referring to the same physical host MUST conflict according to allocation mode before executor work starts.

A capacity declaration carries the fields this accounting reads — `physical_host_id` and `allocation_mode` — at the top level of its attributes and nowhere else. A domain's publication settings MUST NOT repeat them, so the value the site authority accounts with is the only value there is.

#### Scenario: VM slice is held
- **WHEN** an exclusive bare-metal reservation targets the same physical host
- **THEN** the site ledger rejects the exclusive reservation

#### Scenario: A bare-metal declaration is registered
- **WHEN** a bare-metal declaration names its physical machine and allocation mode
- **THEN** both are top-level attributes, and its publication settings carry neither

### Requirement: Multidimensional capacity accounting
A site resource MAY declare total capacity across more than one named quantity dimension (for example `gpu_count`, `vcpu_count`, `ram_gb`, `disk_gb`); a claim's requested quantities MUST be checked and held against every declared dimension, not only a single default quantity, with held/available accounting kept exact under concurrent holds. A dimension a resource does not declare MUST NOT be assumed to have room. This accounting is per resource row: it does not aggregate or cross-check declared or held capacity across multiple resource rows that happen to share a physical host (see "Cross-mode physical accounting" above for the one cross-row check that does exist, which is scoped to exclusive/shareable mode conflicts, not capacity sums).

#### Scenario: A reservation would exceed a secondary dimension
- **WHEN** a claim requests more of a declared dimension (for example memory) than the resource has available, even though another dimension (for example GPU count) would fit
- **THEN** the reservation is rejected rather than admitted for a shape the resource cannot serve

#### Scenario: Concurrent holds accumulate per dimension
- **WHEN** two separate holds are placed on one shareable resource
- **THEN** each declared dimension's available quantity reflects the sum of both holds, not just the dimension the first hold happened to request

#### Scenario: Legacy single-quantity claims are unaffected
- **WHEN** a claim requests a quantity using a legacy single-quantity key (`units`, or a composition's alias such as the VM domain's `gpu_count`) instead of a dimensions map
- **THEN** it is checked and held exactly as it was before multidimensional capacity existed, translated internally to the composition's mirror dimension

### Requirement: Executor-neutral site authority
The site authority MUST own Physical Resources, settlement-relevant Resource Pool identities, Capacity Reservations, committed allocations, deal ownership references, capacity versions, and capacity events without depending on lease watchdogs, job runners, or concrete executor teardown states. A provisioner MAY stage administrative pool membership and provider configuration, but those records MUST NOT alter settlement selection until integrated through the site-authority boundary.

#### Scenario: Allocation is committed
- **WHEN** a valid Capacity Reservation is committed for executor work
- **THEN** the site authority records its allocation identity, physical accounting mode, offering mode, and deal ownership while leaving execution policy to the compute lifecycle

#### Scenario: Generic site package is installed alone
- **WHEN** site authority modules are imported without VM or bare-metal provisioning packages
- **THEN** resource, reservation, allocation, and event behavior remains available without concrete executor imports

### Requirement: Idempotent release recording
The site authority MUST record release exactly once for an allocation and advance capacity version only when the authoritative allocation transition commits.

#### Scenario: Release command is repeated
- **WHEN** the compute lifecycle repeats a successful release command with the same allocation identity
- **THEN** the site authority returns the released state without duplicating capacity or event transitions

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

### Requirement: Reservation supersede and settlement abandonment

A negotiated shape change to an already-reserved capacity hold MUST NOT mutate the existing `CapacityReservation` or any settlement assignment already bound to it in place. `CapacityLedgerService.resize_reservation` supersedes it instead: one atomic transaction releases the old reservation, evaluates the new shape's candidacy as if the old hold had already cleared, reserves the new shape under a new `capacity_reservation_id`, and commits or rolls back all of it together. A new shape with no eligible candidate leaves the old reservation exactly as it was — still held, never released — rather than losing it. `resize_reservation` is a single self-managed-session method; it is not composed into a larger caller transaction.

The site authority reclaims capacity from a reservation in exactly three internal paths: a lapsed TTL hold, a terminal release, and a resize's supersede step. Each of these unconditionally invokes an optional `SettlementAbandonmentHook`, a `Protocol` this package defines without referencing fulfillment types, in the same transaction as the reclaim. `market_site` MUST NOT import `market_fulfillment` to implement this hook, including under `TYPE_CHECKING`; the concrete implementation is supplied by the fulfillment capability at composition time and alone decides whether there is a not-yet-dispatched settlement assignment to mark abandoned. The site authority calls the hook regardless of whether one exists for the reservation in question.

#### Scenario: Resize evaluates the new shape as if the old hold already cleared

- **WHEN** a reservation is resized to a new shape that only fits once the old reservation's own held capacity is released
- **THEN** the resize succeeds, because release and re-evaluation happen inside the same transaction rather than as two independently committed steps

#### Scenario: Resize rolls back when the new shape is unavailable

- **WHEN** no candidate satisfies the new shape
- **THEN** the whole transaction rolls back and the old reservation remains held, unmodified, with no abandonment hook invoked

#### Scenario: Capacity reclaim always offers the abandonment hook a chance to react

- **WHEN** a TTL hold lapses, a reservation is released, or a resize supersedes a reservation
- **THEN** the configured `SettlementAbandonmentHook`, if any, is called for the affected `capacity_reservation_id` regardless of whether a settlement assignment exists for it

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

### Requirement: Per-site projection load-state visibility
A storefront MUST report, per configured site and per independent projection family (resource-pool, capacity-bucket), whether that projection has never loaded, is currently loaded, is stale, or is unavailable. This state MUST be visible on the storefront's operator status surface, scoped per site and family — one site's load failure MUST NOT present as broad storefront degradation while other configured sites are healthy. A storefront MUST NOT persist projection generations durably across restart; retry-until-success plus this observable status is the accepted mechanism for a site being unreachable at storefront startup. Any future reader of these caches MUST treat a never-loaded or unavailable state as unknown, not as authoritative zero capacity — the same principle "Site authority is unavailable" already states for the legacy reconciliation path applies equally here.

#### Scenario: A configured site is unreachable at storefront startup
- **WHEN** the storefront starts and one configured site's projection load has not yet succeeded
- **THEN** operator status reports that site/family as not-yet-loaded rather than presenting an empty projection as authoritative, and the storefront continues retrying without blocking readiness for other configured sites

#### Scenario: One projection family fails to refresh after a successful load
- **WHEN** a resource-pool refresh fails while the capacity-bucket family advances
- **THEN** the storefront retains the previous resource-pool generation in memory as stale, reports that state on the status surface, and commits the capacity-bucket replacement independently

#### Scenario: A site's projection has genuinely loaded with zero pools
- **WHEN** a site's resource-pool projection has successfully loaded and that site currently has no pools
- **THEN** a projection consumer treats that site as an authoritative empty answer, distinct from a site whose projection has never loaded — it MUST NOT fall back to a different capacity source for that site on the theory that an empty result might mean the projection is unavailable

#### Scenario: A projected resource's own availability is authoritative
- **WHEN** a projected resource carries its own `available` field alongside a separately-sourced fallback availability value for the same resource
- **THEN** a consumer uses the projection's own `available` field regardless of whether the fallback value is present or absent — the projection's own live data is never conditionally discarded in favor of a fallback source

### Requirement: Capacity accounting is private to the site authority
The site authority SHALL account reservable capacity with `CapacityBucket` rows and SHALL store each active reservation's current backing in `CapacityReservationDebit`. A storefront-facing capacity reservation SHALL NOT expose a bucket identifier or backing physical-resource identifier. This extends to domain-specific physical-placement fields carried on the reservation (for example the `host_id` a reservation's execution reference carries), not only the site authority's own generic accounting identifiers -- any field that identifies which concrete physical resource is serving a reservation is a backing physical-resource identifier for the purposes of this requirement, regardless of which domain named it. Scheduling MAY atomically replace the current debit when it selects a different eligible bucket.

#### Scenario: Storefront reads a capacity reservation
- **WHEN** a storefront reads an admitted reservation
- **THEN** it receives lifecycle state and reserved dimensions without private bucket or backing-resource identity

### Requirement: Physical inventory and grouped capacity are separate projections
A site authority SHALL expose `site_resource_pools` from authoritative domain inventory and `site_capacity_buckets` from current bucket availability. Each projection SHALL have an independent monotonic revision and canonical digest. Grouped capacity SHALL contain deterministic grouping criteria and `resource_count`, SHALL NOT contain physical-resource identifiers, and SHALL NOT be used as an allocation target.

#### Scenario: Storefront refreshes grouped capacity
- **WHEN** the capacity-bucket projection revision changes
- **THEN** the storefront can replace that projection independently without receiving physical-resource identifiers or using a group as an allocation target

### Requirement: Committed dimensions remain authoritative through scheduling

Scheduling MUST NOT admit a dimension shape exceeding what the capacity reservation declares. Within that bound, a scheduling request MAY be narrower than the reservation — reflecting, for example, a negotiated shape change not yet expressed as a reservation resize, or a placement/pricing check against a candidate shape. The dimensions actually scheduled — not the reservation's own dimensions unconditionally — are the authoritative admitted resource shape carried with the selected settlement resource, so the domain fulfillment provider can interpret them without the caller retransmitting an independently computed shape. A negotiated shape change that is meant to persist resizes the reservation itself (supersede, never mutate) rather than relying on an implicit narrower scheduling request to represent it.

#### Scenario: Scheduling request narrower than the reservation is permitted
- **WHEN** a scheduling request asks for less of a dimension than the reservation holds
- **THEN** scheduling admits the narrower shape and records the dimensions actually scheduled, not the reservation's full dimensions, on the selected settlement resource

#### Scenario: Scheduling request exceeding the reservation is rejected
- **WHEN** a scheduling request asks for more of a governed dimension than the reservation holds
- **THEN** scheduling rejects the request before assignment or provider execution

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

### Requirement: Operator-administered capacity declarations

A site authority MUST accept operator-administered capacity resources as the
authoritative declaration of sellable capacity for one Physical Resource identity,
across every capacity dimension the declaration carries. A declaration is
authoritative for shape and quantity — what is declared sellable and how much of
it there is. Whether that declaration may be admitted against is a separate
property resolved outside the declaration, and a capacity resource MUST remain a
complete and authoritative declaration of its own shape regardless of that
property. A capacity declaration MUST be able to
express more than one dimension, and the authority MUST NOT require any particular
dimension to be present. Where an operator has declared capacity for a Physical
Resource, no other inventory record SHALL supply or override that resource's
projected capacity.

Every declaration MUST name its Resource Pool. A registration request that omits the
pool MUST be rejected at request validation rather than recorded against a default,
because registration replaces the whole declaration and a silently defaulted pool is
a reassignment nobody requested. A declaration naming a pool the site does not have
MUST be refused, whether it arrives as a registration or a document entry. A stored
declaration with no recorded pool is read as belonging to the default pool.

#### Scenario: Shape authority is not admission authority

- **WHEN** a consumer reads a declared capacity resource
- **THEN** the declared shape and quantity are authoritative
- **AND** whether the declaration may be admitted against is resolved outside the declaration itself

#### Scenario: Operator declares multidimensional capacity

- **WHEN** an operator registers a capacity resource declaring several dimensions for
  a Physical Resource
- **THEN** the site authority records every declared dimension and admission,
  matching, and projection all read the declared values

#### Scenario: Declared capacity supersedes any other inventory record

- **WHEN** a Physical Resource has both an operator-declared capacity resource and an
  inventory record elsewhere describing the same resource
- **THEN** the declared capacity resource is authoritative and the other record does
  not contribute capacity

#### Scenario: Registration names a pool that does not exist

- **WHEN** a capacity registration names a Resource Pool the site does not have
- **THEN** it is refused as invalid and no declaration is written or changed

#### Scenario: Registration omits the pool

- **WHEN** a capacity registration request carries no pool identifier
- **THEN** it is rejected at request validation and no declaration is written or changed

#### Scenario: Declaration omits a dimension

- **WHEN** a capacity declaration carries only some dimensions
- **THEN** the authority accepts it and treats the omitted dimensions as undeclared
  rather than rejecting the declaration or substituting a value from another record

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

### Requirement: A capacity declaration names no mandatory dimension

A capacity authority MUST accept a declaration expressing any set of dimensions and
MUST NOT write a dimension the caller did not declare. Where a legacy scalar unit
mirror is maintained, the dimension it mirrors MUST be supplied by the composition
root, the way domain-specific claim aliases already are, rather than fixed in the
shared capacity module.

Where a caller declares capacity explicitly, the authority MUST NOT add a mirror
dimension to that declaration. The legacy scalar unit total MUST be optional, and
MUST be absent where the declaration names no mirror dimension — the existing
consistency check between the scalar and its mirrored dimension compares them when
both are present, so absence rather than a substituted zero is what keeps that check
meaningful. A declaration naming only dimensions a domain owns —
for example a credit balance with no compute dimension — MUST be stored as declared.

#### Scenario: A declaration names no compute dimension

- **WHEN** an operator declares capacity consisting only of a domain's own unit dimension
- **THEN** the stored declaration contains exactly that dimension
- **AND** no GPU or other compute dimension is manufactured

#### Scenario: A declaration has no mirror dimension to total

- **WHEN** a declaration names no dimension the legacy scalar mirrors
- **THEN** the scalar unit total is absent rather than zero
- **AND** the consistency check between the scalar and its mirrored dimension does not apply

#### Scenario: A legacy single-quantity claim is translated

- **WHEN** a claim requests a unit count through a legacy single-quantity key rather
  than a dimensions map
- **THEN** it is translated to the composition's mirror dimension, and the matching,
  held-quantity, and payload mirror fields all read that same dimension

#### Scenario: A composition supplies its mirror dimension

- **WHEN** a composition root configures which dimension the legacy scalar mirror tracks
- **THEN** that dimension is used for the mirror in that composition
- **AND** no other composition's dimension name appears in it

#### Scenario: A claim names another domain's dimension as an attribute

- **GIVEN** a composition whose mirror dimension and unit claim keys do not include
  `gpu_count`
- **WHEN** a claim requires `gpu_count` equal to a resource's unit total
- **THEN** the resource does not match, because the unit total is a matchable fact
  only under the composition's own mirror dimension

### Requirement: A declaration's attributes cannot restate its identity

A capacity authority MUST refuse a declaration whose attributes use a key naming one
of the declaration's own fields: the resource id, pool, host, resource type, or
resource subtype. Those are declaration fields, and an attribute of the same name
would be a second, disagreeing statement of the same fact. Wherever claims are
matched against a resource, its declaration fields MUST take precedence over any
attribute of the same name, so a stored declaration written before this rule
cannot change its own identity for matching.

#### Scenario: A registration puts the host in attributes

- **WHEN** a registration request's attributes include `host_id`
- **THEN** it is refused as invalid and no declaration is written or changed

#### Scenario: A stored declaration carries a conflicting attribute

- **GIVEN** a stored declaration whose host is `kvm1` and whose attributes name
  `host_id` as `kvm9`
- **WHEN** a claim requires `host_id` `kvm1`
- **THEN** the declaration matches, and a claim requiring `kvm9` does not

### Requirement: A capacity resource does not move pools under live obligations

A capacity resource MUST NOT be reassigned from one Resource Pool to another while
it has a live capacity obligation — a hold, a reservation, an assignment, or a
workload — whose authority is resolved through its pool. A reassignment request in
that state MUST be refused, and the resource MUST remain in its current pool.

A live capacity obligation is a reservation in a capacity-holding state whose
capacity is debited against the resource or whose settlement assignment names it.
Every running workload holds such a reservation, so the site authority enforces this
rule without consulting fulfillment state.

A reservation's pool is resolved through the resource's current pool rather than
recorded on the reservation, so reassignment would otherwise rewrite the authority
underneath an existing obligation without that obligation changing. This applies to
every reassignment, including moving a resource to a pool declaring a different
provider or different capacity backing.

#### Scenario: A resource with a live reservation is reassigned

- **WHEN** a reassignment is requested for a capacity resource holding a live reservation
- **THEN** the request is refused and the resource remains in its current pool

#### Scenario: A resource assigned to a reservation is reassigned

- **WHEN** a reassignment is requested for a capacity resource a held reservation has
  been assigned to for settlement, though its capacity was debited elsewhere
- **THEN** the request is refused and the resource remains in its current pool

#### Scenario: A drained resource is reassigned

- **WHEN** a reassignment is requested for a capacity resource with no live capacity obligation
- **THEN** the reassignment succeeds
