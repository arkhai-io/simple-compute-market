## MODIFIED Requirements

### Requirement: Buyer evidence is separate from private delivery

Buyer settlement progress MUST retain its recorded opaque settlement reference, exact accepted Agreement bytes and domain settlement data for recovery. Delivery results and credentials MUST remain in the domain's authenticated result handling and MUST NOT be substituted for accepted settlement state or persisted as public run evidence. A buyer that receives a bearer credential MUST keep its secret in a private buyer credential store and MUST record in the run log only the credential's non-secret fields and the store's reference; no run-log event, including a recorded seller status body, MAY carry the secret. Seller delivery authorization remains the storefront's verified SettlementEvidence, not buyer-local progress.

#### Scenario: Buyer retrieves a delivered API key

- **WHEN** the buyer retrieves a grant after settlement has completed
- **THEN** buyer recovery retains the accepted settlement reference while the bearer credential uses the private result boundary and stays out of the run log

#### Scenario: A delivered secret is stored privately

- **WHEN** a settlement delivers a bearer credential with its secret
- **THEN** the secret is written to the buyer's private store and the run log records `credentials_delivered` with the key ID, base URL, balance, and store reference and no secret

#### Scenario: A seller status body carries the secret

- **WHEN** a polled or terminal seller status recorded in the run log carries the delivered credential
- **THEN** the recorded body holds the credential without its secret

## ADDED Requirements

### Requirement: A buyer's private credential store

The buyer's private credential store MUST keep one record per run in a directory only the buyer's user can open (`0700`) and a file only it can read (`0600`), written atomically, and MUST refuse a directory or file that is a symbolic link and a run identifier that is not a plain file name. The store MUST sit behind an interface that names its scheme in the reference it returns, so another store can replace it without changing the run log's shape.

#### Scenario: The store is written

- **WHEN** a delivered credential is saved for a run
- **THEN** the file holding it is readable only by the buyer's user and its reference names the store's scheme and the run

#### Scenario: The store directory is a symbolic link

- **WHEN** the store's directory is a symbolic link
- **THEN** the store refuses to write and nothing is written through the link

### Requirement: A buyer retrieves a delivered credential by run

The buyer MUST provide a command that reads a run's delivered credential through the run's recovery identity and the reference its run log records, and prints it, with a machine-readable form for scripts. A run whose `credentials_delivered` event carries the secret from before private storage MUST still be readable, with the command stating that the secret is held in the run log; the run log MUST NOT be rewritten to move it.

#### Scenario: A buyer reads a stored key

- **WHEN** the buyer asks for the credential of a run whose run log records a store reference
- **THEN** the command prints the key ID, secret, base URL, and balance read from the store

#### Scenario: A buyer reads a key recorded before private storage

- **WHEN** the run's `credentials_delivered` event carries the secret
- **THEN** the command prints it, states that it is held in the run log, and leaves the run log unchanged

### Requirement: A failed private write does not lose a delivered credential

When settlement delivers a secret and the private store cannot save it, the buyer MUST show the credential to the buyer once, MUST record `credentials_unsaved` with the non-secret fields and the error's class and no secret, and MUST exit with a status distinct from every other buyer failure, telling the buyer to copy the credential now.

#### Scenario: The store cannot be written

- **WHEN** settlement is ready and saving the delivered secret fails
- **THEN** the credential is shown once, the run log records `credentials_unsaved` without the secret, and the command exits with the unsaved-credential status
