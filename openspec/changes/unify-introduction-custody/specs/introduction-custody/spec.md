## ADDED Requirements

### Requirement: One custody layer holds every host's introduction contacts

Introduction custody MUST hold the contacts of every introduction a host makes, and MUST know
nothing of the host's domain: it MUST NOT depend on a settlement mechanism, a market family
or a deployed service. A host MUST supply each introduction's identifier, the role label of
each of its two parties, and an optional opaque, non-secret context, and custody MUST
interpret none of them; the two labels MAY be the same. Custody MUST refuse, before writing
anything, a role label that is blank or longer than 64 characters, and a context that is
not a JSON object or exceeds custody's size bound. Authorizing who may reveal, read, end or delete an introduction MUST
remain the host's.

An introduction MUST be persisted once, with both parties' contacts, at the moment it is
revealed. A reveal repeated with identical contacts MUST return the stored introduction, a
reveal with different contacts MUST be refused, and a reveal of a redacted introduction MUST
answer the deleted outcome. A read MUST distinguish three results: an identifier never
revealed is absent; a revealed introduction returns both contacts, an empty contact being
present rather than absent; and a redacted introduction answers the deleted outcome.

Every custody operation MUST run on a connection the host supplies, so that it takes part in
the host's transaction. Custody MUST own the schema it persists in, for every database
dialect it supports, and each host's migration chain MUST create it from custody's own
statements.

#### Scenario: Two hosts hold introductions through one layer

- **WHEN** a storefront holds a contact-exchange introduction and another host holds an
  introduction of its own
- **THEN** both are held by the same custody operations, each under the identifier and role
  labels its host supplied

#### Scenario: A reveal is repeated

- **WHEN** a host reveals an introduction already revealed with identical contacts
- **THEN** custody returns the stored introduction and persists nothing new

#### Scenario: A reveal conflicts with the stored introduction

- **WHEN** a host reveals an introduction already revealed with different contacts
- **THEN** custody refuses the reveal and the stored contacts are unchanged

#### Scenario: An identifier never revealed is read

- **WHEN** a host reads an identifier it never revealed
- **THEN** custody answers that it is absent, which differs from a revealed introduction
  holding an empty contact

#### Scenario: A custody operation joins the host's transaction

- **WHEN** a host ends an introduction and records its own state change in one transaction
  that then rolls back
- **THEN** neither the redaction nor the host's change is persisted

### Requirement: Contacts are encrypted at rest under a key held outside the database

Custody MUST store every contact as authenticated ciphertext under a keyset held outside the
database, and MUST NOT store a contact in plaintext. Each ciphertext MUST name the key that
wrote it, so a contact written under any key the keyset still holds can be read. Each
ciphertext MUST be bound to the introduction or held contact, the slot and the role it was
written for, so that one moved to another record or another slot fails to decrypt whatever
role labels the host supplied, and MUST NOT be bound to any retention value.

A host composing custody MUST refuse to start when its keyset is absent or malformed, or when
a stored ciphertext names a key its keyset does not hold; the refusal MUST name the setting
or the missing key ids.

#### Scenario: A contact is stored

- **WHEN** a host reveals an introduction
- **THEN** each contact is stored as ciphertext, and reading the database without the keyset
  yields no contact

#### Scenario: A ciphertext is moved to another record

- **WHEN** a stored ciphertext is copied into another introduction's slot or into the other
  slot of its own introduction
- **THEN** reading that slot fails to decrypt and no contact is returned

#### Scenario: A ciphertext is moved between slots with the same role label

- **WHEN** a host revealed an introduction whose two parties share one role label, and one
  slot's ciphertext is copied into the other slot
- **THEN** reading that slot fails to decrypt and no contact is returned

#### Scenario: A host starts without its keyset

- **WHEN** a host composing custody starts with no keyset configured
- **THEN** it refuses to start and names the keyset setting

#### Scenario: A host starts with a key missing

- **WHEN** a host starts with a keyset that lacks a key a stored ciphertext names
- **THEN** it refuses to start and names the missing key ids

### Requirement: A revealed introduction's contacts change at most once, by redaction

A revealed introduction's contacts, decrypted, MUST change at most once after it is
persisted, by redaction, and redaction MUST NOT be reversible. Redaction MUST remove both
contacts in one atomic change and record when it happened, keeping the introduction's
identifier, role labels, context and reveal time as a tombstone, so a concurrent read
observes either the complete introduction or the redacted one. An unredacted introduction's
record MUST NOT be removed. Redaction MUST be idempotent: redacting an already-redacted
introduction, or an identifier never revealed, MUST converge rather than fail.

A stored ciphertext MAY be replaced by a re-encryption of the same contact under another key.
The database MUST enforce every part of this requirement it can observe: no change but
redaction or re-encryption, no change to the identifier, role labels, context, reveal time or
the held contact an introduction was promoted from,
no restoring a redacted contact, a re-encryption only on an unredacted introduction keeping
both contacts present under a different key, and no removal of an unredacted record. Custody
MUST enforce that a re-encryption leaves the decrypted contact unchanged, and MUST offer no
host a write over a stored contact.

