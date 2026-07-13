## Context

This change is split from the legacy planning corpus so it can be reviewed, implemented, verified, and archived independently. Deferred/conditional: activation criteria are not yet satisfied.

## Goals / Non-Goals

**Goals:**
- Provisioning may replace its storefront-client dependency with a narrow local HTTP client if dependency direction becomes costly.

**Non-Goals:**
- This change is conditional and has no implementation tasks until the dependency becomes a demonstrated maintenance problem.

## Decisions

- Keep ownership aligned with `physical-provisioning` and its baseline specification.
- Preserve existing wire, persistence, and deployment compatibility unless the proposal explicitly calls for a coordinated cutover.
- Remove obsolete in-repository callers or paths in the same implementation; do not leave indefinite aliases.

## Risks / Trade-offs

- Legacy prose may describe landed and pending work together; implementation MUST re-check current code before editing.
- Cross-service changes require focused contract tests at each changed boundary.
