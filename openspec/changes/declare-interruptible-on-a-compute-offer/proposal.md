## Why

`POST /api/v1/admin/deals/{escrow_uid}/interrupt` refuses unless the deal is
interruptible, and decides that by reading `offer_resource["interruptible"]`. No offer
can carry that key: `ComputeResource` declares no such field and pydantic drops
unknown ones, so the value is discarded at publish and the guard's first test is
false for every deal in the system.

Its second test — whether the buyer's escrow proposal is splitter-gated — is a
different question wearing the same name. A splitter-gated escrow describes how funds
are released, not whether the seller sold interruptible capacity. Treating one as
evidence of the other means an ordinary ERC20 deal can never be interrupted and a
splitter-backed deal always can, regardless of what either was sold as.

The gap surfaced in end-to-end run 31499398440, where two scenarios declared
`"interruptible": True` and were refused. Those scenarios have since been restructured
to trigger teardown through lease expiry, which is what ends a lease in production and
is the path that should carry the main teardown assertions. That removes the blockage
but not the defect: interruption remains a documented control that nothing can use.

Interruptibility is a commercial property of an offer. A buyer choosing between spot
and on-demand capacity is choosing exactly this, and it belongs in the listing the
buyer agrees to rather than being inferred from escrow mechanics.

## What Changes

- Add `interruptible: bool = False` to `ComputeResource`, so a seller can publish
  interruptible capacity and a buyer can see it before agreeing.
- Keep the splitter-gated proposal as a separate, additional condition rather than a
  proxy for the field, and state at the guard why both exist: one is what was sold, the
  other is what the escrow permits.
- Add an end-to-end scenario that publishes an interruptible listing, agrees a deal,
  interrupts it, and asserts the same durable teardown convergence the expiry path
  asserts. This is the case the field exists for, and it is currently untested.
- Default `False`, so an offer that says nothing is not interruptible. Silence should
  not sell preemptible capacity.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: a compute offer may declare itself interruptible, and that
  declaration is part of the published listing.
- `vm-fulfillment`: a deal is interruptible when its offer said so, independently of the
  escrow's splitter posture.

## Non-Goals

- Do not make interruptibility negotiable per round. It is a property of the offer, fixed
  at publish; a buyer who wants non-interruptible capacity chooses a different listing.
- Do not change pricing or policy behaviour. Whether an interruptible offer should price
  differently is a seller's decision, and no policy in this repository reads the field.
- Do not remove the splitter-gated condition. It is a real second route and removing it
  would change behaviour for deals that rely on it.
- Do not re-point the full-deal scenarios back at interruption. Lease expiry is the
  production teardown trigger and should stay the main path under test.

## Impact

- **Affected code:** `domains/vms/domain/src/arkhai_vms/listing_models.py`
  (`ComputeResource`), the offer projection in the VM storefront's listing adapter, and
  `_deal_is_interruptible` in `admin_controller`.
- **Affected tests:** VM domain model tests, storefront unit tests for the interrupt
  guard, and a new end-to-end scenario.
- **Wire compatibility:** additive and optional. An existing offer without the key parses
  as `False`, which matches how such a deal behaves today.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`
      for the published field, `openspec/specs/vm-fulfillment/spec.md` for the guard
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A compute offer declares its own interruptibility, and a deal's interruptibility comes
  from what was sold rather than from the escrow's splitter posture.

## Dependencies and Related Changes

- `compose-domain-wheels-and-policies` restructured the two full-deal scenarios onto lease
  expiry, which is what unblocked their teardown stages without this change. This change
  covers the control those scenarios stopped using.
- `revalidate-deal-requirements-at-scheduling` concerns categorical requirements not being
  re-checked at scheduling. Adjacent in shape — an attribute agreed at negotiation not
  being honoured later — but a different attribute and a different stage.
