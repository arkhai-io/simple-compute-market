## MODIFIED Requirements

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at every ingress (configuration and the
introduction start), MUST be persisted only for deals whose introduction has been
started, and MUST be deletable as part of the deal lifecycle without disturbing the
settled obligation record. A deal that never starts its introduction MUST persist no
contact data.

Deletion MUST remove both parties' contact payloads for one introduction while leaving
the settled obligation record, the deal's terminal state, and the resolvability of its
`obligation_ref` intact. `obligation_ref` is the universal deal-settlement identity
that cross-mechanism status and tooling correlate by, so removing the record to remove
contact data would erase a deal that legitimately happened rather than the personal
details it carried.

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

## ADDED Requirements

### Requirement: Deleting contact payloads leaves a tombstone

Deleting an introduction's contact payloads MUST redact them in place rather than
remove the introduction: the persisted introduction MUST record when its payloads were
deleted, MUST hold neither party's contact payload afterwards, and MUST keep the agreed
introduction context. Redaction MUST be atomic, so a concurrent read observes either
the complete introduction or the redacted one and never a partial record.

The fact that an introduction was revealed is what prevents it being revealed again,
so a revealed introduction's persisted record MUST NOT be removed while its payloads
are present. A revealed introduction MUST be changed at most once after it is
persisted, and only by that redaction; redaction MUST NOT be reversible. A storefront
MUST enforce both in its persistence rather than relying on callers.

Redaction MUST be idempotent. Redacting an already-redacted introduction, or a deal
that never started its introduction, MUST converge rather than fail.

After redaction, a storefront MUST NOT return either party's contact payload for that
introduction from its introduction record:

- an authenticated read MUST answer with a stable deleted outcome that states when the
  payloads were deleted;
- an introduction start MUST still drive the deal's obligation to its terminal state,
  then answer the same deleted outcome, and MUST NOT persist contact data or deliver
  the introduction;
- the reveal projection MUST refuse to render a redacted introduction.

#### Scenario: Deletion is repeated

- **WHEN** deletion is invoked for an introduction whose payloads are already deleted,
  or for a deal that never started its introduction
- **THEN** the operation converges without failing

#### Scenario: A read arrives after deletion

- **WHEN** an authenticated party reads an introduction whose payloads have been
  deleted, including where the read interleaves with the deletion
- **THEN** it receives either the complete introduction or the deleted outcome, and
  never a partially populated introduction

#### Scenario: A buyer starts a deleted introduction again

- **WHEN** a buyer sends an introduction start, under a new request identity, for a
  deal whose payloads have been deleted
- **THEN** the storefront answers the deleted outcome
- **AND** no contact payload is persisted and the seller receives no delivery

#### Scenario: A deleted introduction cannot be restored or removed

- **WHEN** any code path attempts to restore a redacted introduction's payloads, or to
  remove an unredacted introduction's record
- **THEN** the storefront's persistence refuses the change

### Requirement: Contact payloads are retained for a configured window

The contact-exchange mechanism's seller configuration MUST carry a retention window,
defaulting to 30 days. The window MUST be either a positive duration or an explicit
`indefinite`, which MUST cause no deletion; a zero window MUST be refused. An operator
wanting unbounded retention therefore says so rather than relying on an absent policy.

The window MUST be applied as an aggregate policy over the storefront's holdings,
read from the running configuration wherever it is used. It MUST NOT be recorded per
introduction and enforced from the recorded value: retention is not a term agreed with
a counterparty, and a pinned window would exempt exactly the introductions an operator
shortening the policy most needs to remove. Configuring a finite window is the
operator's consent to delete existing payloads past it.

An introduction MUST become eligible for deletion when the time since it was revealed
reaches the window.

Deletion MUST be reachable both through a scheduled sweep over eligible introductions
and through an operator-invoked deletion of one introduction, and both MUST invoke one
shared deletion operation. The scheduled sweep MUST be a storefront lifecycle loop that
the lifecycle pause holds and an operator can step, and an operator MUST be able to
preview what its next cycle would delete without deleting anything.

Every storefront that composes the mechanism MUST run the sweep, MUST serve the
operator-invoked deletion, and MUST serve both disclosures this capability requires.

#### Scenario: The window is shortened after a reveal

- **WHEN** an operator restarts a storefront with a retention window shorter than the
  age of an already-revealed introduction
- **THEN** the next sweep deletes that introduction's payloads
- **AND** no window recorded at reveal exempts it

#### Scenario: The window is indefinite

- **WHEN** a storefront's retention window is `indefinite`
- **THEN** payloads are retained and the sweep deletes nothing

#### Scenario: A zero window is configured

- **WHEN** a storefront is configured with a zero retention window
- **THEN** the configuration is refused

#### Scenario: Both invocation paths share one operation

- **WHEN** an operator deletes one introduction and the scheduled sweep deletes another
- **THEN** both remove the payloads through the same deletion operation

#### Scenario: An operator previews and steps the sweep

- **WHEN** the lifecycle loops are held and an operator previews the retention sweep,
  then runs one cycle of it
- **THEN** the preview reports the eligible introductions without deleting them
- **AND** the cycle deletes exactly those introductions' payloads

#### Scenario: A storefront composes the mechanism

- **WHEN** a storefront composes `contact-exchange.v1`
- **THEN** it runs the retention sweep and serves the operator deletion and both
  disclosures

### Requirement: The retention window is disclosed before commitment and at reveal

The effective window MUST be readable from the storefront's public readiness
projection, without authentication, before a buyer commits contact data. The buyer's
payload accompanies the introduction start, so a window disclosed only at reveal is
disclosed after the point a party could decline. The window MUST additionally be
disclosed in the projection that carries the reveal. Both disclosures MUST read the
same running configuration, so they cannot disagree, and MUST be present only when the
mechanism is enabled.

Both disclosures MUST carry the window as a machine-readable value, stating an
`indefinite` window explicitly, and MUST state that it is current storefront policy
rather than a commitment, and that it governs the storefront's introduction record.
The operator may change the window or remove a payload at any time, and copies each
side delivered to its own configured sinks, or holds in its own tooling, are outside
what the introduction record governs. A disclosure MUST NOT state or imply that it
covers any copy other than the introduction record; one that did would be a false
claim about where the data is and who controls it.

#### Scenario: A buyer reads the window before negotiating

- **WHEN** a buyer queries a storefront's readiness projection before starting an
  introduction
- **THEN** the effective retention window is readable without authentication
- **AND** it is the same value the reveal projection discloses

#### Scenario: The window is disclosed at reveal

- **WHEN** a party reads a revealed introduction
- **THEN** the projection carrying the reveal also carries the effective retention
  window
- **AND** the disclosure states current storefront policy rather than a commitment
- **AND** it is scoped to the introduction record and does not state or imply that
  any other copy, including one already delivered to a configured sink, is covered
