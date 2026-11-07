## ADDED Requirements

### Requirement: Evolution preserves retained accepted representations

A change evolving retained signed or content-addressed state MUST preserve the
original accepted representation and identity. Proof verification MUST use the
owning protocol's canonicalization and framing over that representation before
conversion to an application view. A migration MUST NOT replace accepted content
with a current-model dump. Derived unsigned state MAY migrate separately.

#### Scenario: A decoded view gains a defaulted field

- **WHEN** an upgrade adds a defaulted field to the application view of retained
  bare-metal lease-ready evidence
- **THEN** original evidence bytes, digest, signature input, and supported v1
  decoding remain unchanged

#### Scenario: A derived field is renamed

- **WHEN** a migration renames derived state beside retained accepted content
- **THEN** the original accepted representation and identity are not rewritten

### Requirement: Preservation respects explicit support and retention boundaries

Representation preservation MUST NOT extend authorized retention, reverse deletion
or tombstoning, or reenable explicitly unsupported wire versions. A reader-removal
change MUST identify supported reference and read obligations and establish that
none still needs the reader. Zero nonterminal records alone MUST NOT establish
that retained terminal evidence or supported recovery is unused.

#### Scenario: Contact retention deletes an accepted payload

- **WHEN** the contact capability deletes payloads under its authorized policy
- **THEN** existing tombstone and refusal behavior remain authoritative, and the
  deleted payload is not presented as replacement content under its old proof

#### Scenario: A previous-wire payment mandate is loaded

- **WHEN** settlement data carries a mandate the settlement contract explicitly refuses
- **THEN** it remains refused and unchanged rather than converted or reenabled

#### Scenario: Terminal evidence still has supported readers

- **WHEN** no nonterminal contract needs a decoder but retained terminal evidence
  still has a supported read obligation
- **THEN** a removal change cannot declare that decoder unused from the
  nonterminal count alone
