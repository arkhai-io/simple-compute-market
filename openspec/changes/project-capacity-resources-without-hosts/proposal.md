## Why

The resource-pool projection is driven by host rows. `capacity_inventory` maps
capacity declarations by the host each one names, then iterates `Host` rows and
projects one entry per host a declaration names. A declaration that names no
host, or names a host that is not registered, contributes nothing to the
projection and is invisible to every storefront consuming it. The declaration
succeeds and nothing happens.

That contradicts the projection's own authority model.
`capacity-resource-administration` made the capacity declaration the single
authority for a Physical Resource's shape and quantity and made `Host`
connection identity only. The projection still refuses to show a declaration
unless a connection record exists for it.

Tracing what the projection actually reads from the host row showed the
correlation is not merely a precondition to relax but almost entirely
unneeded there:

- `attributes.host_id` and `attributes.public_host` have no projection
  consumer, and `public_host` falls back to the provisioner's management
  address, which a storefront-facing projection should not carry.
- `enabled` is folded with `Host.enabled`, which no admission, scheduling, or
  dispatch path consults, so the projection reports a state the site does not
  enforce.
- The `host.pool_id` fallback is dead: every declaration names its pool.
- The bare-metal publication view reads the host row only for `enabled`.

The one place a declaration must resolve to a registered host is dispatch,
where the host record supplies the connection. That is also where it currently
fails *open*: an unregistered host falls back to a static inventory file.

And scheduling does not fail closed at all. The scheduler will select a
Physical Resource whose declaration names no host, rebind capacity to it, and
commit an assignment the provider can never execute; an equivalent retry
returns the same unusable assignment. This exists today, independent of the
projection.

The campaign needs all of this closed. `unbacked-listing-publication` needs a
seller with no host inventory to project at all, and the contact-exchange
listings that goal serves have no host behind them by construction.

## What Changes

- **Build the resource-pool projection from capacity declarations alone.**
  Every declaration projects. No host inventory record is read. Each entry's
  identity, pool, type, capacity, reported availability, attributes, and
  `enabled` come from its declaration. Generic entries carry no host connection
  identity. This is not additive: existing entries lose
  `attributes.host_id` and `attributes.public_host`, and an entry whose host is
  disabled but whose declaration is enabled now projects enabled.
- **Build the bare-metal publication view from its declaration alone.** The view
  requires the declaration to name a host, not a registered host record. A
  declaration with an enabled publication and no host projects without the view
  rather than failing the site's whole projection generation.
- **Declare, per fulfillment provider, whether delivery needs a host**, collect
  those declarations at provisioning composition, and inject the result as plain
  data into site admission and settlement scheduling.
- **Refuse admission and placement** of a Physical Resource whose declaration
  names no host when its pool's provider needs one. It is an ineligible
  candidate — the ordinary capacity-refusal class — not a new error.
- **Make dispatch fail closed on an unregistered host.** Execution inventory is
  rendered only from the registered host record the settlement resource names.
  Remove the static-inventory fallback from every execution path; the configured
  inventory file remains a startup seed input only.
- **Resolve the VM tenant-facing address from the host record**: its
  `public_host`, else its `ssh_host`. Document the fallback in the VM quickstart,
  and document the inventory file as a seed input in both quickstarts and in
  `DEPLOYMENT_AND_CONFIG.md`.
- **Delete the unused legacy `ProvisioningService` and the static-inventory
  readers** left without a caller.

## Capabilities

### Modified Capabilities

- `site-capacity`: the resource-pool projection is built from declarations
  alone; naming a host is optional for a declaration; admission applies a
  composition-supplied host requirement.
- `fulfillment`: providers declare whether delivery needs a host; scheduling
  rechecks it before any placement effect.
- `physical-provisioning`: execution inventory comes only from the registered
  host record; the tenant address falls back to the record's connection
  address; the bare-metal publication view is built from its declaration.

### New Capabilities

None.

## Non-Goals

- Do not change what a capacity declaration contains, how it is administered, or
  how it is imported. `capacity-resource-administration` owns all three.
- Do not add a backing property to the projection or filter by backing.
  `pool-declared-advertisement-and-backing` declares backing and
  `unbacked-listing-publication` consumes it, including the registry filter that
  lets buyers separate unbacked listings. Unbacked listings never reach
  admission, scheduling, or dispatch, so the host requirement never applies to
  them.
- Do not change what disabling a host means. No new admission or placement
  against a disabled host, while dispatch still honours existing assignments and
  teardown still works, is owned by `pools-6-fair-scheduling-policy`.
