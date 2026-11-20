## ADDED Requirements

### Requirement: Optional once accounting shares the normal verified read

Seller watch MAY consume an optional neutral once-accounting capability. It MUST use the same verified payment read as the ordinary authority view, MUST NOT add a request or retry an unqualified opt-in answer, and MUST preserve ordinary public result shapes. Qualified accounting MUST remain bounded to TEST once-only scope and MUST NOT authorize a return.

#### Scenario: Optional projection is unavailable

- **WHEN** a legacy adapter, unreadable authority, malformed opt-in answer or out-of-scope payment cannot provide qualified accounting
- **THEN** no accounting success or additional payment read is invented
- **AND** ordinary authority outcomes remain truthful

### Requirement: Same-sequence accounting capture is immutable and transactional

Servicing MUST retain a bounded seller assertion in the existing evidence store without full signed payment contents. Identical financial facts at one sequence MUST preserve the first receipt. Conflicting facts MUST retain one stable unqualified marker. Capture MUST share the normal observation, final-stop and cursor transaction, with a nested savepoint isolating capture-only failure. Private accounting qualification MUST require matching durable semantic evidence and no conflict marker.

#### Scenario: A refreshed proof has identical financial facts

- **WHEN** the normal read repeats a sequence with unchanged finance and a later observation or signature
- **THEN** the original typed evidence bytes remain unchanged and no duplicate item is stored

#### Scenario: Conflicting finance repeats at one sequence

- **WHEN** the same sequence carries different financial facts
- **THEN** the original receipt remains immutable and one durable conflict marker prevents qualified accounting

#### Scenario: Capture fails after inserting an item

- **WHEN** the nested capture savepoint fails after an actual evidence insert
- **THEN** the partial item is removed and normal observation, final-stop and cursor changes may commit

#### Scenario: The outer transaction rolls back

- **WHEN** the normal transaction fails after the receipt insert
- **THEN** neither receipt nor corresponding observation, final stop or cursor change survives
- **AND** the next ordinary read continues from the durable prior cursor

#### Scenario: The conflict marker cannot be inserted

- **WHEN** changed same-sequence financial facts are observed but inserting their conflict marker fails
- **THEN** ordinary servicing may commit without qualifying the accounting
- **AND** repeating that changed observation cannot use the old unmatched receipt to qualify
