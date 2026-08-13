## Why

**Rewritten 2026-08-06.** The original change proposed a 2×2 storefront-to-site topology
proving both one-storefront/many-sites and one-site/many-storefronts. Two things
invalidated it. Multi-domain storefront composition supersedes separately composed
single-domain storefronts, collapsing one axis; and there are no plans to support
many-to-many storefront-to-site ownership, so the other axis proves a capability the
product does not want. Re-grounding the rest against current code found that most of what
the change would have *implemented* has since shipped, leaving a smaller change that is
almost entirely proof. The original documents are preserved in Git history; completed
prerequisite evidence is preserved in `tasks.md`.

What has shipped since the original was written:

- **Site-pinned claim routing with no fallback** — implemented in
  `AggregateCapacityClient.reserve` and already promoted to
  `storefront-publication`'s "Site-pinned claim routing" requirement, with evidence.
- **Cross-mode conflict rejection** — implemented in `kit/site` through
  `allocation_mode`, and normative as `site-capacity`'s "Cross-mode physical accounting".
- **Concurrent VM and bare-metal adapters in one provisioner** — implemented through
  `compose_adapter_bundles(vm_bundle=..., bare_metal_bundle=...)`.
- **Explicit executor identity** — `pool-declared-offering-modes` supplies the requested
  mode explicitly and removes both implicit `"vm"` fallbacks.

What remains is what a proof change is for: none of it has ever been exercised together,
against running services, across more than one authority. Every end-to-end scenario in
the repository is a single-site VM deal.

## What Changes

- Add a deterministic topology of one multi-domain compute storefront against two
  provisioning authorities, exercising VM and bare-metal lifecycles at each — four
  domain-to-authority edges through reservation, scheduling, fulfillment, result
  observation, teardown, and capacity restoration.
- Verify durable selected-site ownership survives storefront restart and that no
  state-changing operation reaches another authority after reservation.
- Verify cross-mode conflicts on one Physical Resource are rejected before executor work
  in both directions, within an authority.
- Verify no default executor is ever substituted: a missing, unknown, or conflicting
  executor identity fails before adapter or infrastructure work.
- Verify identities that are only authority-local — pool, resource, and access aliases —
  are never treated as globally unique across authorities.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: a deterministic multi-authority topology exercises every
  domain-to-authority edge of a multi-domain storefront through the full lifecycle,
  including restart, isolation, and cross-mode rejection, without timing sleeps.

## Non-Goals

- **Do not prove or support many-to-many storefront-to-authority ownership.** Removed
  2026-08-06: there are no plans to support it, one authority binds to one storefront
  today, and proving it would require per-storefront identity that does not exist.
- ~~Do not host VM and bare-metal market contracts in one storefront process.~~
  **Superseded 2026-08-06** by `multi-domain-storefront-composition`; this change now
  depends on that composition rather than excluding it.
- Do not implement selected-site routing, cross-mode admission, adapter composition, or
  explicit executor identity. All four are implemented or owned elsewhere; this change
  proves them together.
- Do not own the legacy-row migration for durable reservations lacking executor
  identity. Moved 2026-08-06 to `pool-declared-offering-modes`, which removes the
  fallback those rows depend on and should own the migration for what depended on it.
- Do not add another resource domain, a third provisioning API, or cross-seller capacity
  markets.
- Do not use real hardware timing as acceptance evidence, or add proof-only production
  APIs.
- Do not prove authenticated reverse delivery. Pull reconciliation is the correctness
  baseline; push remains `replace-polling-with-authenticated-push`'s.

## Impact

- Affected tests and topology: one multi-domain storefront application, two compute
  provisioning services with both adapter bundles, site-capacity fixtures, fulfillment
  clients, and lifecycle result polling.
- Runtime behavior changes only where the proof exposes a defect in an existing
  capability; such a fix belongs to the owning capability rather than to a test-only
  branch.
- Deployment and test configuration gains explicit multi-authority bindings for the
  deterministic scenario.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the accepted topology map.
- [x] Existing subsystem specification — `openspec/specs/test-compatibility/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- A deterministic multi-authority topology proves every domain-to-authority edge,
  including restart and cross-mode rejection — `openspec/specs/test-compatibility/spec.md`.
- The accepted topology map — `docs/development/ARCHITECTURE.md`.

## Dependencies and Related Changes

- Depends on `multi-domain-storefront-composition` for the storefront under test, and on
  `market-platform-bare-metal-10-storefront-composition` and `bare-metal-buyer-domain`
  for a complete bare-metal deal path.
- Depends on `pools-7-storefront-fulfillment-cutover` for durable selected-site
  scheduling, fulfillment status and result, restart recovery, and teardown.
- Depends on `pool-declared-offering-modes` for explicit executor identity and the legacy
  -row policy this change no longer owns.
- Complements `bare-metal-and-credits-domain-stacks`, which proves a complete deal per
  domain at one authority. This change adds the multi-authority dimension and should
  reuse its fixtures rather than build a parallel harness.
