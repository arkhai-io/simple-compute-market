# Design

The payment scenario uses shared payments configuration, a durable wallet-free buyer profile and `DomainDealState`. A fixture owns one pool/host/declaration, publishes its explicit USD 1.00/hour option, and arms a non-pausing mock create rule. Discovery chooses the listing and seller from a typed query and payment clause, not a supplied seller URL.

Settlement replay uses the original run/profile. Refund signs as the configured lane seller and verifies pinned responses. Financial reversal does not terminate physical delivery: lease expiry and production watchdog/convergence controls independently prove mock teardown and capacity return. Fixture finalization removes only owned rules and resumes held loops.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Three-call fixed-term payment route and distinct financial/physical teardown | `openspec/specs/test-compatibility/spec.md#requirement-fixed-term-vm-payment-scenario` |
| Lane selection and readiness boundary | `docs/development/TESTING.md#4-system-integration-tests-end-to-end` and `e2e-tests/README.md#shared-payment-scenario-configuration` |
| No repository-wide architecture or roadmap change | Existing payment authority boundaries and roadmap goal remain unchanged; this route exercises them |
