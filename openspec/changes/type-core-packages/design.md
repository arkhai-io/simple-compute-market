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

## Migration Plan

Restore current advertised packages first, then add one package per coherent commit with passing wheel/type/runtime checks. Consumers require no wire migration. Roll back a package's marker only if its advertised support cannot be maintained, with release documentation corrected in the same change.

## Permanent Documentation Promotion

Typed boundary ownership belongs in `market-composition`; required checks in `test-compatibility`; marker/package behavior in `deployment-state`; rationale belongs in the corresponding architecture companions.
