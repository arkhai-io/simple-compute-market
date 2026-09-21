## ADDED Requirements

### Requirement: Accepted artifacts are immutable and verified over stored bytes

A service MUST persist an accepted artifact — content signed by a counterparty,
pinned by a content digest, or used to derive an identity another service holds — as
its exact accepted canonical bytes, and MUST NOT rewrite those bytes in any migration.
Signature and digest verification MUST be computed over the stored bytes, never over a
re-serialization of the record through the current code's model.

#### Scenario: A model gains a defaulted field

- **WHEN** a release adds a field with a default to the model an accepted artifact
  decodes into
- **THEN** every artifact stored before the release still verifies and loads

#### Scenario: A migration renames a field

- **WHEN** a migration renames a field that appears inside stored accepted artifacts
- **THEN** the stored accepted bytes are unchanged, and only derived unsigned state is
  rewritten

### Requirement: Retired artifact kinds keep read-only decoders until unused

When an artifact kind is retired, a service MUST stop producing it and MUST retain a
read-only decoder that converts it to the current model for as long as any
non-terminal record references it. The service MUST expose the count of non-terminal
records referencing each retained kind, and a decoder MUST NOT be removed while that
count is non-zero on a deployment that still holds such records. A retired kind MUST
NOT be renamed, and identities derived under it MUST NOT be re-derived under another.

#### Scenario: A long-running contract spans a kind retirement

- **WHEN** a release retires the kind a live contract was accepted under
- **THEN** the contract continues to be serviced through the retained decoder, and no
  operator drain is required before the upgrade

#### Scenario: The last contract under a retired kind ends

- **WHEN** the count of non-terminal records referencing a retained kind reaches zero
- **THEN** the decoder is eligible for removal in a later release
