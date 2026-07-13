## Context

This change is split from the legacy planning corpus so it can be reviewed, implemented, verified, and archived independently. Planned and independently implementable.

## Goals / Non-Goals

**Goals:**
- Customer-facing and service package locks no longer encode parent-directory uv sources.

**Non-Goals:**
- Do not change runtime dependency versions except as required by lock regeneration.

## Decisions

- Keep ownership aligned with `deployment-state` and its baseline specification.
- Preserve existing wire, persistence, and deployment compatibility unless the proposal explicitly calls for a coordinated cutover.
- Remove obsolete in-repository callers or paths in the same implementation; do not leave indefinite aliases.

## Risks / Trade-offs

- Legacy prose may describe landed and pending work together; implementation MUST re-check current code before editing.
- Cross-service changes require focused contract tests at each changed boundary.
