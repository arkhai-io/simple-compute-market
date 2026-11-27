## MODIFIED Requirements

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at every ingress (configuration and the
introduction start) by introduction custody's one payload validator, MUST be persisted
only for deals whose introduction has been started, and MUST be deletable as part of the
deal lifecycle without disturbing the settled obligation record. A deal that never starts
its introduction MUST persist no contact data.

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

### Requirement: Deleting contact payloads leaves a tombstone

Deleting an introduction's contact payloads MUST redact them through introduction
custody, which keeps the introduction as a tombstone recording when its payloads were
deleted and keeping the agreed introduction context, and which enforces that a revealed
introduction is changed at most once, by an irreversible redaction, and that its record
is never removed while its payloads are present. The fact that an introduction was
revealed is what prevents it being revealed again.

Redaction MUST be idempotent. Redacting an already-redacted introduction, or a deal
that never started its introduction, MUST converge rather than fail.

After redaction, a storefront MUST NOT return either party's contact payload for that
introduction from its introduction record:

- an authenticated read MUST answer with a stable deleted outcome that states when the
  payloads were deleted;
- an introduction start that finds the payloads deleted, whether when it reads the
  introduction or when it persists one, MUST still drive the deal's obligation to its
  terminal state, then answer the same deleted outcome, and MUST NOT persist contact
  data or deliver the introduction;
- the reveal projection MUST refuse to render a redacted introduction.

An introduction is revealed when it is persisted, and a reveal and a deletion are
ordered by that moment. A start that persisted, or found persisted, the complete
introduction before a deletion committed is a reveal that preceded the deletion: it
MAY complete, answer the reveal, and deliver it, even if the deletion commits while it
is still in progress. Deletion bounds what the storefront holds from the moment it
commits; it does not recall a reveal already made, just as it does not recall copies
already delivered to either side's sinks.

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

#### Scenario: A deletion overlaps a start that has already revealed

- **WHEN** an introduction start has persisted the complete introduction and is still
  completing the deal's obligation when a deletion of its payloads commits
- **THEN** the start completes and answers the reveal, and, if it claims the
  introduction's seller-side delivery, dispatches it best-effort
- **AND** every later read or start answers the deleted outcome

#### Scenario: A deleted introduction cannot be restored or removed

- **WHEN** any code path attempts to restore a redacted introduction's payloads, or to
  remove an unredacted introduction's record
- **THEN** the storefront's persistence refuses the change

### Requirement: Contact payloads are retained for a configured window

The contact-exchange mechanism's seller configuration MUST carry a retention window,
defaulting to 30 days. The window MUST be either a positive duration or an explicit
`indefinite`, which MUST cause no deletion; a zero window MUST be refused. An operator
wanting unbounded retention therefore says so rather than relying on an absent policy.

The window MUST be applied as introduction custody's aggregate policy over the
storefront's holdings, read from the running configuration wherever it is used. It MUST
NOT be recorded per introduction and enforced from the recorded value: retention is not
a term agreed with a counterparty, and a pinned window would exempt exactly the
introductions an operator shortening the policy most needs to remove. Configuring a
finite window is the operator's consent to delete existing payloads past it.

An introduction MUST become eligible for deletion when the time since it was revealed
reaches the window.

Deletion MUST be reachable through custody's scheduled sweep, through an operator-invoked
deletion of one introduction, and through a party's early end, and all MUST invoke
custody's one deletion operation. The sweep MUST be registered as a storefront lifecycle
loop that the lifecycle pause holds and an operator can step, and an operator MUST be
able to preview what its next cycle would delete without deleting anything.

A preview reports the introductions eligible when it is taken. Eligibility only grows
with time, so the next cycle MUST delete every previewed introduction whose payloads
are still present, and MAY also delete introductions that became eligible after the
preview. A cycle bounded to a batch MUST select the longest-revealed introductions
first, so a previewed introduction is never displaced by one that became eligible
later.

Every storefront that composes the mechanism MUST run the sweep, MUST serve the
operator-invoked deletion, and MUST serve both disclosures this capability requires.

#### Scenario: The window is shortened after a reveal

- **WHEN** an operator restarts a storefront with a retention window shorter than the
  age of an already-revealed introduction
- **THEN** the storefront deletes that introduction's payloads before it serves
  introductions again
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
- **AND** the cycle deletes the payloads of every previewed introduction not deleted
  in the meantime, together with any that became eligible after the preview

#### Scenario: A storefront composes the mechanism

- **WHEN** a storefront composes `contact-exchange.v1`
- **THEN** it runs the retention sweep and serves the operator deletion and both
  disclosures

