## 1. Verify Current Boundary

- [ ] 1.1 Reconcile the legacy plan against current code and focused tests; remove already-landed steps
- [ ] 1.2 Confirm wire, persistence, packaging, and deployment compatibility requirements for the affected boundary

## 2. Implement and Verify

- [ ] 2.1 Implement postgres-backed registry rollout at the owning capability boundary
- [ ] 2.2 Add or update focused tests for the observable acceptance scenario
- [ ] 2.3 Run the narrow affected test suites and OpenSpec validation

## 3. Cleanup

- [ ] 3.1 Remove obsolete paths and update explanatory/operator documentation after behavior is verified
