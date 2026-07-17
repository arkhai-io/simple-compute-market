## Context

This change is split from the legacy planning corpus so it can be reviewed, implemented, verified, and archived independently. Planned and independently implementable.

## Goals / Non-Goals

**Goals:**
- Seller automation can inspect interruptible deals, dry-run decisions, truncate leases, and execute settlement splits with audit evidence.

**Non-Goals:**
- Do not standardize a plugin decision vocabulary until multiple strategies require it.

## Decisions

- Keep ownership aligned with `storefront-publication` and its baseline specification.
- Preserve existing wire, persistence, and deployment compatibility unless the proposal explicitly calls for a coordinated cutover.
- Remove obsolete in-repository callers or paths in the same implementation; do not leave indefinite aliases.

## Risks / Trade-offs

- Legacy prose may describe landed and pending work together; implementation MUST re-check current code before editing.
- Cross-service changes require focused contract tests at each changed boundary.
