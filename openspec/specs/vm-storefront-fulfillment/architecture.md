# VM Storefront Fulfillment Architecture

The [normative contract](spec.md) defines evidence-gated VM delivery and restart convergence.

## Evidence and delivery ownership

Buyer and seller role tables bind Alkahest and Arkhai payments independently.
Seller entries verify authoritative sources and persist negotiation-keyed
`vm_settlement_evidence`: mechanism, exact Agreement digest, established opaque
reference, status and the `vm.settlement-evidence.v1` payload. Verified storage
requires a SHA-256 digest, nonempty source and validated `vm.delivery-facts`
version 1. Once verified, status/source/delivery cannot be replaced; changed
Agreement, mechanism or established reference conflicts.

`vm_delivery_records` separately owns immutable fulfillment context, selected-site
and physical identities, phase checkpoints, expiring claims and private results.
Before physical effects, the exact request/target is persisted in
`vm.storefront.fulfillment-context` version 1. Foreground and periodic recovery
coordinate through the same durable claim, not process-local locks. A payment
creates no escrow or obligation; genuine Alkahest rows and servicing remain
separate.

The planner reads verified normalized provision terms, lease timing, funding
expiry and any stage-supplied lease bytes/condition anchor. It does not decode a
receipt or choose behavior from a mechanism ID. Recovery resolves the exact
accepted Agreement through the seller table, revalidates source evidence, then
runs common physical convergence under the existing reservation/fulfillment
identity. The selected continuation owns attestation, claim binding and failure
policy. Private credentials are delivery state, never settlement evidence.

## Explicit database reset

Incompatible disposable databases must be reset explicitly while negotiation,
settlement and recovery are quiesced. Use a new owned SQLite path or delete only
the confirmed disposable database; bootstrap fresh migrations, republish and
renegotiate. Do not reuse historical payment escrow rows or restore stale state
after external effects. Introducing migrations bootstrap current tables in
place; startup rejects the former payment schema rather than copying/adopting
it. Rebuild `.dist` and reinstall consuming buyer/storefront wheels before use.
The committed `domains/vms/storefront/examples/payment_smoke.py` owns and removes
its fresh temporary database; it is a controlled wiring entry, not a deployed
ledger/provider qualification.

## Ambiguous on-chain submission

The pinned `alkahest-py==1.1.2` exposes no supported bounded attestation query by
`refUID`. Raw RPC/EAS event scanning here would depend on external ABI, address
and network assumptions owned by the mechanism kit. The Alkahest continuation
therefore adopts a matching attestation only through a supported injected query
capability. It never blindly resubmits after an ambiguous outcome: submission
intent is durable before the external effect, delivery stays pending for operator
reconciliation, and already-delivered compute is not undone. The capability gap
belongs to `openspec/changes/add-alkahest-attestation-reference-query`.
