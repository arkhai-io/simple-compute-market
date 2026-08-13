## Why

Acquiring a capacity hold costs a buyer two signed HTTP requests and nothing else.
Nothing in the negotiation path gates hold placement on funds, an escrow, or any chain
interaction; there is no rate limiting anywhere in the storefront; there is no
per-buyer concurrency limit on negotiations; and a fresh buyer address is free to mint,
so per-identity throttling would not help either.

The consequence is that a single actor can hold a storefront's entire sellable
inventory indefinitely, at no cost, by negotiating, accepting, and never settling. Every
legitimate buyer is denied for as long as the attacker keeps the loop running.

Shortening the hold window does not fix this. The fraction of capacity an attacker holds
is bounded by their request rate, not by the TTL: holding everything continuously needs
roughly *reservable slices ÷ TTL* requests per second, so a shorter window only tightens
the attacker's loop while degrading legitimate settlement. The shipped default of 900
seconds and a hypothetical 10-second default are equally exploitable.

Both the VM and API-credits storefronts ship this default.

## What Changes

- Ship `capacity.hold_ttl_seconds = 0` as the default for both storefronts, so no
  capacity is held before the buyer's escrow settles. Settlement's existing atomic
  reserve — already implemented, already the documented fallback — becomes the only
  path by which capacity becomes exclusive.
- Record the reasoning in the settings themselves, as a security posture rather than a
  performance trade. The existing comment presents 0 as a latency/contention choice,
  which is how the vulnerable default survived.
- Correct operator-facing guidance that instructs sellers to enable holds.
- Keep the local end-to-end profiles at a non-zero value deliberately, so the two-phase
  reserve path stays under test coverage while production ships safe.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: capacity is not held before settlement unless holding is
  compensated, and a configuration that grants unfunded exclusivity is not a shipped
  default.

## Non-Goals

- Do not remove the two-phase reserve implementation. It is correct and becomes safe to
  re-enable once holds are billed; deleting it would have to be rebuilt.
- Do not build hold billing — `billable-capacity-reservations` owns that and is what
  makes a non-zero default defensible again.
- Do not add rate limiting or per-identity caps. They target identity, identity is free,
  and they would penalize a legitimate buyer without stopping an attacker.
- Do not change the settlement-time reserve, admission, matching, or scheduling.
- Do not change the local e2e profiles' behavior; their override is deliberate and
  keeps the disabled path covered.

## Impact

- Affected configuration: `domains/vms/storefront/src/market_storefront/settings.toml`
  and `domains/apicredits/storefront/src/apicredits_storefront/settings.toml` defaults;
  annotations on `storefront.bob.toml` and `storefront.credits.toml` recording why they
  override; `docs/cookbooks/vllm-apicredits-seller.md`.
- Affected behavior: a buyer whose escrow settles may now find the capacity taken and
  need a refund. This is the accepted cost — it affects one deal at a time and has a
  recovery path, against a vector that denies every buyer at once.
- Affected tests: any suite asserting a hold exists after acceptance under default
  configuration. `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`
  parameterizes the TTL and should be unaffected, but this needs checking rather than
  assuming.
- Not affected: the two-phase reserve code, settlement's commit-or-reserve-fresh
  fallback, admission semantics.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the capacity-reservation section, on when
      capacity becomes exclusive in a deal's lifecycle.
- [x] Existing subsystem specification — `openspec/specs/negotiation-protocol/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Unfunded exclusivity is not a shipped default; capacity is held before settlement only
  where holding is compensated — `openspec/specs/negotiation-protocol/spec.md`.
- Why shortening the hold window is not a mitigation — this change's `design.md`.

## Dependencies and Related Changes

- Reversed by `billable-capacity-reservations`, which makes a non-zero default
  defensible by charging for held time. That change should restore a non-zero default as
  part of its own work.
- `negotiation-time-capacity-hold` moves holds *earlier*, the opposite direction, and is
  correctly sequenced behind billing.
- `negotiation-capacity-feasibility-probe` partially offsets this change's cost: a buyer
  learns feasibility during negotiation rather than discovering it after payment, though
  it does not remove the race.
- Independent of `capacity-reservation-lifecycle-hardening`.
