## Why

The storefront-side capacity client and the publication runtime are duplicated across
the VM and API-credits storefronts — `capacity_client` at 556 against 217 lines and
`publication_service` at 215 against 193 — and absent from bare metal, which therefore
neither reserves capacity nor publishes listings.

Publication is close to identical between the two copies, which makes it the clearer
extraction. The capacity client is the more interesting one: the size gap suggests part
of VM's is genuine domain specificity rather than shared mechanism, and separating the
two is the substance of this change.

The seam these land on is established by `kit-storefront-composition-seam`, along with
the rule this change follows: an extracted concern leaves no domain-local implementation,
and a domain that lacked it gains it by composition.

## What Changes

- Move these concerns into the kit layer, with the domain supplying its contract, its
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

- `market-composition`: these concerns are kit-owned and composed by a domain rather than
  reimplemented per domain.

## Non-Goals

- Do not change observable behavior for any domain. Where the copies disagree, the
  divergence is resolved deliberately and recorded, not absorbed.
- Do not extract concerns owned by the sibling extraction changes.
- Do not restructure domain package layouts.
- Do not build deployable stacks or e2e coverage — `bare-metal-and-credits-domain-stacks`
  delivers those.
- Do not change `core`, provisioning, registry, wire contracts, or persistence schemas.

## Impact

- Affected code: new kit modules; the three domains' composition roots and their removed
  local copies.
- Affected tests: kit unit suites; each domain's suites for behavior preservation.
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

- These concerns are kit-owned and composed — `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `kit-storefront-composition-seam` for the seam and the extraction rule.
- Sibling of the other extraction changes; independent of them.
- Consumed by `bare-metal-and-credits-domain-stacks`, which cannot deliver an end-to-end
  deal for a domain missing these concerns.
