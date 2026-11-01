## Why

A registered host has an `enabled` flag, and disabling a host is how an operator
excludes it from new work: the host authority describes `disable_host` as
excluding a host from new work while keeping it resolvable for job history.

Only job submission reads the flag. A fulfillment's create refuses a disabled
host, while a teardown or an operator's job does not
(`openspec/specs/physical-provisioning/spec.md#requirement-jobs-are-submitted-against-a-registered-host`).
Site admission and settlement scheduling never read it. So a disabled host's
capacity declarations stay on sale: a claim is admitted and scheduled onto the
disabled host, and its create's dispatch is then refused and retried until an
operator re-enables the host. The operator who disabled a host to keep work off
it has kept nothing off it; they have turned its sold capacity into deliveries
that cannot happen.

Two rules explain why the flag has no reader before dispatch, and neither is a
reason for this behaviour:

- Site admission does not read host records. It references a host only by
  `host_id`, and checks a named host's registration at dispatch, not at
  admission
  (`openspec/specs/site-capacity/spec.md#requirement-admission-applies-the-pool-providers-host-requirement`).
- The site's resource-pool projection is built from capacity declarations alone,
  and a declaration naming a disabled host projects enabled
  (`openspec/specs/site-capacity/spec.md#requirement-the-resource-pool-projection-is-built-from-capacity-declarations`).
  This keeps the site from owning provisioning connection information.

Those rules separate authorities. They do not require that disabling a host
leave its capacity sellable, and the behaviour was recorded as a defect when it
was found: disabling a host should keep new deliveries off it at admission.

## What Changes

- Disabling a registered host keeps new deliveries off it: site admission (probe
  and reserve) and settlement scheduling treat a capacity declaration naming a
  disabled host as an ineligible candidate, refused in the ordinary
  capacity-refusal way. Re-enabling the host makes it eligible again.
- The site learns which hosts are disabled without owning host records or
  connection information. The provisioning composition already supplies the
  site and the scheduler a per-provider host requirement as plain data; how host
  eligibility reaches them is decided in design.
- Work already admitted or running on a host is unchanged by disabling it: its
  teardown proceeds, as job submission already allows.
- Decide in design what publication does with a declaration naming a disabled
  host. While the projection keeps it enabled, a storefront keeps advertising a
  listing admission now refuses, which is the storefront's ordinary
  stale-projection case but a visible one. The alternatives include the
  projection carrying host eligibility, which amends the requirement that it
  reads no host records, and leaving publication as it is with the refusal
  reported.

## Capabilities

### Modified Capabilities

- `site-capacity`: admission eligibility of a declaration naming a disabled
  host, and possibly the resource-pool projection.
- `fulfillment`: scheduling eligibility of the same declaration.
- `physical-provisioning`: what disabling a host means, stated where the host
  authority is specified.
- `storefront-publication`, if design changes what publication does.

### New Capabilities

None.

## Non-Goals

- Do not change job submission: a fulfillment's create keeps refusing a disabled
  host, and teardown and operator jobs keep running against one.
- Do not make the site authority own host records or connection information.
- Do not change what a capacity declaration's own `enabled` field means, and do
  not disable declarations when their host is disabled: a declaration is the
  operator's statement of what sells, and the host's state is the host
  authority's.
- Do not change how host inventory enters the registry; that is
  `bring-host-inventory-under-definition-documents`.

## Impact

- `kit/site` admission (probe and reserve) and `kit/fulfillment` scheduling, and
  the provisioning service's composition that supplies them their host
  requirement.
- Possibly the site's resource-pool projection and storefront publication,
  depending on design.
- Operator documentation of what disabling a host does.

## Dependencies and Related Changes

- Independent: nothing must land first.
- Related to `bring-host-inventory-under-definition-documents`, which brings host
  inventory under the definition-document mechanism and retains a host the
  document stops naming rather than disabling it. That retention rests partly on
  this defect: while disabling a host leaves it sellable, a document that
  disabled the hosts it stops naming would turn a removed line into capacity
  that cannot be delivered. Once this change lands, that change's treatment is
  open to revisiting.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `site-capacity`, `fulfillment`,
      `physical-provisioning`, and possibly `storefront-publication`
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/ROADMAP.md`'s Goal 1 gap "Site admission and scheduling never
read a host record's enabled flag" is owned by this change and closes with it.

### Knowledge to promote

To be determined at design completion.
