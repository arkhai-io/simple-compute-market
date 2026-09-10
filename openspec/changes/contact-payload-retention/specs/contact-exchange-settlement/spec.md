## MODIFIED Requirements

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at every ingress (configuration and the
introduction start), MUST be persisted only for deals whose introduction has been
started, and MUST be deletable as part of the deal lifecycle without disturbing the
settled obligation record. A deal that never starts its introduction MUST persist no
contact data.

A composing storefront MUST carry a retention window as configuration with an
explicit operator default. An implicit unbounded default MUST NOT be used: it reads
as the absence of a policy rather than a decision, and it leaves nothing to
disclose. An operator MAY configure indefinite retention, which is a different and
better state than never having considered the question.

Deletion MUST remove both parties' contact payloads for one introduction while
leaving the settled obligation record, the deal's terminal state, and the
resolvability of its `obligation_ref` intact. `obligation_ref` is the universal
deal-settlement identity that cross-mechanism status and tooling correlate by, so
removing the record to remove contact data would erase a deal that legitimately
happened rather than the personal details it carried.

Deletion MUST be idempotent. Deleting an already-deleted or never-revealed
introduction MUST converge rather than fail, because a partially failed sweep is
exactly when a retry occurs. An authenticated read arriving after deletion MUST
return a clean already-deleted outcome rather than a partially populated
introduction package.

The effective retention window MUST be disclosed to both parties through the same
projection that carries the reveal, which is the one point both are guaranteed to
read. The disclosure MUST be scoped to what the storefront retains. Each side may
have delivered its own copy of the reveal to locally configured sinks, and
`delete_introduction` governs what the marketplace persists rather than what a
recipient's own mailbox or file already holds, so a disclosure stated without that
scope would be a false claim about where the data is.

#### Scenario: Unstarted deals hold no contact data

- **WHEN** a contact-exchange deal is accepted but neither party starts the
  introduction
- **THEN** no contact payload is persisted for that deal

#### Scenario: Introduction teardown removes the payloads

- **WHEN** an operator removes a revealed introduction at the end of its retention
  window
- **THEN** both contact payloads are deleted while the settled obligation record
  remains

#### Scenario: A deleted deal remains correlatable

- **WHEN** a deal's contact payloads have been deleted
- **THEN** its settled obligation record and terminal state remain
- **AND** the deal still resolves and correlates by its `obligation_ref`

#### Scenario: Deletion is repeated

- **WHEN** deletion is invoked for an introduction whose payloads are already
  deleted, or for a deal that never started its introduction
- **THEN** the operation converges without failing

#### Scenario: A read arrives after deletion

- **WHEN** an authenticated party reads an introduction whose payloads have been
  deleted, including where the read interleaves with the deletion
- **THEN** it receives a clean already-deleted outcome rather than a partially
  populated introduction package

#### Scenario: The window is disclosed at reveal

- **WHEN** a party reads a revealed introduction
- **THEN** the projection carrying the reveal also carries the effective retention
  window
- **AND** the disclosure is scoped to storefront retention and does not state or
  imply that copies already delivered to configured sinks are covered
