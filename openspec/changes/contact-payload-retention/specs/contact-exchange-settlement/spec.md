## MODIFIED Requirements

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at every ingress (configuration and the
introduction start), MUST be persisted only for deals whose introduction has been
started, and MUST be deletable as part of the deal lifecycle without disturbing the
settled obligation record. A deal that never starts its introduction MUST persist no
contact data.

A composing storefront MUST carry a retention window as configuration with a
stated default. An unset window MUST mean indefinite retention and MUST cause no
deletion, so an operator wanting today's behaviour can say so explicitly rather
than relying on an unstated absence of policy.

The window MUST be applied as an aggregate policy over the storefront's holdings
and MUST be read live wherever it is used. It MUST NOT be recorded per
introduction and enforced from the recorded value: retention is not a term agreed
with a counterparty, and a pinned window would exempt exactly the rows an operator
shortening the policy most needs to remove. Configuring a finite window is the
operator's consent to delete existing payloads past it.

Deletion MUST remove both parties' contact payloads for one introduction while
leaving the settled obligation record, the deal's terminal state, and the
resolvability of its `obligation_ref` intact. `obligation_ref` is the universal
deal-settlement identity that cross-mechanism status and tooling correlate by, so
removing the record to remove contact data would erase a deal that legitimately
happened rather than the personal details it carried.

Deletion MUST be reachable both through a scheduled sweep over payloads past the
window and through an operator-invoked path for one introduction on request, and
both MUST invoke one shared deletion operation. Neither path substitutes for the
other: a policy honoured only on operator action is not automatic, and a scheduled
sweep cannot serve an out-of-schedule request for a single party.

Deletion MUST be idempotent. Deleting an already-deleted or never-revealed
introduction MUST converge rather than fail, because a partially failed sweep is
exactly when a retry occurs. An authenticated read arriving after deletion MUST
return a clean already-deleted outcome rather than a partially populated
introduction package.

The effective window MUST be readable from the storefront before a buyer commits
contact data. The buyer's payload accompanies the introduction start, so a window
disclosed only at reveal is disclosed after the point a party could decline. The
window MUST additionally be disclosed through the projection that carries the
reveal, and both surfaces MUST read the same live value so they cannot disagree.

Both disclosures MUST state current storefront policy rather than a commitment:
the operator may change the window or remove a payload directly at any time, and
nothing the storefront publishes binds them. Both MUST be scoped to what the
storefront retains. Each side may have delivered its own copy of the reveal to
locally configured sinks, and deletion governs what the marketplace persists rather
than what a recipient's own mailbox or file already holds, so a disclosure stated
without that scope would be a false claim about where the data is.

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

#### Scenario: The window is shortened after a reveal

- **WHEN** an operator shortens the retention window below the age of an
  already-revealed introduction
- **THEN** the next sweep deletes that introduction's payloads
- **AND** no window recorded at reveal exempts it

#### Scenario: The window is unset

- **WHEN** a storefront's retention window is unset
- **THEN** payloads are retained indefinitely and the sweep deletes nothing

#### Scenario: Both invocation paths share one handler

- **WHEN** an operator invokes deletion for one introduction and the scheduled
  sweep deletes another
- **THEN** both remove the payloads through the same deletion operation

#### Scenario: A buyer reads the window before negotiating

- **WHEN** a buyer queries a storefront before starting an introduction
- **THEN** the effective retention window is readable from the storefront
- **AND** it is the same live value the reveal projection later discloses

#### Scenario: The window is disclosed at reveal

- **WHEN** a party reads a revealed introduction
- **THEN** the projection carrying the reveal also carries the effective retention
  window
- **AND** the disclosure states current storefront policy rather than a commitment
- **AND** it is scoped to storefront retention and does not state or imply that
  copies already delivered to configured sinks are covered
