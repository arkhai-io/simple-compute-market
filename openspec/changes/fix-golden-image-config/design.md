## Context

This change is split from the legacy planning corpus so it can be reviewed, implemented, verified, and archived independently. Planned and independently implementable.

## Goals / Non-Goals

**Goals:**
- Golden-image automation emits Dynaconf key names consumed directly by provisioning and documents secret transfer.

**Non-Goals:**
- No adapter or second configuration format.

## Decisions

- Keep ownership aligned with `physical-provisioning` and its baseline specification.
- Preserve existing wire, persistence, and deployment compatibility unless the proposal explicitly calls for a coordinated cutover.
- Remove obsolete in-repository callers or paths in the same implementation; do not leave indefinite aliases.

## Risks / Trade-offs

- Legacy prose may describe landed and pending work together; implementation MUST re-check current code before editing.
- Cross-service changes require focused contract tests at each changed boundary.
