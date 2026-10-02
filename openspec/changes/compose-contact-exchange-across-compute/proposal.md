## Why

`contact-exchange.v1` is composed on bare metal only. Nothing about the mechanism
is bare-metal-specific: its package-boundary test asserts it imports nothing
beyond `market_core`, `market_identity`, `market_settlement_runtime`, and
pydantic — no domain, no provider, no framework.

What is bare-metal-specific is the composition glue that installs accepted-state
interpretation into the reveal service. Reading it, almost none of that is
bare-metal either: it loads a negotiation thread, checks its terminal state,
validates a settlement plan carrying one obligation, re-derives `obligation_ref`,
and drives the obligation to collected. The only domain-specific parts are the
persistence client and its two payload methods.

Composing a second domain by copying that glue would put a second implementation
of mechanism-shaped logic in a domain, against the established rule that an
extracted concern leaves no domain-local copy and that domains retain only the
values and hooks that instantiate a kit mechanism. Doing it once is duplication;
doing it for every compute domain is a maintenance surface where the mechanism's
own invariants get re-derived inconsistently.

The same holds one layer out. Bare metal's seller-side delivery dispatch and its
buyer's introduction commands are also domain-local and also almost entirely
domain-neutral, so composing VM by copying them would duplicate them too.

And one value is wrong for the shape Goal 7 needs. The seller's contact is a single
storefront-wide setting, so a storefront publishing for several seller sites would
reveal one seller's contact on another seller's deal, and would deliver every
buyer's contact to the same destinations whichever seller the deal was with.

`docs/development/ROADMAP.md` assigns both gaps to this change: contact exchange
composed beyond bare metal (Goal 6), and the per-origin contact Goal 7's
multi-seller introductions depend on.

## What Changes

- Promote the domain-neutral part of the introduction composition glue out of the
  bare-metal storefront into `kit/contact-exchange`: accepted-state interpretation,
  obligation-ref re-derivation, the obligation drive sequence, and the read an
  operator's re-delivery takes, with three domain reads injected (the negotiation
  thread, the settlement obligation, and the agreement's origin).
- Leave the bare-metal storefront holding only its persistence client, its
  configuration carrier, and its route bindings, matching how it composes every
  other kit mechanism.
- Resolve the seller's contact payload per listing origin rather than per
  storefront. `ContactSettlementConfig.contact_payload` is one static value for a
  whole storefront, which is coherent only at one seller per storefront; Goal 7
  publishes listings from several seller sites through one storefront, where it
  would reveal the wrong seller's contact details. A new origin-keyed form,
  `[Settlement.contact.origins.<origin>]`, treats origins as opaque strings the
  domain supplies; the storefront-wide form remains as shorthand for a storefront
  with exactly one origin. A listing whose origin has no contact publishes no
  contact-exchange option, and a reveal whose origin has none is refused before
  anything is persisted. Resolution lives in the promoted composition, so it
  applies to bare metal and VM alike.
- Extend `kit/delivery` with named sink instances and an origin routing table, so
  a storefront publishing for several sellers delivers each reveal to its own
  origin's destinations, and move the seller-side background dispatch and
  re-delivery out of bare metal into it. Existing `[Delivery]` sections keep
  working unchanged.
- Compose the mechanism in the VM storefront, the one remaining compute-family
  domain, with retention, introduction routes, and delivery. Bare metal already
  composes it; API credits is a separate market family with its own registry
  schema identity and is out of scope.
- Promote the buyer's `introduce` and `introduction [--deliver]` command bodies
  into `core_buyer` as a group each domain buyer mounts, and give the VM buyer
  `request-introduction`, `introduce`, and `introduction`, matching the typed
  clients bare metal's buyer already uses.
- State normatively that accepted-state interpretation, seller-side delivery
  dispatch, and the buyer's introduction commands each have one implementation,
  and that a composing domain supplies persistence, configuration, and route
  bindings rather than lifecycle logic.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: accepted-state interpretation and the obligation
  drive sequence have one implementation; a composing domain supplies persistence
  and configured values; the seller's contact payload is resolved from a listing's
  origin, with publication and reveal refusing an origin that has none.
