## ADDED Requirements

### Requirement: Bare-metal Alkahest servicing binds delivery before seller collection

An exactly selected bare-metal Alkahest obligation MUST retain the immutable
accepted plan, obligation, escrow, seller payout, chain, token, amount, expiry,
arbiter, and demand already verified at settlement. Exact settlement MUST
durably enqueue claimant-authorized fulfillment through the shared operation
journal only after that authority is persisted; legacy and unconfigured
obligations MUST remain unscheduled. Once the existing physical
service reports authoritative access-ready state, the storefront MUST persist a
canonical credential-free evidence intent before publishing one fulfillment
attestation whose refUID is the exact escrow and whose recipient is the
configured seller. It MUST confirm the returned attestation UID, refUID,
recipient, revocation state, and evidence bytes before binding that UID as the
shared fulfillment reference. Only then MAY the shared runtime evaluate the
accepted condition and invoke its existing collection codec. Collection success
MUST additionally require a successful transaction to the accepted escrow whose
call names the exact escrow and fulfillment UIDs and whose receipt contains one
exact token Transfer from that escrow to the configured seller for the accepted
amount.

RecipientArbiter acceptance proves only that the fulfillment attestation names
the negotiated seller recipient. It MUST NOT be represented as validation of
the physical evidence fields. Those fields remain attributable through the
accepted-plan digest and authoritative physical result/receipt.

The publication intent, returned UID, condition/collection operations, and
receipts MUST survive restart without a duplicate attestation or payment. A
worker MUST win an atomic compare-and-set over the immutable evidence intent
immediately before submission; a stale or concurrent worker MUST perform no
external write. Before an attestation write can begin, the shared fulfillment
operation MUST durably fence reclaim, and ordinary retry, deferral, non-active
physical state, or worker-lease expiry MUST NOT clear that fence. A
known UID with uncertain readback MUST be read again without resubmission. A
possibly successful publication whose UID was not durably recorded, an unknown
read, or an uncertain collection acknowledgement MUST fail closed and MUST NOT
authorize blind repetition or reclaim. Expired, reclaimed, collected, and
manual-required outcomes remain mutually exclusive under the shared lifecycle.
Only a collection mechanism that returned an effect identity requiring
authoritative readback MAY suppress resubmission; hosted retryable errors MUST
reuse their stable request identity rather than being parked by this rule.
An authoritative absence decision MAY explicitly reset the same evidence intent
and clear its shared-operation fence; no timeout or expired worker lease MAY do
so implicitly.

#### Scenario: Authoritative delivery permits seller collection

- **WHEN** the exact selected-site fulfillment has an active access grant and
  the persisted public result and receipt agree with the accepted agreement
- **THEN** servicing publishes and confirms one seller-recipient fulfillment
  attestation, binds its UID, and collects the accepted ERC-20 escrow through
  the existing codec with an exact successful seller-transfer receipt

#### Scenario: Publication acknowledgement is ambiguous

- **WHEN** fulfillment submission may have succeeded but no returned UID was
  made durable
- **THEN** servicing records an operator-required ambiguous state and performs
  no second publication, collection, or reclaim

#### Scenario: Readback is interrupted after the UID is recorded

- **WHEN** exact fulfillment readback is unavailable after the returned UID was
  persisted
- **THEN** restart retries readback for that UID and never submits another
  fulfillment attestation

#### Scenario: Worker disappears after publication is fenced

- **WHEN** a worker stops after fencing publication and its lease later expires
- **THEN** reclaim remains excluded through retry or physical deferral until
  exact publication is confirmed or authoritative absence is explicitly applied

#### Scenario: Exact collection receipt is invalid

- **WHEN** collection readback contradicts the accepted transfer or call
- **THEN** shared and operator-facing status remain `manual_required` even when
  the domain terminal mirror is unavailable, and collection is not reported ready
