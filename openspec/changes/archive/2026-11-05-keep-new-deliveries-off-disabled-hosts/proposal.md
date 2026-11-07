## Why

A registered host has an `enabled` flag, and disabling a host is how an operator
excludes it from new work: the host authority describes `disable_host` as
excluding a host from new work while keeping it resolvable for job history.

On the delivery path only job submission reads the flag. A fulfillment's create
refuses a disabled host, while a teardown or an operator's job does not
(`openspec/specs/physical-provisioning/spec.md#requirement-jobs-are-submitted-against-a-registered-host`).
Site admission (probe, reserve, and resize), the site's rebind recheck, and
settlement scheduling never read it. So a disabled host's capacity declarations
stay on sale: a claim is admitted and scheduled onto the disabled host, and its
create's dispatch is then refused and retried until an operator re-enables the
host. The operator who disabled a host to keep work off it has kept nothing off
it; they have turned its sold capacity into deliveries that cannot happen.

A declaration naming a host that was never registered fails the same way: it is
admitted, because admission does not require the named host's registration
(`openspec/specs/site-capacity/spec.md#requirement-admission-applies-the-pool-providers-host-requirement`),
and its create then retries at dispatch. And a backed declaration naming no host,
in a pool whose provider needs one, is refused at admission but still projected
enabled, so its listing is published.

The projection does not help a storefront avoid any of these: it is built from
capacity declarations alone, and a declaration naming a disabled or unregistered
host projects enabled (site-capacity's requirement "The resource-pool projection
is built from capacity declarations", which this change replaces with
`openspec/specs/site-capacity/spec.md#requirement-the-resource-pool-projection-is-built-from-capacity-declarations-and-offers-only-a-usable-host`).

Those rules separate authorities. They do not require that a listing whose
delivery has no usable host be sold or published: such a listing is the same as a
listing with no host, and neither should appear.

## What Changes

- A declaration in a backed pool whose provider needs a host is offered only when
  it names a registered, enabled host. Offered means site admission (probe,
  reserve, resize), the site's rebind recheck, and settlement scheduling treat it
  as eligible, and both site projections show it enabled. A declaration without
  one is refused in the ordinary capacity-refusal way and projects as not
  enabled, so storefronts close its listings through their existing
  disabled-source rules and reopen them under their original identities when its
  host is enabled or registered.
- The rule does not apply in an unbacked pool, nor where the pool's provider needs
  no host.
- Admission no longer admits against a declaration naming a host with no
  registration.
- The site learns which hosts take new delivery through a seam the provisioning
  composition supplies and the ledger and the scheduler read in their own
  transaction. The site owns no host records or connection information.
- New placement never uses a host that cannot take delivery, including a
  reservation's own backing, so a pool-scoped hold is re-placed at scheduling or
  refused. An assignment already made keeps its host, and its create waits at
  dispatch; teardown and operator jobs are unchanged.
- This change takes the disabled-host rule over from
  `pools-6-fair-scheduling-policy`, whose proposal, design, and index row drop
  their claim to it at this change's closeout.

## Capabilities

### Modified Capabilities

- `site-capacity`: admission eligibility of a declaration with no usable host, and
  the projections' `enabled` for it, which projected-inventory consistency now
  admits.
- `fulfillment`: scheduling eligibility of the same declaration.
- `physical-provisioning`: what disabling a host means, and host inventory as
  connection identity narrowed to admit the ids of hosts taking new delivery.

### New Capabilities

None.

## Non-Goals

- Do not change job submission: a fulfillment's create keeps refusing a disabled
  or unregistered host, and teardown and operator jobs keep running against a
  disabled one.
- Do not make the site authority own host records or connection information.
- Do not change what a capacity declaration's own `enabled` field means, and do
  not disable declarations when their host is disabled: a declaration is the
  operator's statement of what sells, and the host's state is the host
  authority's.
- Do not change storefronts, the projection's wire shape, or the capacity event
  feed.
- Do not change how host inventory enters the registry, or the retention of hosts
  a host definitions document stops naming.
- Do not change scheduling policy beyond eligibility; fairness stays with
  `pools-6-fair-scheduling-policy`.

## Impact

- `kit/resource-pools`: the deliverable-host seam and the usable-host rule beside
  the host requirement.
- `kit/site`: admission, the rebind recheck, and one ledger read stating each
  declaration's offered state, from which the capacity-bucket projection and the
  advisory snapshot are built.
