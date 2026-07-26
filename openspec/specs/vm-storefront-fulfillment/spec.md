# VM Storefront Fulfillment

## Purpose

This specification defines how the VM storefront turns an accepted commercial escrow into delivered compute capacity and how unfinished delivery converges after process restart.

## Requirements

### Requirement: Accepted-deal delivery priority

Once a deal has been accepted, commercial delivery takes priority over local bookkeeping durability. The storefront MUST retry and loudly report failed local checkpoint writes, but it MUST NOT abandon an otherwise deliverable VM solely because storefront-local persistence failed. Recovery MUST reconcile authoritative external state when local checkpoints are absent or stale.

### Requirement: Versioned fulfillment context

Before the first recoverable external mutation, the VM storefront MUST persist a versioned `vm.storefront.fulfillment-context` envelope on the primary escrow. Version 1 records the exact normalized VM fulfillment request, generated VM target, listing and order references, lease timing inputs, and escrow identity. Credentials and other returned secrets MUST NOT be stored in this envelope.

Unsupported kinds or versions MUST remain operator-visible and MUST NOT be guessed or rewritten silently.

### Requirement: Full settlement convergence ownership

The VM storefront owns convergence from capacity reservation through physical fulfillment, credential delivery, lease registration required by the current teardown path, on-chain fulfillment, listing update, escrow readiness, and settlement-claim creation. The claims engine remains responsible for post-fulfillment claim submission and collection; it does not recover physical fulfillment.

### Requirement: Foreground and restart convergence

The foreground settlement task and the restart worker MUST use the same durable escrow state and replay-safe phase boundaries. The foreground path may continue to wait synchronously, but unfinished primary escrows MUST be discoverable by a dedicated periodic worker registered at storefront startup.

The worker MUST use durable cross-process coordination with an expiring claim. A process-local lock MUST NOT be the correctness boundary.

### Requirement: Physical fulfillment resumption

When a durable fulfillment ID exists, recovery MUST query that fulfillment directly and MUST NOT schedule or begin a replacement fulfillment. Nonterminal provider state remains pending. Active results MUST be fetched and durably recorded. Provider failure MUST use the existing storefront failure policy.

When fulfillment identity is absent, recovery MUST use the persisted exact request and the idempotent reservation, scheduling, and begin-fulfillment contracts rather than generating replacement request values.

### Requirement: Aggregate site routing

Restart recovery MUST use the same aggregate capacity and fulfillment clients as foreground settlement. Cold-cache recovery MAY fan out across configured sites using the existing broad fallback policy shared by both aggregate clients. Typed fallback classification is an aggregation-wide concern and is not changed only for fulfillment recovery.

### Requirement: Ambiguous on-chain submission safety

Before retrying an on-chain compute fulfillment whose local acknowledgement is absent, the storefront MUST use an available supported Alkahest attestation-query surface to reconcile a matching fulfillment. A matching attestation is adopted and persisted. Conflicting matches remain operator-visible.

When the installed Alkahest client does not expose a supported bounded query, the storefront MUST NOT blindly resubmit after an unknown transaction outcome. The escrow remains pending, the condition is logged at high severity for operator reconciliation, and commercial delivery already completed MUST NOT be undone. Generic RPC/EAS event scanning is deferred to a supported `alkahest-py` or `kit/alkahest` query abstraction rather than implemented through repository-owned assumptions about external ABI and deployment details.