After redaction, a read MUST answer a stable deleted outcome stating when the contacts were
deleted, and MUST NOT state why.

#### Scenario: A redacted introduction is read

- **WHEN** a host reads an introduction whose contacts have been redacted
- **THEN** it receives the deleted outcome with the redaction time and no contact

#### Scenario: A code path tries to restore a redacted contact

- **WHEN** any update tries to store a contact on a redacted introduction
- **THEN** the database refuses the change

#### Scenario: A code path tries to remove an unredacted introduction

- **WHEN** any statement tries to delete an unredacted introduction's record
- **THEN** the database refuses the change

#### Scenario: Redaction is repeated

- **WHEN** a host redacts an introduction already redacted, or an identifier never revealed
- **THEN** the operation converges without failing

#### Scenario: A read interleaves with redaction

- **WHEN** a read of an introduction runs concurrently with its redaction
- **THEN** the read returns either both contacts or the deleted outcome, never one contact

### Requirement: Retention is one running policy

Custody MUST apply a host's retention window as an aggregate policy read from the host's
running configuration, and MUST NOT record a window or cutoff per introduction. The window
MUST be a positive duration or `indefinite`, which deletes nothing; a host MAY refuse
`indefinite` by its own policy. An introduction MUST become eligible for deletion when the
time since it was revealed, read from the process time source, reaches the window.

#### Scenario: The window is shortened

- **WHEN** a host restarts with a window shorter than the age of an introduction already
  revealed
- **THEN** that introduction is eligible for deletion at the next sweep

#### Scenario: The window is indefinite

- **WHEN** a host's window is `indefinite`
- **THEN** the sweep deletes nothing

### Requirement: Every deletion uses one operation

Redacting one introduction — by the sweep, by an operator, by a participant's early end, or
by restore redaction — MUST go through one shared deletion operation.

#### Scenario: Two paths delete

- **WHEN** an operator deletes one introduction and the sweep deletes another
- **THEN** both are redacted by the same operation

### Requirement: Either participant may end an introduction

Custody MUST offer an end operation that redacts an introduction's contacts for both parties,
in the host's transaction, through the one deletion operation, converging when the
introduction is already redacted. Ending an identifier never revealed MUST persist nothing
and MUST report it absent, so the host can answer it and a later reveal is not prevented.
The host MUST authorize that the caller is one of the
introduction's participants.

#### Scenario: A participant ends an introduction

- **WHEN** a host ends an introduction on a participant's request
- **THEN** both contacts are redacted and every later read answers the deleted outcome

### Requirement: The sweep is an operator-controlled worker

Custody MUST provide the retention sweep as a lifecycle worker whose one cycle redacts
eligible introductions oldest first in bounded batches. The worker MUST offer a gate an
operator can pause and resume, which holds the worker at a cycle boundary without cancelling
a cycle; one cycle, run under the worker's lock by both its timer and an operator's step; a
preview of what the next cycle would delete, writing nothing; and a bounded status. A preview
reports the introductions eligible when it is taken, and the next cycle MUST delete every
previewed introduction still unredacted, and MAY delete introductions that became eligible
since.

A host composing custody MUST run the worker and expose its controls behind its own
administrator authentication.

#### Scenario: An operator previews and steps the sweep

- **WHEN** an operator pauses the sweep, previews it, then runs one cycle
- **THEN** the preview reports the eligible introductions without deleting them
- **AND** the cycle deletes every previewed introduction still unredacted

### Requirement: A host sweeps before serving after downtime and reports overdue contacts

A host composing custody MUST, at startup, after its keyset checks and before it serves
introductions, run the sweep's cycle until no eligible introduction remains. The sweep's
status MUST report how long past the window the oldest unredacted introduction is, or that
none is overdue.

#### Scenario: A host restarts after downtime

- **WHEN** a host starts while introductions past the window are still unredacted
- **THEN** it redacts them before it serves any introduction

#### Scenario: An operator reads overdue contacts

- **WHEN** an operator reads the sweep's status while an introduction past the window is
  unredacted
- **THEN** the status reports how far past the window it is

### Requirement: Rotation re-encrypts retained contacts

Custody MUST provide a re-encryption worker, with the same gate, one cycle, preview and
status as the sweep, whose cycle re-encrypts, oldest first in bounded batches, every
unredacted contact and held contact not under the keyset's primary key. A host's status MUST
report how many stored contacts each key holds.

#### Scenario: An operator rotates the key

- **WHEN** an operator makes a new key primary and the re-encryption worker runs
- **THEN** every stored contact is re-encrypted under the new key, decrypting to the same
  value
- **AND** the status reports no contact under the old key

### Requirement: A contact can be held before its introduction exists