- Do not reconcile the bare-metal storefront's second copy of host identity in
  its publication configuration. `pools-8-capacity-projection-and-listing-hints`
  owns retiring independently authored host fields from publication.
- Do not introduce a provider whose delivery needs no host. None exists or is
  planned in this campaign; the declaration seam exists so the kit does not
  assume one.
- Do not catch a declaration in a host-requiring pool that names no host at
  registration or document validation. The failure occurs at reservation.

## Impact

- **Provisioning service:** `capacity_inventory` (projection), `composition`
  (host-requirement collection), container wiring.
- **`kit/resource-pools`:** the fail-closed host-requirement predicate.
- **`kit/site`:** admission candidate eligibility.
- **`kit/fulfillment`:** provider protocol declaration and scheduler candidate
  eligibility.
- **VM provisioning adapter:** job inventory resolution, tenant-address
  resolution, static-inventory readers, a possibly unused legacy
  `ProvisioningService`.
- **Bare-metal provisioning adapter:** provider declaration, required host
  validation.
- **Wire:** the resource-pool projection's generic per-entry `attributes` lose
  `host_id` and `public_host`. No projection consumer reads either. The
  projection's revision and digest advance once on upgrade.
- **Behaviour:** a declaration naming no host becomes visible to storefronts; in
  a host-requiring pool it is refused at reservation rather than stranded after
  scheduling.
- **Unchanged:** capacity declaration administration, pool declarations,
  unbacked-listing handling, fairness policy, and the capacity-bucket projection,
  which already enumerates declarations.

## Dependencies and Related Changes

- **Depends on `capacity-resource-administration`** — archived 2026-09-21. Its
  shape-versus-admission wording in
  `openspec/specs/site-capacity/spec.md#requirement-operator-administered-capacity-declarations`
  is the definition this change relies on.
- **Prerequisite for `unbacked-listing-publication`**, whose design names this
  change as what keeps placement and dispatch fail-closed for a declaration
  with no host.
- **Hands off to `pools-6-fair-scheduling-policy`** the disabled-host admission
  and placement rule, both halves.
- **Hands off to `pools-8-capacity-projection-and-listing-hints`** the
  bare-metal storefront's duplicated host identity.
- **Coordinates with `contain-embedded-host-key-material`**, which changes
  `write_inventory` and `render_inventory_ini` in the same adapter files this
  change edits for inventory resolution. There is no ordering dependency; each
  change edits different functions.
- **Coordinates with `pools-9-retire-local-physical-authority`**, which retires
  adjacent storefront-local physical tables. This change reads none of them.
- `publish-multidimensional-listing-shape` consumes projected dimensions and is
  unaffected.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the host requirement is a
      layer-rechecked authorization like pool offering modes, and "Resource
      pools" states that repository-wide rule.
- [x] Existing subsystem specification — `site-capacity`, `fulfillment`,
      `physical-provisioning`, and the `site-capacity` companion
      `architecture.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

Operator documentation:
- `docs/seller-quickstart.md` states the VM tenant-address fallback.
- `docs/seller-quickstart.md` and `docs/bare-metal-seller-quickstart.md` state
  that the mounted inventory file is a seed input.
- `docs/development/DEPLOYMENT_AND_CONFIG.md` says a host added after first boot
  must be imported rather than edited into the file.
- `docs/development/TESTING.md` records the host-requirement enforcement matrix
  beside the offering-mode one.

### Knowledge to promote

- The resource-pool projection is built from capacity declarations alone and
  carries no host connection identity —
  `openspec/specs/site-capacity/spec.md`.
- Naming a host is optional for a declaration —
  `openspec/specs/site-capacity/spec.md`.
- Admission refuses a Physical Resource whose declaration names no host when its
  pool's provider needs one — `openspec/specs/site-capacity/spec.md`.
- Providers declare whether delivery needs a host; scheduling rechecks it —
  `openspec/specs/fulfillment/spec.md`.
- Each execution layer rechecks the host requirement, as it does pool offering
  modes — `docs/development/ARCHITECTURE.md#resource-pools`.
- Execution inventory comes only from the registered host record; the static
  file is a seed input — `openspec/specs/physical-provisioning/spec.md`.
- The tenant address falls back to the host record's connection address —
  `openspec/specs/physical-provisioning/spec.md`, plus the VM quickstart.
- The bare-metal publication view is built from its declaration —
  `openspec/specs/physical-provisioning/spec.md`.
- The host is joined at dispatch only, and why —
  `openspec/specs/site-capacity/architecture.md`.
