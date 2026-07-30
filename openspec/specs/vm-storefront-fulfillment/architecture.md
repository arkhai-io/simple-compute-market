# VM Storefront Fulfillment Architecture

The primary escrow row is the VM storefront's durable convergence record. A versioned domain envelope preserves immutable request inputs while explicit identifiers and phase fields record externally meaningful progress. Foreground execution and the periodic restart worker coordinate through an expiring escrow processing claim.

Physical fulfillment services, capacity authorities, chain attestations, credential storage, and settlement claims remain authoritative for their own state. Escrow persistence coordinates these systems but is not treated as proof that an external side effect did or did not occur.