Custody MUST offer held contacts: a single party's contact, under a host-supplied identifier
and role label, held before an introduction exists. It MUST offer holding one; discarding
one, which removes it and converges when it is already gone; and promoting one, which in the
host's transaction creates an introduction from the held contact and the other party's
contact and removes the held contact, the promoted contact decrypting to the held value. A
held contact MUST NOT be changed but by re-encryption. When a held contact is held,
discarded or promoted MUST be the host's decision.

An introduction created by a promotion MUST record the identifier of the held contact it was
promoted from, keep it after redaction, and never change it.

Holding and promoting MUST follow a reveal's idempotency. A hold repeated with the same role
and contact MUST return the held contact and write nothing, and a hold with a different role
or contact under the same identifier MUST be refused, leaving the held contact unchanged. A
promotion whose held contact is gone MUST return the target introduction when it exists
unredacted, was promoted from the same held identifier, and has the same other party's
contact, roles and context; MUST answer the deleted outcome when that introduction was
promoted from the same held identifier and is redacted; MUST be refused as conflicting when
the target introduction was revealed directly or promoted from another held identifier,
redacted or not; and MUST be refused as not held when no introduction exists either. A
promotion whose held contact remains but whose target introduction already exists MUST be
refused. Each refusal MUST change nothing.

#### Scenario: A held contact is promoted

- **WHEN** a host promotes a held contact with the other party's contact
- **THEN** an introduction is revealed holding both contacts and the held contact no longer
  exists, in one transaction

#### Scenario: A held contact is discarded

- **WHEN** a host discards a held contact, once or twice
- **THEN** it no longer exists and the repeated discard converges

#### Scenario: A hold is repeated

- **WHEN** a host holds a contact again under the same identifier, role and contact
- **THEN** custody returns the held contact and writes nothing

#### Scenario: A hold conflicts with the held contact

- **WHEN** a host holds a different contact under an identifier already held
- **THEN** custody refuses the hold and the held contact is unchanged

#### Scenario: A promotion is repeated

- **WHEN** a host promotes a held contact again after its promotion committed, with the same
  other party's contact
- **THEN** custody returns the introduction the first promotion revealed and writes nothing

#### Scenario: A promotion is repeated after its introduction was redacted

- **WHEN** a host promotes a held contact again after its promotion committed and the
  introduction it created was redacted
- **THEN** custody answers the deleted outcome and writes nothing

#### Scenario: A discarded contact is promoted into a target another held contact filled

- **WHEN** a host promotes a discarded held contact into an introduction identifier that a
  promotion of a different held contact created, with the same other party's contact, roles
  and context, whether that introduction is redacted or not
- **THEN** custody refuses the promotion as conflicting and writes nothing

#### Scenario: A discarded contact is promoted into a directly revealed introduction

- **WHEN** a host promotes a discarded held contact into an introduction identifier that a
  reveal created
- **THEN** custody refuses the promotion as conflicting and writes nothing

#### Scenario: A code path tries to change an introduction's promotion source

- **WHEN** any update tries to change the held identifier an introduction was promoted from
- **THEN** the database refuses the change

#### Scenario: A discarded contact is promoted

- **WHEN** a host promotes a held contact that was discarded, and no introduction exists
  under the target identifier
- **THEN** custody refuses the promotion as not held and writes nothing

#### Scenario: A promotion targets an existing introduction

- **WHEN** a host promotes a held contact into an introduction identifier already revealed
- **THEN** custody refuses the promotion, and the held contact and the introduction are
  unchanged

### Requirement: A restored backup can be redacted before the host starts

Custody MUST offer restore redaction, which in the host's transaction redacts every
unredacted introduction and discards every held contact through the one deletion operation
and reports the counts, needing no key. Each host composing custody MUST expose it as a mode
of its migration command, with a preview that reports the counts and changes nothing, so an
operator runs it on a restored database before the host serves again.

#### Scenario: An operator redacts a restored backup

- **WHEN** an operator restores a backup and runs the migration command's restore-redaction
  mode before starting the host
- **THEN** no introduction in the database holds a contact and no held contact remains

#### Scenario: An operator previews restore redaction

- **WHEN** an operator runs the restore-redaction preview
- **THEN** it reports how many introductions and held contacts it would redact, and changes
  nothing

### Requirement: The retention window is disclosed before commitment and at reveal

Custody MUST provide one machine-readable disclosure of the effective window, stating an
`indefinite` window explicitly, stating that it is current policy rather than a commitment,
and stating that it governs the custody record only. A host MUST serve it, from one running
configuration, before a party commits a contact and in the projection carrying a reveal.

#### Scenario: A party reads the window before committing

- **WHEN** a party reads a host's disclosure before committing a contact
- **THEN** it reads the effective window, the same value the reveal discloses

### Requirement: Contact payloads are bounded by one validator

Custody MUST bound every contact it holds with one validator, applied whenever a contact is
revealed or held: at most 16 entries, each key 1 to 64 characters and each value non-blank
and at most 512 characters.

#### Scenario: An oversized contact is offered

- **WHEN** a host reveals or holds a contact with 17 entries
- **THEN** custody refuses it and stores nothing
