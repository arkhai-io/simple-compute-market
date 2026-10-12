# Bare-metal fixed-term payment scenario

## Why

The bare-metal payment buyer and seller need one connected-system scenario proving a complete fixed-term deal without replacing the canonical Alkahest scenario or pretending the mock grants real SSH access.

## What changes

Add the bare-metal payment marker and three ordered calls: purchase/delivery, original-run re-drive, seller refund plus physical teardown. Supply and cleanup stay in module fixtures; no production command or settlement design changes.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/test-compatibility/spec.md`
- [x] Testing map: `docs/development/TESTING.md`
- [x] E2E guide: `e2e-tests/README.md`
- [ ] Repository-wide architecture change

### Knowledge to promote

Purchase-specific ownership and recovery; financial reversal is separate from physical mock teardown; unavailable payments is blocked, not an Alkahest fallback.