- `introduction-delivery`: delivery is available to every composing domain through
  one seller-side dispatch; sinks are named instances; seller-side delivery routes
  by the listing's origin.
- `buyer-orchestration`: the buyer's introduction commands have one core-owned
  implementation every domain buyer mounts.

### New Capabilities

None.

## Non-Goals

- Do not give the mechanism kit a framework, HTTP client, or foreign-mechanism
  dependency. Its package boundary is asserted by test and is part of why the
  mechanism composes cleanly. The promoted glue lands in the kit and takes both
  domain reads as injected Protocols, so it adds no persistence type; the boundary
  test's deny list is unchanged and `uuid` is the only permitted root added.
- Do not change the reveal surface, its authentication, its idempotency, or the
  option shape.
- Do not give `kit/delivery` a mechanism dependency or the mechanism kit a
  delivery dependency; each reads the other's shapes rather than importing it.
- Do not check an origin's contact at acceptance. The reveal is the safety
  guarantee and publication catches the standing misconfiguration; see
  `design.md` decision 5.
- Do not edit shared end-to-end helpers or fixtures, which are under refactor;
  system evidence is new scenario modules, with lane configuration changed only
  where a named task needs it.
- Do not build per-deal contact aliasing. Making the payload resolvable is the hook
  aliasing would also need, but choosing an alias per deal is a separate concern.
- Do not add scalar participation. The mechanism declines it, and
  `unbacked-listing-publication` publishes rates as listing attributes precisely
  so that decision holds.
- Do not couple composition to backing. A capacity-backed listing may settle by
  introduction and an unbacked listing may settle by another mechanism; this
  change must not assume either.

## Impact

- Affected code:
  - `kit/contact-exchange`: a new composition module, the origin-keyed
    configuration and its resolver, the option builder's origin check, the reveal
    service's per-agreement contact resolution, and one boundary-test line.
  - `kit/delivery`: named instances, the origin routing table, and the seller-side
    background dispatcher and re-delivery.
  - `core/buyer`: the introduction command group.
  - The bare-metal storefront: its introduction glue and delivery module reduce to
    persistence, configuration carrier, and route bindings; its publication passes
    the listing origin.
  - The bare-metal buyer: mounts the core introduction commands.
  - The VM storefront: settlement composition, introduction persistence, migration
    tuple, introduction routes, delivery wiring, retention wiring (the sweep loop,
    the admin deletion routes, and the readiness disclosure
    `contact-payload-retention` requires of every composing storefront), and the
    listing origin passed to publication.
  - The VM buyer: `request-introduction`, plus the mounted core commands.
  - `e2e-tests`: new scenario modules and, where named, lane configuration.
- Affected specification: `openspec/specs/contact-exchange-settlement/spec.md`,
  `openspec/specs/introduction-delivery/spec.md`,
  `openspec/specs/buyer-orchestration/spec.md`.
- Affected documentation: `docs/development/DEPLOYMENT_AND_CONFIG.md`'s
  contact-exchange section, for the origin-keyed form and delivery routing.
- Not affected: the mechanism kit's registration identity, option shape,
  retention, or migrations; the reveal's wire shape.

## Dependencies and Related Changes

- **Owns the VM half of `publish-indicative-listing-rates`' unbacked-supply system
  evidence** (its 7.13, carried in task 6.4): the buyer query that returns backed and
  unbacked VM listings together is bounded by asking rate, naming asset and period,
  and excludes a listing publishing no rate. That change proved the asking-rate path
  on backed supply and through the registry for a listing whose only option is a
  rateless introduction; what it could not supply is the unbacked VM listing this
  change first makes publishable.
