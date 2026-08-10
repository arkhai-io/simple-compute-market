## Why

The synchronous negotiation runtime is the largest duplicated concern in the storefront
role: 914 lines in the VM storefront and 609 in the API-credits storefront, two
hand-maintained implementations of one protocol. Bare metal has no implementation at
all, which is a large part of why it cannot complete a deal.

What differs between the two copies is which codecs normalize a round, which policy hook
runs, and which configuration supplies timeouts. What is identical is the protocol
itself: round persistence, terminal-state handling, the accept chokepoints, and the
guards around them. That is the division the kit seam exists for.

The cost of leaving it duplicated is visible in this repository already. Round-zero
guards, hold placement, and shape rejection have each been added to the VM
implementation and not the other, so a capability that reads as "the market does X"
is really "the VM market does X."

The seam these land on is established by `kit-storefront-composition-seam`, along with
the rule this change follows: an extracted concern leaves no domain-local
implementation, and a domain that lacked it gains it by composition.

## What Changes

- Move the synchronous negotiation runtime (`sync_negotiation`) into the kit layer, with the domain supplying its contract, its
  configuration, and its domain-specific semantics.
- Compose all three domains onto the kit implementation and remove every domain-local
  copy in this change.
- Give bare metal these concerns, which it does not have today.
- Record, per concern, where the existing implementations already diverged and which
  behavior was chosen — silently adopting one is how an extraction becomes a behavior
  change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: The synchronous negotiation runtime is kit-owned and composed by a domain rather than
  reimplemented per domain.

## Non-Goals

- Do not change observable behavior for any domain. Where the copies disagree, the
  divergence is resolved deliberately and recorded, not absorbed.
- Do not extract concerns owned by the sibling extraction changes.
- Do not restructure domain package layouts.
- Do not build deployable stacks or e2e coverage —
  `bare-metal-and-credits-domain-stacks` delivers those.
- Do not change `core`, provisioning, registry, wire contracts, or persistence schemas.

## Impact

- Affected code: new kit modules; the three domains' composition roots and their removed
  local copies.
- Affected tests: kit unit suites for the extracted concerns; each domain's suites for
  behavior preservation.
- Affected packaging: kit gains modules, domain wheels lose them; build targets,
  Dockerfile refresh entries, and lockfiles follow.
- Not affected: core, provisioning, registry, wire contracts, persistence, deployment
  topology.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — re-confirm at implementation time; the
      kit-layer description is updated by `kit-storefront-composition-seam`.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- The synchronous negotiation runtime is kit-owned and composed —
  `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `kit-storefront-composition-seam` for the seam and the extraction rule.
- Sibling of the other extraction changes; independent of them and landable in any
  order among themselves.
- Consumed by `bare-metal-and-credits-domain-stacks`, which cannot deliver an
  end-to-end deal for a domain missing these concerns.
