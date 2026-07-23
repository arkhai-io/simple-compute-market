## Context

Provisioning and e2e loaders duplicate mechanics but differ in prefixes, dotenv files, `.secrets.toml`, include behavior, profile helpers, and provisioning's storefront fallback. `kit/config` has no Dynaconf dependency or shared factory today.

## Goals / Non-Goals

**Goals:** parameterized shared mechanics with byte-for-behavior consumer parity and correct wheel dependencies.

**Non-Goals:** one universal configuration policy or inclusion of the storefront loader.

## Decisions

- Add a small immutable loader-options contract for roots, ordered files/includes, profile selection, prefix, nested separator, dotenv/secrets, missing-file behavior, and merge flags.
- Shared code resolves profiles/order and constructs Dynaconf; consumer modules retain exported settings objects, validators, helpers, and special fallbacks.
- Capture current consumer behavior in characterization tests before extraction and run old/new parity fixtures during cutover.
- Add Dynaconf as an explicit `arkhai-kit-config` dependency and verify both consumers from built wheels.

## Risks / Trade-offs

- **[Abstraction erases meaningful differences]** → Parameterize only shared mechanics and reject options that cannot express current behavior.
- **[Merge precedence changes subtly]** → Compare nested values and source order across profile/env/secrets/include fixtures.
- **[Dependency inversion]** → Kit remains lower-level and imports no provisioning/e2e modules.

## Permanent Documentation Promotion

Shared construction and preserved precedence belong in `deployment-state` spec/architecture; consumer-specific operational profile documentation remains with each role.
