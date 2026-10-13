## Context

Core and registry-client markers/config exist, but core typecheck fails and markers lack built-wheel verification. Storefront client, buyer, storefront, and registry packages expose public APIs without one declared support level. A single strictness cliff would encourage broad ignores and mix shell/framework noise with stable carrier contracts.

## Goals / Non-Goals

**Goals:** truthful typed-package markers; package-level ratchets; stable public contracts; CI/wheel evidence.

**Non-Goals:** immediate strict typing of every repository module or replacement of runtime conformance tests.

## Decisions

- A package receives `py.typed` only when its intended public modules pass its documented check and wheel tests confirm marker inclusion.
- Ratchet in order: restore core/registry-client; storefront client; buyer/core storefront public contracts; registry shell last.
- Centralize pragmatic defaults while allowing package-specific stricter overrides and narrow documented third-party exclusions.
- Treat exported carriers/protocols/client responses as higher priority than CLI/FastAPI composition internals.
- Add aggregate CI after included package checks are green; package checks remain independently runnable.
- Decide `kit/site` scope explicitly from ownership rather than adding it incidentally.

## Risks / Trade-offs

- **[Marker overpromises coverage]** → Define supported exports and test wheel marker plus public import/type fixtures.
- **[Framework typing dominates work]** → Type stable boundaries first and leave shell internals at pragmatic levels.
- **[Annotations alter runtime imports]** → Preserve dependency layers, including under `TYPE_CHECKING`, and run import-boundary tests.

## Open question: declared-dependency completeness

- **Typecheck ratchet versus undeclared imports.** *Gates the `core/storefront`
  step.* `core_storefront` lazily imports three packages its `pyproject.toml` does
  not declare: `market_alkahest.schemas` in `refund.py`, `web3` in
  `token_transfer.py`, and `fastapi` in `app_composition.py` and `openapi.py`. A
  per-package ratchet either fails on these, because the project's own environment
  does not install them, or hides them behind ignores that erase the architectural
  fact. `ARCHITECTURE.md` lists the undeclared imports under "Where the current tree
  diverges" and `enforce-package-layers`'s exceptions table carries them under this
  change. Suggested resolution: add "every distribution the source imports is declared,
  and every declared internal distribution is imported or carries a stated runtime
  reason" to the acceptance criterion for every ratcheted package, and sequence the `core/storefront` step after
  `kit-owned-storefront-auth-and-persistence` and `move-escrow-into-alkahest` decide
  whether `refund`, `token_transfer`, and `escrow_identity` leave for `kit/alkahest`
  (the recommended outcome) or stay and are declared. The reverse direction is a warning
  rather than a defect, since a declaration can exist to install a plugin or a
  driver — the VM storefront's two bare-metal declarations install the bare-metal
  contribution into the compute shell — and `enforce-package-layers`'s
  declarations table is where such a reason is recorded. Task 2.5 is the decision gate for
  the "`kit/site` question" and stays one; the recommended answer for it is that
  `kit/site` passes `ARCHITECTURE.md`'s third-domain placement test because API
  credits composes it, stays repository-wide, and belongs in a kit typing ratchet
  rather than this core campaign.

## Migration Plan

Restore current advertised packages first, then add one package per coherent commit with passing wheel/type/runtime checks. Consumers require no wire migration. Roll back a package's marker only if its advertised support cannot be maintained, with release documentation corrected in the same change.

## Permanent Documentation Promotion

Typed boundary ownership belongs in `market-composition`; required checks in `test-compatibility`; marker/package behavior in `deployment-state`; rationale belongs in the corresponding architecture companions.
