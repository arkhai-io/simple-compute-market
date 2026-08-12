## ADDED Requirements

### Requirement: Body-bound publisher authentication

Publication, update, close, and publisher-identity rotation MUST use the shared versioned marketplace request-signature contract with an injected signer. Publisher ownership MUST be authorized by exact canonical principal, and no private-key string, address-only claim, embedded signature field, or unsigned mutation parameter MAY bypass that contract.

#### Scenario: Listing body changes after signing

- **WHEN** any listing payload field changes after the publisher creates its proof
- **THEN** the registry rejects the publication before validation or persistence

#### Scenario: Publisher uses Ed25519

- **WHEN** a valid Ed25519 principal first publishes a schema-valid listing
- **THEN** the registry lazily creates or resolves the stable publisher and binds listing ownership without requiring an EVM wallet

### Requirement: Publisher identity migration preserves ownership

The registry MUST migrate every existing EIP-191 publisher identity and listing ownership relation to canonical principal form before serving the new signature version. Migration MUST preserve stable publisher and listing identifiers and MUST roll back completely on malformed identities, cross-scheme ambiguity, duplicate active bindings, or referential gaps.

#### Scenario: Existing publisher is migrated

- **WHEN** a valid address-owned listing population is upgraded
- **THEN** each address becomes an `eip191` principal and the same publisher retains authority over the same listings
