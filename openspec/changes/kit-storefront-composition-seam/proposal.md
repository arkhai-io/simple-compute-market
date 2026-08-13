## Why

The architecture's layering is core for what applies to every domain, kit for composable
functionality many domains share, and the domain layer for instantiating and configuring
kit. The storefront role does not follow it: the cross-cutting machinery a storefront
needs lives in the domain layer, so each domain reimplements it.

Measured 2026-08-06 across the eight cross-cutting storefront concerns:

| Concern | VM | API credits | Bare metal |
|---|---|---|---|
| `sync_negotiation` | 914 | 609 | — |
| `settlement_jobs` | 368 | 274 | — |
| `capacity_client` | 556 | 217 | — |
| `failure_policy` | 392 | 182 | — |
| `claims_runtime` | 224 | 128 | — |
| `publication_service` | 215 | 193 | — |
| `negotiation_watchdog` | 138 | 110 | — |
| `alkahest_service` | 65 | 58 | — |

Roughly 2,870 lines against 1,770 — two parallel implementations differing mainly in
which codecs they call. Bare metal has none of them, which is why its storefront is
1,930 lines against the VM storefront's 14,408: not simpler, incomplete.

The cost compounds. Every defect fixed in one copy stays live in the other, and every
new cross-cutting capability must be built once per domain or silently skip the domains
that lack it.

This change does not extract the machinery. It establishes the seam that extraction
lands on, and proves it with the two smallest concerns — the ones whose duplication is
least arguable — before the 914-line one.

## What Changes

- Define where a kit-owned storefront runtime sits in the layering, what a domain
  supplies to it, and how a domain composes it, extending the injected-contract shape
  `storefront-domain-parameterization` establishes.
- Move `negotiation_watchdog` and `alkahest_service` into kit and compose all three
  domains onto them, removing both domain-local copies rather than leaving one behind.
- Give bare metal these two concerns by composition, which it does not have today.
- Establish the pattern each later extraction follows: kit owns the mechanism, the
  domain supplies codecs and configuration, and no domain-local copy of an extracted
  concern survives the change that extracts it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: cross-cutting storefront runtime is kit-owned and composed by a
  domain, rather than reimplemented per domain; a concern moved into kit leaves no
  domain-local implementation behind.

## Non-Goals

- Do not extract negotiation, settlement, capacity, or publication. Those are the three
  changes that follow, and attempting them here is what would make this change
  unreviewable.
- Do not change any observable behavior. A domain's negotiation timeouts, watchdog
  intervals, and chain client construction must behave identically before and after.
- Do not restructure domain package layouts. A composed domain gets small on its own;
  relocating directories for tidiness is churn with no capability behind it.
- Do not build the bare-metal deployable stack or e2e coverage —
  `bare-metal-and-credits-domain-stacks` delivers those once the concerns exist.
- Do not change `core`. This is kit-layer work; core keeps carrying only what applies to
  every domain.

## Impact

- Affected code: new kit modules for the two concerns; `domains/vms/storefront`,
  `domains/apicredits/storefront`, and `domains/bare_metal/storefront` composition roots
  and their removed local copies.
- Affected tests: kit unit suites for the extracted concerns; each domain's suites for
  behavior preservation; the shared conformance path.
- Affected packaging: a kit package gains modules; domain wheels lose them. Build
  targets and Dockerfile wheel refresh entries follow.
- Not affected: core, provisioning, registry, wire contracts, persistence, deployment
  topology.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the kit-layer description, on what the
      storefront role composes rather than implements.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Cross-cutting storefront runtime is kit-owned and composed, and an extracted concern
  leaves no domain-local implementation — `openspec/specs/market-composition/spec.md`.
- The seam's shape: what kit owns, what a domain supplies —
  `openspec/specs/market-composition/architecture.md`.

## Dependencies and Related Changes

- Depends on `storefront-domain-parameterization`, whose injected-contract shape this
  seam extends. Extracting a concern that reaches a contract from module scope would
  move the problem into kit.
- Prerequisite for `kit-owned-negotiation-runtime`,
  `kit-owned-settlement-runtime`, and `kit-owned-capacity-and-publication`, each of
  which lands on this seam.
- `bare-metal-and-credits-domain-stacks` consumes all four.
- Independent of every Goal 1, 2, 3, and 5 change; touches no capacity, negotiation, or
  settlement behavior.