## ADDED Requirements

### Requirement: A storefront holds its introductions in introduction custody

A storefront composing `contact-exchange.v1` MUST hold its introductions in introduction
custody, keyed by `obligation_ref`, with the buyer's and the seller's contacts under the
roles `buyer` and `seller` and the agreed introduction context as custody's context. It
MUST take custody's keyset as a setting in its Secret overlay, MUST refuse to start under
custody's keyset refusals, MUST run custody's startup sweep before it accepts requests,
MUST register custody's re-encryption worker as a storefront lifecycle loop beside the
retention sweep, and MUST expose custody's restore redaction as a mode of its migration
command. The seller-side delivery claim MUST remain the mechanism's own, keyed by
`obligation_ref`, and custody MUST hold no delivery state.

#### Scenario: A storefront starts without a keyset

- **WHEN** a storefront composing the mechanism starts with no custody keyset in its
  Secret overlay
- **THEN** it refuses to start and names the setting

#### Scenario: A revealed introduction is stored

- **WHEN** a buyer starts an introduction
- **THEN** both contacts are stored encrypted in custody under the deal's
  `obligation_ref`, and the reveal reads as before

#### Scenario: An operator rotates a storefront's key

- **WHEN** an operator makes a new key primary and steps the re-encryption loop until
  it reports nothing under the old key
- **THEN** every introduction still reads as before

### Requirement: Either party may end an introduction early

A storefront composing the mechanism MUST serve an authenticated introduction end
operation, admitting only the deal's buyer and seller principals, that redacts the
introduction through custody's end and answers the deleted outcome, converging when it
is already deleted. Ending an introduction never revealed MUST be refused with a stable
not-revealed answer and MUST persist nothing, so an end cannot prevent a later reveal. The
mechanism's buyer command group MUST offer ending an introduction, so every domain buyer
that mounts it can. The seller's operator ends an introduction by the operator-invoked
deletion.

#### Scenario: A buyer ends an introduction

- **WHEN** the buyer of a revealed introduction ends it
- **THEN** both contact payloads are deleted, the buyer receives the deleted outcome,
  and every later read by either party answers the deleted outcome

#### Scenario: A non-party tries to end an introduction

- **WHEN** a principal that is not a party to the deal requests the end
- **THEN** the request is refused and the introduction is unchanged

#### Scenario: A party ends an introduction never revealed

- **WHEN** the buyer or seller of a deal whose introduction was never started requests the
  end
- **THEN** the request is refused as not revealed, nothing is persisted, and a later start
  reveals the introduction

### Requirement: Introduction routes record no contact for exact retry

The introduction start, read and end operations MUST be declared credential-capable on
every storefront composing the mechanism: the outcome recorded for an exact retry MUST
hold no contact payload, and every exact retry MUST run the operation again under current
authorization, whatever outcome was recorded: a retried start resumes the start, so an
exact retry of a start whose completion failed completes the reveal, as
`introduction-delivery` requires. Outcomes of those operations recorded before this declaration MUST have
their contact payloads removed when the storefront's database is upgraded.

#### Scenario: A read is retried exactly after deletion

- **WHEN** a party repeats an exact introduction read after the introduction's payloads
  were deleted
- **THEN** it receives the deleted outcome, not the earlier reveal

#### Scenario: A start is retried exactly after a reveal

- **WHEN** a buyer repeats an exact introduction start whose reveal completed
- **THEN** it receives the reveal with the counterparty's contact read from custody, not a
  recorded outcome stripped of it, and the seller's side is not dispatched again

#### Scenario: A reveal's recorded outcome is inspected

- **WHEN** an introduction start or read has been answered
- **THEN** the storefront's recorded outcome for it holds no contact payload

### Requirement: An upgraded storefront holds no plaintext contact

Upgrading a storefront database written by marketplace 0.3.0 or 0.4.0 MUST redact every
introduction it holds, keeping each as a tombstone under its `obligation_ref` with its
reveal time and agreed context, and MUST leave no contact payload in plaintext. A start or
read of such an introduction MUST answer the deleted outcome and MUST NOT reveal it again.

#### Scenario: A 0.4.0 storefront is upgraded

- **WHEN** a storefront database from marketplace 0.4.0 holding revealed introductions is
  migrated
- **THEN** no contact payload remains in it, and each introduction is a tombstone

#### Scenario: A buyer starts a pre-upgrade introduction

- **WHEN** a buyer starts an introduction revealed before the upgrade
- **THEN** the storefront drives the obligation to its terminal state, answers the
  deleted outcome, and persists and delivers no contact
