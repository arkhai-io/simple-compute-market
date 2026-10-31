## MODIFIED Requirements

### Requirement: Bare-metal evidence is independent of escrow rows

Bare-metal stages MUST persist accepted-Agreement-bound SettlementEvidence by negotiation ID. Fulfillment/status MUST read its verified status/reference, never an escrow fallback or chain-name sentinel. Established identity/source evidence MUST be conflict-protected. Before protected recovery, the selected stage MUST revalidate authoritative source evidence; Alkahest materialization identity alone MUST NOT authorize delivery.

Verified lifecycle cutover MUST adopt exact requests/windows and recorded reservation/fulfillment IDs into shared delivery; legacy progress MUST become read-only projections. Ambiguous rows MUST remain repair-required with their resource. Credentials or provider-active state MUST NOT imply activation, billing start or availability. Live guarded reads MUST precede credential purge. The mandatory writer-floor bridge MUST precede migration and refuse unsupported rollback.

Malformed historical evidence and receipt-only or escrow-sentinel schemas MUST NOT be silently copied or used as fallback. Incompatible unverified schemas MUST require explicit owned-database reset with effects/recovery quiesced, not fabricated evidence or a replacement resource.

#### Scenario: A legacy payment sentinel is presented

- **WHEN** an escrow row names arkhai.payments.v1 as its chain but no verified negotiation evidence exists
- **THEN** it authorizes no physical effect and status does not treat it as payment verification

#### Scenario: Bare-metal delivery resumes from evidence

- **WHEN** a verified accepted negotiation is resumed without an escrow row
- **THEN** shared delivery uses its existing selected-site lifecycle and durable physical identity without a replacement reservation

#### Scenario: Accepted evidence conflicts

- **WHEN** a record is reused with another mechanism, Agreement digest or established reference
- **THEN** the write fails before capacity, access or provider mutation

#### Scenario: Materialized Alkahest source is no longer active

- **WHEN** recovery finds reclaim or collection in progress or completed, a non-ready mechanism status, or chain evidence no longer matching the accepted obligation
- **THEN** it refuses before reservation, fulfillment, access or teardown effects

#### Scenario: Verified bare-metal lifecycle is adopted

- **WHEN** authoritative reconciliation confirms the exact accepted request/window and existing physical identities
- **THEN** shared delivery adopts them and legacy domain progress is projection-only
- **AND** malformed historical evidence is not copied and availability is not inferred from old private results

#### Scenario: A bare-metal bridge binary attempts rollback

- **WHEN** the actual supported pre-cutover bridge binary opens the migrated database
- **THEN** its writer-floor check refuses startup before any recovery or foreground writer runs
