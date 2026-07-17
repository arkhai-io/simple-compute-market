## Context

This change is split from the legacy planning corpus so it can be reviewed, implemented, verified, and archived independently. Deferred/conditional: activation criteria are not yet satisfied.

## Goals / Non-Goals

**Goals:**
- External operators can run the e2e suite against arbitrary deployments from an independent project.

**Non-Goals:**
- This change is deferred with no current timeline or implementation tasks.

## Decisions

- Keep ownership aligned with `test-compatibility` and its baseline specification.
- Preserve existing wire, persistence, and deployment compatibility unless the proposal explicitly calls for a coordinated cutover.
- Remove obsolete in-repository callers or paths in the same implementation; do not leave indefinite aliases.

## Risks / Trade-offs

- Legacy prose may describe landed and pending work together; implementation MUST re-check current code before editing.
- Cross-service changes require focused contract tests at each changed boundary.
