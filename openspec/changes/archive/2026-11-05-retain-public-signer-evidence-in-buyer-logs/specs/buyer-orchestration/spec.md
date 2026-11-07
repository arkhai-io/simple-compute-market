# Spec Delta

## ADDED Requirements

### Requirement: Public signer evidence remains loggable

Buyer run logs MUST preserve protocol evidence whose `signer` is exactly a
validated canonical public `{scheme, identifier}` identity. They MUST continue
rejecting private signer material, signer objects, noncanonical or extended
signer mappings and other secret/provider carriers at every nesting level.

#### Scenario: Delivery end returns a signed claim

- **WHEN** the accepted seller's signed acknowledgement includes a claim with its canonical public signer identity
- **THEN** the buyer logs the evidence unchanged and does not fail after the surrender was accepted

#### Scenario: A public-looking carrier contains a private field

- **WHEN** a signer mapping adds private material or a nested secret/provider carrier
- **THEN** the run log rejects it before writing the event

## MODIFIED Requirements

### Requirement: Buyer evidence is separate from private delivery

Buyer settlement progress MUST retain its recorded opaque settlement reference, exact accepted Agreement bytes and domain settlement data for recovery. Delivery results and credentials MUST remain in the domain's authenticated result handling and MUST NOT be substituted for accepted settlement state or persisted as public run evidence. Seller delivery authorization remains the storefront's verified SettlementEvidence, not buyer-local progress.

#### Scenario: Buyer retrieves a delivered API key

- **WHEN** the buyer retrieves a grant after settlement has completed
- **THEN** buyer recovery retains the accepted settlement reference while the bearer credential uses the private result boundary and stays out of the run log

#### Scenario: Private delivery accompanies a settlement status

- **WHEN** an authenticated settlement response carries status and private delivery fields
- **THEN** progress observers receive only public status, the private result remains available to its authenticated caller and no private delivery field enters the run log
