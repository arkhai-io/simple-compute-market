## MODIFIED Requirements

### Requirement: Signed payment receipts gate selected-site execution

VM and bare-metal payment stages MUST load the accepted mandate beside exact Agreement bytes and verify the matching service-signed receipt before producing verified SettlementEvidence. Physical delivery MUST consume that evidence and the accepted domain/site binding, never compare mechanism IDs or create payment escrow/obligation rows. Restart MUST revalidate through the selected stage and reuse durable reservation and fulfillment identities rather than buyer routing or current listing state.

#### Scenario: Receipt is pending or mismatched

- **WHEN** the seller cannot verify a matching signed receipt
- **THEN** it reports retryable pending or rejects invalid evidence without provisioning or creating access

#### Scenario: Verified VM provisioning restarts

- **WHEN** foreground work or recovery resumes verified payment progress
- **THEN** the existing convergence lease and durable physical fulfillment ID prevent duplicate delivery

#### Scenario: Bare-metal receipt is verified

- **WHEN** payment settlement succeeds for an accepted bare-metal Agreement
- **THEN** reservation, fulfillment, result retrieval and teardown continue against that Agreement's selected-site authority

## ADDED Requirements

### Requirement: Bare-metal role tables own settlement choices

Bare-metal buyer and seller roles MUST each declare exactly their supported settlement entries. Acceptance hooks and seller settlement MUST resolve the Agreement's mechanism through the seller table; buyer purchase MUST use its buyer table. Payment-only buyer support MUST NOT imply seller-only mechanisms are supported by that buyer. Common physical delivery MUST receive verified evidence, not select a mechanism.

#### Scenario: Bare-metal buyer supports payment only

- **WHEN** discovery presents payment and seller-supported Alkahest options
- **THEN** the buyer selects only its declared compatible entry without hardcoding payment in purchase control flow

#### Scenario: Seller supports introduction instead of physical delivery

- **WHEN** its declared contact-exchange stage settles an accepted introduction
- **THEN** the fused stage retains introduction evidence and no physical reservation, access grant or payment is required

### Requirement: Bare-metal evidence is independent of escrow rows

Bare-metal settlement stages MUST persist accepted-Agreement-bound SettlementEvidence by negotiation ID. Fulfillment and status MUST read that record's verified status/reference, not accept an escrow row as alternative proof or interpret a chain-name sentinel. Established identity/source evidence MUST be conflict-protected. Incompatible evidence/lifecycle schemas MUST require explicit database reset without legacy payment-row copying or fallback. Before protected recovery effects, the selected stage MUST revalidate authoritative source evidence; an Alkahest journal's materialization identity alone MUST NOT authorize physical delivery.

#### Scenario: A legacy payment sentinel is presented

- **WHEN** an escrow row names `arkhai.payments.v1` as its chain but no verified negotiation evidence exists
- **THEN** it authorizes no physical effect and status does not treat it as payment verification

#### Scenario: Bare-metal delivery resumes from evidence

- **WHEN** a verified accepted negotiation is resumed without an escrow row
- **THEN** fulfillment uses its existing selected-site lifecycle and durable physical identity without creating a replacement reservation

#### Scenario: Accepted evidence conflicts

- **WHEN** a record is reused with another mechanism, Agreement digest or established reference
- **THEN** the write fails before capacity, access or provider mutation

#### Scenario: Materialized Alkahest source is no longer active

- **WHEN** recovery finds reclaim or collection in progress or completed, a non-ready mechanism status, or chain evidence no longer matching the accepted obligation
- **THEN** it refuses before reservation, fulfillment, access or teardown effects

### Requirement: Bare-metal obligation servicing follows the accepted seller entry

Each bare-metal seller entry MUST declare its own obligation servicing: the
continuation the settlement servicing worker runs when an obligation becomes ready
and when it ends. The runtime MUST compose servicing only for entries that provide
it, and the worker's hooks MUST resolve the entry from the accepted Agreement of the
obligation's `agreement_ref`, not compare the obligation's mechanism with concrete
mechanism IDs. An obligation whose mechanism differs from its Agreement's, or whose
entry composes no servicing, MUST be refused before any servicing effect. An entry
whose obligations need no servicing, such as contact exchange whose reveal binds the
obligation, MUST decline explicitly.

#### Scenario: An Alkahest obligation becomes ready

- **WHEN** the servicing worker reports an Alkahest obligation ready
- **THEN** the hook resolves the Alkahest entry from the accepted Agreement and only
  that entry's lifecycle starts delivery

#### Scenario: An obligation names another mechanism than its Agreement

- **WHEN** a serviced obligation's mechanism differs from its accepted Agreement's
- **THEN** the hook refuses it and no entry's servicing acts
