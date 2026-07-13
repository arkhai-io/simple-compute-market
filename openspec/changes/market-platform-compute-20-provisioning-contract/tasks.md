## 1. Reconcile the Existing Wire

- [x] 1.1 Inventory every provisioning client model/method, service route, VM caller, bare-metal caller, lease operation, credential response, and storefront callback
- [x] 1.2 Separate common lifecycle semantics from direct VM operator APIs and executor-specific payloads
- [x] 1.3 Verify current idempotency, job-state, lease-release, and callback behavior with focused contract tests
- [x] 1.4 Update the design/specs if current routes or compatibility constraints invalidate the proposed cutover

## 2. Create the Compute Contract Package

- [x] 2.1 Add compute-owned contract version, executor/action identity, correlation, idempotency, job, credential, result, lease, error, and event models
- [x] 2.2 Define adapter registration for executor-owned parameter/result validation without generic field inspection
- [x] 2.3 Define client protocols and HTTP mappings for command, job, lease, and lifecycle-event surfaces
- [ ] 2.4 Package and export the contract/client without VM implementation dependencies or parent-directory source assumptions

## 3. Adapt the Current Service In Place

- [x] 3.1 Accept and validate versioned action envelopes against committed allocation executor identity
- [x] 3.2 Make submission idempotent and retain allocation/deal/executor correlation through terminal job state
- [x] 3.3 Return typed result, credential, logs-reference, and structured error envelopes
- [x] 3.4 Expose allocation-backed lease registration, inspection, termination, retry release, and force release through the common models
- [x] 3.5 Deliver versioned deal-scoped events through a narrow idempotent event-sink interface

## 4. Fit VM and Bare Metal

- [x] 4.1 Register VM action, result, credential, and release adapters while retaining direct VM operator models in the VM package
- [x] 4.2 Register bare-metal grant/reclaim, result, credential, and release adapters in the bare-metal package
- [x] 4.3 Migrate VM storefront orchestration to the compute-owned client
- [x] 4.4 Migrate bare-metal callers and tests to the same client without importing VM models

## 5. Complete the Compatibility Cutover

- [x] 5.1 Add explicit unsupported-version and executor-mismatch responses before infrastructure work
- [x] 5.2 Migrate all in-repository package constraints and callers to the compute-owned distribution
- [x] 5.3 Remove the VM-owned shared client/DTO paths and any temporary route aliases
- [x] 5.4 Remove the separate callback-client change assumptions now covered by the event-sink contract

## 6. Verify the Contract

- [x] 6.1 Run common client/service round-trip, duplicate submission, cancellation, terminal error, result, credential, and version-mismatch tests
- [x] 6.2 Run VM and bare-metal adapter contract and lifecycle suites
- [x] 6.3 Run focused storefront-to-provisioner command and provisioner-to-storefront event scenarios
- [x] 6.4 Build/install the contract distribution and validate OpenSpec artifacts after behavioral verification
