# Buyer compute RFQ architecture

The [RFQ specification](spec.md) defines the lifecycle, access rules and public account contract.

## Registry and compute contract

The registry is authoritative for RFQs, terms revisions, responses and introductions. It validates the selected compute-family JSON Schema and filter declarations as data. The compute package defines typed requirements, search filters and offered node quantity. The registry works with the capability kind, validated data and declared comparisons.

The trusted account entry point derives an immutable subject and current sharing permission from the caller's authenticated credential. It signs the target operation, resource, exact registry audience and inputs for the registry. The registry maps admitted authority signers to their stable account namespace. Ownership uses that namespace and the subject, so credential replacement and allowed signer rotation preserve ownership. Authorized account projections identify each party through an opaque RFQ-scoped reference. On a registry that allows supply discovery without a read key, anonymous callers can search and look up open RFQs. Their projection contains published requirements and commercial terms but excludes party references and private records.

The interactive terminal, browser and authorized delegates share the same account API. The account entry point verifies signed registry responses against the requested audience and preserves the proof for the caller. The registry binds each request ID to its logical inputs and records contact-free mutation outcomes. Read retries recheck access in the registry. See [registry replay](../registry-discovery/architecture.md#body-bound-exchanges-and-durable-replay) and [version 2 proofs](../marketplace-identity/architecture.md#canonical-version-2-proofs).

## Consent and lifecycle

A respondent or their authorized delegate submits contact with consent scoped to the buyer and current terms revision. The buyer presents their own contact and consents when selecting that respondent. Selection authorizes the pair to retrieve each other's chosen contact for the introduction's retention window. At selection, the registry records a cutoff based on the configured interval. Each introduction retains that cutoff across configuration changes, and either participant can end access earlier.

The registry checks party references, versions, eligibility and database time within its write transaction. A substantive amendment ends consent on pending responses, so a respondent who wants to proceed confirms the revised terms. Cosmetic edits keep the terms revision. Withdrawal, dismissal and RFQ closure update eligibility and remove their associated pending payloads in the same transaction.

## Contact custody and recovery

The registry encrypts contact payloads using authenticated encryption with a random nonce and a key held outside the database. The ciphertext binds the registry authority, record, party, purpose and expiry. Selection re-encrypts the payload when its purpose changes. Only the consenting pair can retrieve contacts through the API. The running service and its operator are trusted with contact custody.

Logical expiry takes effect on every authorized read. Startup and periodic sweeps remove expired payloads from the live database. An explicit end deletes the pair's contact payloads in the same transaction as revocation. A backup can still contain ciphertext. Read admission after a restore requires authoritative reconciliation or redaction of data with uncertain eligibility. See [registry RFQ configuration](../registry-discovery/configuration.md#rfq-registry-settings) and [RFQ operations](../../../docs/operator-handbook.md#operate-and-recover-rfqs).
