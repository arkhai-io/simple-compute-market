## 1. Reconcile Authority and Lifecycle State

- [x] 1.1 Map current resource, reservation, allocation, lease, executor-release, and event operations to their actual persistence owners
- [x] 1.2 Identify all transitional re-exports and callers crossing from site authority into compute lifecycle or storefront composition
- [x] 1.3 Verify current idempotency, capacity-version, failed-release, and force-release behavior with focused tests before editing
- [x] 1.4 Update the design/specs if the current transactional boundary differs from the proposed ownership split

## 2. Define the Site-Authority Port

- [x] 2.1 Define executor-neutral operations for allocation lookup, begin release, successful release, failed release evidence, and event publication
- [x] 2.2 Adapt the existing site ledger to the port without changing identifiers, reservation semantics, or cross-mode conflicts
- [x] 2.3 Add contract tests for atomic hold/commit/release, duplicate release, capacity version, and separate capacity/deal events
- [x] 2.4 Verify lower site modules import no lease watchdog, job runner, storefront composition, VM, or bare-metal implementation

## 3. Isolate Compute Lease Lifecycle

- [x] 3.1 Make lease lifecycle consume injected site-authority and executor-release ports
- [x] 3.2 Keep watchdog scheduling, retry, force release, and failure diagnosis in compute lifecycle composition
- [x] 3.3 Wire VM teardown and bare-metal reclaim as independent release delegates
- [x] 3.4 Preserve capacity-unavailable state until release succeeds or an explicit operator force release commits

## 4. Migrate Events and Callers

- [x] 4.1 Preserve anonymous versioned capacity events through the site boundary
- [x] 4.2 Preserve allocation-recorded deal ownership for lifecycle event sinks
- [x] 4.3 Migrate production and test callers to the new ports
- [x] 4.4 Remove transitional lifecycle/site re-export paths after all callers migrate

## 5. Verify the Separation

- [x] 5.1 Run site-ledger unit and contract tests
- [x] 5.2 Run VM and bare-metal lease release, failure, retry, and force-release tests
- [x] 5.3 Run focused storefront capacity projection and event-correlation scenarios
- [x] 5.4 Validate import boundaries and OpenSpec artifacts after behavioral verification
