# VM Storefront Fulfillment Architecture

The primary escrow row is the VM storefront's durable convergence record. A versioned domain envelope preserves immutable request inputs while explicit identifiers and phase fields record externally meaningful progress. Foreground execution and the periodic restart worker coordinate through an expiring escrow processing claim.

Physical fulfillment services, capacity authorities, chain attestations, credential storage, and settlement claims remain authoritative for their own state. Escrow persistence coordinates these systems but is not treated as proof that an external side effect did or did not occur.

## Ambiguous on-chain submission: rejected alternative

Investigation established that the pinned `alkahest-py==1.1.2` dependency contains internal log-scanning machinery but exposes neither its provider nor a bounded `refUID` attestation query -- there is no supported way to ask "does an attestation for this reference already exist?" Building that query as repository-owned raw RPC/EAS event scanning was considered and rejected: it would require unstable assumptions about external contract ABIs, deployment addresses, and network behavior that belong behind a supported `kit/alkahest` abstraction, not duplicated ad hoc in this adapter. The chosen boundary instead adopts a matching attestation only when an exposed query capability is configured, and otherwise never blindly resubmits after an ambiguous transaction outcome -- the escrow stays pending with operator-visible reconciliation rather than risking a duplicate on-chain submission. The missing query capability is filed as its own follow-on (`openspec/changes/add-alkahest-attestation-reference-query`), scoped to `alkahest-py`/`kit/alkahest`, not this storefront.