- **Owns the system evidence for `unbacked-listing-publication`** (tasks 6.4 and
  6.5). That change made unbacked listings derivable, bound, and published through
  the storefront's loop, but VM composes no settlement option an unbacked listing
  may publish until this change composes introduction, so no stack could show one
  to a buyer. The scenarios live here, with the flow that first makes them
  runnable.
- **Depended on `contact-payload-retention`**, now archived. Composing the
  mechanism more widely multiplies the deployments holding contact payloads, so
  retention had to exist first. That change implemented retention in the kit and
  composed it into bare metal; this change composes it into VM with the mechanism.
- **Depended on `pass-through-storefront-config`**, now complete, which makes the VM storefront chart
  pass service configuration through instead of enumerating each mechanism. On its
  baseline this change's settlement and delivery sections deploy by Helm values once
  the contact mechanism is registered and the generated values schema regenerated,
  with the generator extended for `kind`-dependent delivery sinks.
- **Task 6.5 is blocked on `bare-metal-mock-provisioned-deal`**'s two-storefront,
  two-site topology and is redesigned from it.
- **Runs alongside `bare-metal-mock-provisioned-deal`**, which is moving bare-metal
  negotiation onto the kit runtime and deal controls into kit route services. This
  change edits the bare-metal storefront's introduction, delivery, publication, and
  route wiring, not its negotiation or acceptance path; whichever lands second
  rebases onto the other.
- No longer coupled to `bare-metal-and-credits-domain-stacks` or
  `kit-storefront-composition-seam` for placement. Those own where kit-owned
  *storefront* runtime sits; the promoted glue is mechanism-shaped and lands in the
  mechanism kit, so it does not need their seam. `kit/storefront` was rejected as
  a home because it declares hard Alkahest dependencies — see `design.md`.
- Builds on `unbacked-listing-publication`, which has landed and is archived: its
  per-mechanism fulfillment declaration is what task 3.1 extends. Its system evidence
  moved here (6.4, 6.5), because an unbacked VM listing publishes only settlement
  options the VM composition does not fulfil through capacity, and contact exchange
  is the first such option. When task 3.1 registers the mechanism, the VM composition's per-mechanism
  fulfillment declaration names it as not fulfilling through capacity. Per-origin contact resolution is what makes
  Goal 7's multi-seller value claim true, though, so Goal 7 is not complete for
  introductions until it lands — see `design.md`.
- **Blocks `unbacked-bare-metal-listings`**, which settles unbacked bare-metal
  introductions through the composition this change promotes and needs the per-origin
  payload. Bare metal is Goal 7's primary target domain; its unbacked system evidence
  is owned by that change, and this change's 6.4 and 6.5 remain the VM half.
- Discharges the remaining half of the recorded open gap for cross-domain
  contact-exchange composition in `docs/development/ROADMAP.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — the settlement-configuration section's
      delivery paragraph describes delivery as storefront-wide; it gains per-origin
      routing and the per-origin contact. Re-confirm the composition-from-kit
      principle needs no change.
- [x] Existing subsystem specification —
      `openspec/specs/contact-exchange-settlement/spec.md`,
      `openspec/specs/introduction-delivery/spec.md`, and
      `openspec/specs/buyer-orchestration/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/DEPLOYMENT_AND_CONFIG.md` also changes: its contact-exchange
section documents the origin-keyed form and its startup refusals, and delivery
routing.

### Knowledge to promote

- Accepted-state interpretation and the obligation drive sequence have one
  implementation; a composing domain supplies persistence and configured values —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- The seller's contact is resolved per opaque origin, guarded at publication and
  reveal — `openspec/specs/contact-exchange-settlement/spec.md`; configuration in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Seller-side delivery has one implementation, sinks are named instances, and
  delivery routes per origin — `openspec/specs/introduction-delivery/spec.md`;
  `docs/development/ARCHITECTURE.md`'s settlement configuration section.
- The buyer's introduction commands are core-owned and domain-mounted —
  `openspec/specs/buyer-orchestration/spec.md`.
