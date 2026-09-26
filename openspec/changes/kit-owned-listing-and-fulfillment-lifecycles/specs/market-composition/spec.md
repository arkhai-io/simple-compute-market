## ADDED Requirements

### Requirement: Kit-owned listing lifecycle and fulfillment convergence

The seller listing lifecycle (close, pause, reopen, and successor carry-over) and
restart-safe fulfillment convergence (obligation resumption, terminal-state driving,
executor-result reconciliation, and teardown independence) MUST be kit-owned and
composed by every storefront domain. A domain MUST supply its listing payload codec,
successor-identity rule, executor payload, result decoding, and effects, and MUST NOT
carry a listing lifecycle service, a resume runtime, or a per-site projection cache of
its own.

#### Scenario: A seller closes a listing in any domain

- **WHEN** a seller closes, pauses, or reopens a listing through the shared routes
- **THEN** the kit mutates the common binding and publishes the result, and the
  domain's codec alone interprets the listing payload

#### Scenario: A storefront restarts with accepted obligations

- **WHEN** a storefront restarts after settlement and before fulfillment completes
- **THEN** the kit resumes every accepted obligation, drives it to a terminal state
  through the domain's executor hooks, and reconciles the executor's report, with the
  same mechanism in every domain
