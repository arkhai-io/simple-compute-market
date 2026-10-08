## ADDED Requirements

### Requirement: A fulfillment attempt may be deferred to its domain's convergence

A fulfillment attempt MUST report one of three outcomes: fulfilled, failed, or deferred.
Deferred means work remains that the domain's own convergence will finish: the workload
exists, but a step after it did not complete. A deferred outcome MUST be persisted through
the domain, so the domain can leave its deal open; no fulfillment MAY be bound for it, and
servicing MUST NOT be woken for it.

#### Scenario: A domain defers a fulfillment

- **WHEN** a domain's fulfillment reports deferred
- **THEN** the outcome is persisted, no fulfillment reference is bound to the obligation,
  and servicing is not woken

### Requirement: A fulfillment submission with an unknown outcome is never repeated

A fulfillment step that publishes evidence to an external authority MUST make every
retry safe. A publication the authority deduplicates by a stable operation identity,
derived from the obligation and the evidence, MAY be retried under that identity. A
publication without one MUST record its submission intent on the obligation's
fulfillment operation before submitting, and MUST NOT submit again while a recorded
intent has no recorded reference, unless a supported lookup finds the reference the
earlier submission created.

The intent and the reference MUST each be first-write-wins: recording the same value
again changes nothing, and recording a different value for the same operation is
refused. The reference MUST be recorded before the fulfillment is completed with it. The
intent MAY be cleared only by the attempt holding the operation's lease, and only after
the publisher reports that nothing was submitted or that the authority refused it.

A publisher without a stable operation identity MUST report one of four outcomes:
published, with the reference it created; not submitted, when the failure provably
preceded the submission; outcome unknown; or rejected, when the authority refused it. Not
submitted and rejected clear the intent and MAY be retried; a step MAY bound the retries
of a rejection and then park the obligation for an operator with a reason. An outcome
unknown, or a recorded intent with no recorded reference, parks the obligation for an
operator with a reason. The settlement repository MUST count the obligations parked for
an operator, by mechanism status or by any operation.

#### Scenario: The process stops after submitting

- **WHEN** a fulfillment step recorded its intent and submitted, and the process stopped
  before recording the reference
- **THEN** the next attempt does not submit, and the obligation waits for an operator with
  a reason

#### Scenario: The process stops after recording the reference

- **WHEN** a fulfillment step recorded the reference and the process stopped before
  completing the fulfillment
- **THEN** the next attempt completes the fulfillment with the recorded reference and does
  not submit

#### Scenario: A different intent is recorded for the same operation

- **WHEN** an attempt records an intent that differs from the one already recorded for the
  operation
- **THEN** the write is refused and the recorded intent is unchanged

#### Scenario: The submission provably never left

- **WHEN** a publisher reports that its submission was not sent
- **THEN** the attempt clears its intent and records a retry, and a later attempt may
  submit

#### Scenario: The authority refuses the submission repeatedly

- **WHEN** a publisher reports a rejection on each attempt until the step's bound
- **THEN** each earlier rejection clears the intent and records a retry, and the last parks
  the obligation for an operator with a reason

#### Scenario: A publication is deduplicated by the authority

- **WHEN** a publication carries a stable operation identity the authority deduplicates
- **THEN** a retry after an uncertain acknowledgement reuses that identity, and no intent
  is required

#### Scenario: Parked obligations are counted

- **WHEN** obligations wait for an operator by mechanism status or by an operation
- **THEN** the repository's count includes each such obligation once