- `kit/fulfillment`: the scheduler's candidate filter and one read on its
  scheduling unit of work.
- `provisioning/compute`: the seam's implementation over the host registry, the
  resource-pool projection builder's input, taken from the ledger's offered read,
  and container wiring.
- Operator and deployment documentation of what disabling a host does.
- No wire, persistence, or deployment change.

## Dependencies and Related Changes

- Independent: nothing must land first.
- Takes over the disabled-host rule from `pools-6-fair-scheduling-policy`, which
  received it from `project-capacity-resources-without-hosts`.
- Answers `bring-host-inventory-under-definition-documents`'s revisit question:
  a host definitions document keeps retaining the hosts it stops naming, on the
  reason that hosts registered through the API must coexist with it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` (the resource-pools paragraph on the
      host requirement, restated; the listing principle itself stays in
      `site-capacity`'s architecture)
- [x] Existing subsystem specification: `site-capacity`, `fulfillment`,
      `physical-provisioning`
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/ROADMAP.md`'s Goal 1 gap "Site admission and scheduling never
read a host record's enabled flag" is owned by this change and closes with it.

### Knowledge to promote

Provisional permanent destinations, one bullet per decision in `design.md`:

- D1, pools-6 drops its claim to the rule: `openspec/changes/pools-6-fair-scheduling-policy/`
  proposal and design, and its row in `openspec/changes/README.md`.
- D2, host eligibility reaches the kit layers through a composition-supplied seam
  read in the caller's session: `openspec/specs/site-capacity/architecture.md`;
  `docs/development/ARCHITECTURE.md`'s resource-pools paragraph on the host
  requirement, restated to name the usable-host rule.
- D3 and D12, a backed declaration whose provider needs a host is offered only with
  a registered, enabled host: `openspec/specs/site-capacity/spec.md` (admission and
  projection requirements) and `openspec/specs/fulfillment/spec.md` (scheduling
  requirement), via the delta specs; and, for D12, the principle that a listing
  whose delivery has no usable host is the same as a listing with no host:
  `openspec/specs/site-capacity/architecture.md`, "Declared capacity and connection
  identity".
- D4, new placement never uses an unusable host and an existing assignment keeps
  its host: `openspec/specs/fulfillment/spec.md`, via the delta spec.
- D5, why projected `enabled` follows admission:
  `openspec/specs/site-capacity/architecture.md`, "Declared capacity and connection
  identity".
- D6, the seam and the rule beside the host requirement:
  `openspec/specs/site-capacity/architecture.md`; `docs/development/ARCHITECTURE.md`'s
  resource-pools paragraph on the host requirement.
- D7, a composition that supplies no report applies none:
  `openspec/specs/site-capacity/architecture.md`; `docs/development/ARCHITECTURE.md`'s
  resource-pools paragraph on the host requirement.
- D8, where the rule is applied and how a refusal answers:
  `openspec/specs/site-capacity/spec.md` and `openspec/specs/fulfillment/spec.md`,
  via the delta specs.
- D9, a change of host state emits no capacity event:
  `openspec/specs/site-capacity/architecture.md`, "Event privacy and convergence".
- D10, host definitions documents keep retaining unnamed hosts, on the remaining
  reason: `openspec/specs/physical-provisioning/architecture.md`, its retention
  paragraph restated; `docs/development/DEPLOYMENT_AND_CONFIG.md`'s host retention
  paragraph restated on the same reason.
- D11, what disabling a host means, and that a host record contributes nothing to
  a projection's capacity or attributes, admission, scheduling, and projection
  learning only the ids of hosts taking new delivery (with 11 F1):
  `openspec/specs/physical-provisioning/spec.md` and
  `openspec/specs/site-capacity/spec.md`, via the delta specs;
  `docs/operator-handbook.md`, the host-documents bullet "A host the document does
  not name is left as it is"; `docs/development/DEPLOYMENT_AND_CONFIG.md`, the host
  retention paragraph.
- 11 F2 and 21 F2, the ledger states each declaration's offered state in one read,
  from which every projection and the snapshot are built:
  `openspec/specs/site-capacity/spec.md`, via the delta spec;
  `openspec/specs/site-capacity/architecture.md`.
- The gap closes, and "Host records are used only where a connection is made" is
  restated: `docs/development/ROADMAP.md` Goal 1.
- Each layer's proof of the usable-host rule, the offered read, and the bare-metal
  publication stages: `docs/development/TESTING.md`, "Host Requirement Enforcement".
