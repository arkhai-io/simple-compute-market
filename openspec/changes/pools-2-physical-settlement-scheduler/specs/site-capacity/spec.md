## MODIFIED Requirements

### Requirement: Reservation lifecycle

Capacity reservation MUST use a hold/commit/release lifecycle keyed by
durable allocation identity, MUST support lease-shaped `start`/`end`
windows and expiry of uncommitted holds through both a lazy check on
subsequent ledger access and a periodic watchdog sweep, and MUST be
idempotent for retries.

#### Scenario: Two buyers reserve the same final unit

- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

#### Scenario: Uncommitted hold outlives its TTL without another ledger access

- **WHEN** no subsequent `reserve`/`commit`/`release` call touches an expired uncommitted hold
- **THEN** a periodic reservation-expiry watchdog still releases it without requiring storefront-side polling
