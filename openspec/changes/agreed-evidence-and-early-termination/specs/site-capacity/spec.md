## ADDED Requirements

### Requirement: Lease end intent is recorded with its transition

The site MUST record an immutable `lease_ended` event atomically with every transition establishing a lease's intended end, before teardown. It MUST carry stable event identity, reservation and site identities, effective instant, cause, source state, caller or failure reason when applicable, and deadline phase when present. Expiry, termination, direct release, release failure and force-release MUST be covered; a repeated transition MUST NOT create another event.

#### Scenario: An undelivered reservation ends directly

- **WHEN** release proves that nothing was dispatched and frees a reservation without entering `releasing`
- **THEN** the same transaction records its `lease_ended` event with the established instant and source state

#### Scenario: Release fails before teardown

- **WHEN** the lease lifecycle records an end intent but cannot establish safe physical release
- **THEN** it records the end and failure cause durably while capacity remains held under the existing release guard

#### Scenario: An operator force-releases

- **WHEN** an operator force-releases a reservation after external verification
- **THEN** that transition records its own attributable report without rewriting any prior intended-end event

#### Scenario: Termination is repeated

- **WHEN** a caller repeats a termination whose ending transition has already committed
- **THEN** the existing event identity and payload remain unchanged
