# Fixed-term VM payment scenario

## Why

The VM lane has a complete Alkahest deal but no selectable fixed-term payments journey through the production CLI and mock provisioning stack.

## Scope

Add one three-call, readiness-gated VM payment scenario with owned backed supply: buy/deliver, same-run settlement replay, seller refund and separately driven lease release. Preserve the canonical Alkahest stages. No spot lifecycle or settlement-runtime refactor.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/test-compatibility/spec.md`
- [x] Scenario map: `docs/development/TESTING.md`
- [x] Runner guide: `e2e-tests/README.md`
