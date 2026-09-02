## MODIFIED Requirements

### Requirement: Complete and partial administrative updates

The pool API MUST implement POST create, GET list/detail/export, PUT full replacement, PATCH partial update, DELETE disable, POST authoritative import, and POST validation-only behavior with typed request and response models.

Replacement semantics MUST NOT apply to secret provider-configuration fields. A field whose value is never returned by a read cannot be restated by a caller performing a full replacement, so resetting it to a default on omission would destroy a credential in response to an unrelated edit. Secret fields MUST retain their stored value unless the request supplies an explicit replacement, on PUT as on PATCH.

#### Scenario: PUT omits optional mutable fields

- **WHEN** an operator replaces a pool with a valid full `PoolReplace` document that omits optional policy tags
- **THEN** the stored tags are reset to the model's replacement default rather than retaining prior state

#### Scenario: PATCH changes one field

- **WHEN** an operator patches only a pool label
- **THEN** the label changes and all omitted mutable fields remain unchanged

#### Scenario: PUT omits a secret provider-configuration field

- **WHEN** an operator replaces a pool or relay with a full document that omits a secret field the read path never returned
- **THEN** the stored secret is retained rather than reset, and the operation succeeds

#### Scenario: A caller supplies a replacement secret

- **WHEN** a request explicitly supplies a new value for a secret provider-configuration field
- **THEN** the stored value is replaced

### Requirement: Session-scoped pool reads

Resource-pool management MUST expose a session-scoped pool lookup that loads provider configuration using the caller's open database session. Fulfillment uses this operation while freezing prepared provider input so the pool snapshot and aggregate write share one transaction.

Provider configuration MUST be readable at two levels of disclosure. The unqualified read MUST omit secret fields and is what serves API responses, exported documents, administrative round-trips, and reconciliation comparison. A separately named execution read MAY include decrypted secrets and is reserved for preparing provider input at dispatch.

The unqualified name MUST belong to the read that omits secrets, so that a caller which does not ask for them does not receive them. Reconciliation MUST compare stored state against a definition document using the unqualified read on both sides, so that a field one side cannot see does not report as perpetual drift.

#### Scenario: Pool configuration is frozen with acceptance

- **WHEN** fulfillment prepares provider input inside its acceptance transaction
- **THEN** the pool and provider configuration are read through the same caller-owned session before the prepared operation is persisted

#### Scenario: An API response is serialized

- **WHEN** provider configuration is read for a pool detail, list, or export response
- **THEN** no secret field is present in the serialized output

#### Scenario: Reconciliation compares an unchanged document

- **WHEN** a definition document that has not changed is compared against stored state holding a secret
- **THEN** the comparison reports no difference

### Requirement: Atomic authoritative reconciliation

Pool YAML import MUST treat the supplied definitions as authoritative, validate the complete document before mutation, apply valid changes atomically, disable enabled pools omitted from the document, never hard-delete omitted pools, and return a deterministic reconciliation diff.

Authority is what makes the document a declaration rather than a merge: an operator who removes an entry is stating that the pool should no longer be offered, and an import that silently kept it would make the document an incomplete description of the system it claims to describe. Disabling rather than erasing bounds the cost of that authority, so a mistaken omission is recoverable.

That authority is scoped to the act of submitting a document. A service MUST NOT re-apply a previously imported document merely because a process started. Import is idempotent with respect to the document, not with respect to the database: re-running it against state something else has changed reverts that change, because a diff against the document is what detects it. A process restart is not an operator declaring desired state, and treating it as one silently reverts administrative work on eviction, drain, and crash recovery.

A service that imports a definition document at startup MUST therefore record a durable digest of the document it imported and reconcile only when the current document differs from the recorded one. An explicit import request MUST reconcile regardless of the digest, because the operator has asked. The recorded digest MUST be updated in the same transaction that applies the reconciliation, so a failed apply does not suppress the next attempt.

#### Scenario: One imported entry is invalid

- **WHEN** a document contains valid changes and one invalid pool definition
- **THEN** the complete import is rejected and none of the valid changes are persisted

#### Scenario: Valid document is re-imported

- **WHEN** an operator imports the same valid document twice
- **THEN** the second response reports the declared pools unchanged and performs no semantic data change

#### Scenario: Canonical export is round-tripped

- **WHEN** an operator exports the current pool state and validates or imports that YAML without editing it
- **THEN** the document remains valid and represents the same complete pool and provider configuration state

#### Scenario: A process restarts against an unchanged document

- **WHEN** state is changed through the API and the service restarts with the same definition document still mounted
- **THEN** no reconciliation is performed and the change made through the API is retained

#### Scenario: A mounted document is edited and the service restarts

- **WHEN** a mounted definition document is edited and the service restarts
- **THEN** the document is reconciled authoritatively, including disabling entries it no longer names

#### Scenario: An operator submits an unchanged document explicitly

- **WHEN** an operator submits a document identical to the one last imported
- **THEN** reconciliation runs and the response reports the resulting diff

#### Scenario: Reconciliation fails part way

- **WHEN** an import is attempted and the apply fails
- **THEN** the recorded digest is unchanged, so the next startup attempts the reconciliation again
