## MODIFIED Requirements

### Requirement: Linear buy orchestration

A buy run MUST compose discovery, candidate filtering/aggregation, negotiation and the domain-owned selected settlement hook, and persist results needed for inspection and recovery. Core MUST dispatch using the exact accepted Agreement's mechanism through the buyer-role table, not escrow-proposal presence. The selected stage owns its actor sequence and kit-specific prerequisites.

#### Scenario: Settlement response is lost

- **WHEN** the run log contains accepted terms and a deal reference
- **THEN** recovery inspects or resumes that Agreement's same table entry and operation without renegotiating a second agreement

## ADDED Requirements

### Requirement: Fresh and resumed buyers use the same stage declaration

A domain's buy, settle-from-run and resume surfaces MUST use the same buyer-role table. Stages MUST receive exact accepted Agreement bytes, opaque settlement data and the recorded profile signer. Selection prerequisites and acceptance validation specific to a mechanism MUST be owned by its entry, and core MUST NOT require an escrow proposal or buyer-first action.

#### Scenario: Payment buy has a stray escrow field

- **WHEN** the accepted Agreement selects a declared payment stage and the outcome also contains an escrow proposal
- **THEN** dispatch still selects the payment entry solely from the Agreement and never creates an Alkahest escrow

#### Scenario: Alkahest proposal is missing

- **WHEN** the accepted Agreement selects Alkahest but its outcome lacks the required proposal
- **THEN** the selected Alkahest entry refuses its own malformed input without core choosing a different mechanism

#### Scenario: Current priority changes before resume

- **WHEN** a buyer resumes a recorded accepted Agreement after another mechanism becomes first priority
- **THEN** it uses the recorded mechanism, exact accepted inputs, profile principal and established operation identity

#### Scenario: Role entry is absent

- **WHEN** the recorded Agreement's mechanism cannot resolve in the domain's buyer-role table
- **THEN** the command reports unsupported accepted work before wallet, payment or seller mutations

### Requirement: Buyer evidence is separate from private delivery

Buyer settlement progress MUST retain secret-free SettlementEvidence correlated to the accepted negotiation when supplied by the selected stage. Delivery results and credentials MUST remain in the domain's authenticated result handling and MUST NOT be substituted for settlement evidence or persisted as public run evidence.

#### Scenario: Buyer retrieves a delivered API key

- **WHEN** the buyer retrieves a grant after settlement has completed
- **THEN** settlement evidence retains its accepted reference while the bearer credential uses the private result boundary and stays out of the run log
