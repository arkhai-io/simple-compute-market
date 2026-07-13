## ADDED Requirements

### Requirement: Site-backed release lifecycle

Compute lease lifecycle MUST use an injected site-authority port and MUST NOT report capacity released until the selected executor release succeeds or an operator performs an explicit force-release action.

#### Scenario: Executor release succeeds

- **WHEN** a lease expires and its registered executor completes teardown or reclaim
- **THEN** compute lifecycle records successful allocation release through the site-authority port and capacity becomes available

#### Scenario: Executor release fails

- **WHEN** VM teardown or bare-metal reclaim returns a failure
- **THEN** the allocation remains unavailable, the lease exposes `release_failed`, and retry and force-release controls retain the failure evidence

#### Scenario: Operator force-releases allocation

- **WHEN** an authorized operator force-releases after an unrecoverable executor failure
- **THEN** the audit state distinguishes the operator override from successful physical teardown

### Requirement: Lifecycle dependency isolation

Generic lease lifecycle and watchdog scheduling MUST depend on executor and site ports rather than concrete VM, bare-metal, storefront, or HTTP client implementations.

#### Scenario: Lifecycle is tested with registered delegates

- **WHEN** a test registers independent site and executor delegates
- **THEN** lease expiry, failure, retry, and release transitions execute without importing a concrete domain or storefront composition root
