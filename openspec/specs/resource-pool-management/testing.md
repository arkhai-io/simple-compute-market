---
tags: [repository, testing]
---

# Testing resource-pool management

Where each layer's tests prove the pool declarations this capability owns, at the
lowest level that can ([`test-levels.md`](../../../docs/guidance/engineering/test-levels.md)).

## Pool Offering-Mode Enforcement

Pool offering-mode coverage follows the lowest-meaningful-level rule while
proving that no execution layer relies on another layer's earlier decision:

- `kit/resource-pools-contracts` unit tests own declaration shape, typed reads,
  membership, absent-as-empty behavior, the pool models' refusal of every
  malformed domain-neutral hint, and asking-rate structure. `kit/resource-pools`
  library integration tests own identical validation across individual and
  bulk administration against real persistence.
- `kit/site` unit tests own explicit claim identity and reservation admission.
  They assert that neither a VM-shaped resource nor any resource attribute
  supplies a missing mode, that an undeclared mode creates no hold, and that
  pool authorization remains independent of exclusive/shareable physical
  accounting.
- `kit/fulfillment` scheduler tests withdraw a declaration after reservation;
  orchestration tests withdraw it after provider input is prepared and assert
  no provider dispatch occurs.
- Advertisement and backing declarations follow the same split.
  `kit/resource-pools-contracts` unit tests own declaration shape, both cross-tag
  rules, the pool models' refusal to build an invalid write, and the resolver's
  distinction between an absent and a malformed declaration. The
  `kit/resource-pools` library integration suite owns identical validation
  across individual and bulk administration, backing immutability, and the
  stored-declaration check.
  Provisioning integration tests own server-side refusal through the typed
  client — status and stored state only, per the rejection-path rule
  ([`integration-tests.md`](../../../docs/guidance/engineering/integration-tests.md#no-raw-calls-the-typed-client-is-the-contract)) — plus the
  startup refusal and every projected pool carrying both declarations. The
  API-credits service's integration suite owns its own startup refusal.
- Provider and backing immutability follow the same split. `kit/resource-pools`
  unit tests own the pure stored-versus-proposed comparison; no database is
  needed to prove it. Its library integration suite owns preserved state on
  refused replace, patch and import, and the no-write equal-provider patch, using
  real persistence and a recording handler. Provisioning integration tests own
  the HTTP 400 and HTTP 422 statuses through the typed client — rejection-path
  bodies for malformed hints — and, against file-backed SQLite with the real
  importer, a refused startup document leaving its digest unchanged and the
  document-created default. No deployed scenario is owed for these single-authority
  transactions.
- The deployed `e2e_pool_declared_modes` scenario sends an unsupported explicit
  mode for a real matching capacity resource and observes HTTP 409 plus no
  reservation row. It stops at the reservation boundary by design: provider
  failure would be evidence that admission occurred too late.

An executor-default inventory is part of closeout for changes to this boundary.
Search production compute contracts, persistence, dispatch, result, release,
site, storefront, and domain adapters for default arguments, `or` fallbacks,
and attribute-based inference; a passing focused suite alone cannot prove their
absence.
