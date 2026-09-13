## MODIFIED Requirements

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

Ordinary publication and refresh MUST omit optional lifecycle status. Reopening
a tracked listing MUST publish the same identifier with explicit `open` status.
For refresh and reopen, the storefront MUST authenticate a read against each
exact configured target and compare the typed listing projection with the
current request's listing identifier, authenticated publisher ownership,
storefront URL, offer, accepted escrows, settlement options, demands, maximum
duration, and expected status. A target's configured registry authority and
trust set MUST come from local validated configuration, never from the remote
response.

Candidate eligibility, durable capacity binding, and current availability MUST
be established before registry I/O. Only an authenticated not-found response
MAY authorize creation for that already-eligible target. Authentication,
authority, transport, parsing, timeout, and other read failures are unknown and
MUST NOT authorize a write. A refresh of a found record requires it to be open;
a reopen explicitly requests open. The GET/POST/GET observations are not an
atomic transaction, so a concurrent status or term change is a mismatch rather
than a preservation guarantee.

Every confirmed lifecycle outcome, including an already-matching authenticated
preflight read, MUST have a durable publication receipt before the domain's
local commit. The immutable operation result MUST distinguish whether required
receipt persistence and publication-event delivery completed. Recovery MUST
retry an outstanding persistence or event side effect without rewriting an
already-confirmed target, and local commit MUST remain blocked until both
required side effects complete. At least one exact-target confirmation permits
that commit under the existing
aggregate compatibility rule, but any unconfirmed intended target makes the
lifecycle result partial. Partial convergence MUST remain visible to an
operator and MUST NOT be reported as full convergence. A rejected, unapplied,
unreadable, persistence-failed, or locally uncommittable transition MUST retain
safe known target receipts and MUST NOT falsely report local success.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

#### Scenario: A closed registry record is relisted

- **WHEN** capacity returns and a tracked closed listing is republished
- **THEN** the registry record is transitioned to open under the same identifier
  and confirmed by read-back before the local and tracking records are advanced

#### Scenario: The registry record does not become open

- **WHEN** the status transition is rejected, unapplied or unconfirmable
- **THEN** the round reports the candidate as failed, the local and tracking
  records stay closed, and repeating the round retries the same identifier

#### Scenario: One configured registry remains unconfirmed

- **WHEN** at least one target confirms the current request but another target
  rejects it or cannot be confirmed
- **THEN** the allowed local commit may occur, but the lifecycle result remains
  partial with ordered safe per-target outcomes and the operator command keeps
  the candidate in its failed collection

#### Scenario: Refresh preflight is unavailable

- **WHEN** an exact target cannot provide an authenticated listing or
  not-found response during refresh preflight
- **THEN** no publication is sent to that target and its state remains unknown

## ADDED Requirements

### Requirement: Publication recovery is bound to one immutable intent

Each refresh or reopen invocation MUST create a new intent bound to the listing,
durable capacity binding, transition, canonical typed request, authenticated
publisher identity, configured target order, and each target's normalized URL,
authority, and trust set. Every new invocation MUST examine every configured
target; historical publication rows or success from an older intent MUST NOT
skip a target.

The candidate identifier and the identifier serialized by its domain payload
MUST be exactly equal before opening a registry client. The runtime MUST fan out
the canonical request produced by that validation; an identity mismatch MUST
perform no registry read, registry write, event, receipt, or local commit.

Recovery MAY act only on an explicitly supplied result from that exact intent.
Already-confirmed targets MUST NOT be rewritten. A definitively rejected write
MAY be repeated with the identical request. A successful write with unknown
readback, a transport-ambiguous write, or a confirmation mismatch MUST receive
authenticated read-only reconfirmation and MUST NOT trigger a blind write. The
runtime MUST NOT keep recovery identity in a shared mutable current-operation
slot, and this contract does not require a journal, scheduler, or automatic
retry loop.

#### Scenario: Terms change after an earlier successful publication

- **WHEN** a later refresh carries different canonical terms
- **THEN** it examines every configured target and an older successful row does
  not satisfy the new intent

#### Scenario: Readback is interrupted after a successful write

- **WHEN** a target accepts a write but its same-target readback is unavailable
- **THEN** recovery reads that target without repeating the write and commits
  locally only after a matching authenticated projection is observed

#### Scenario: Only one target definitively rejected the write

- **WHEN** an exact-intent recovery contains confirmed targets and one known
  rejected target
- **THEN** only the rejected target receives the identical write while all
  other nonconfirmed outcomes are read-only

#### Scenario: Receipt persistence remains unavailable during recovery

- **WHEN** registry confirmation succeeded but receipt persistence repeatedly
  fails
- **THEN** each recovery retries persistence without repeating the registry
  write, event delivery remains outstanding, and local state remains unchanged
  until persistence and the event both succeed

#### Scenario: Partial reopen already committed locally

- **WHEN** one target confirmed a reopen, another target rejected it, and the
  allowed local commit already changed the listing to open
- **THEN** exact-intent recovery accepts that expected open local state, retries
  only the rejected target, and does not repeat the local commit
- **AND** changed binding, unavailable capacity, or stale local state still
  rejects recovery before registry I/O

### Requirement: Explicit refresh of an open listing keeps its identity
A publication round MUST leave an already-open derived listing untouched. An
operator MAY name one tracked open listing for refresh, and the round MUST then
republish that listing under its existing identifier from freshly built terms,
never as a second listing identity, so agreements already accepted against it
remain valid. The named target MUST be refused without any write unless it is
tracked by this storefront's derivation, its local listing is open, and its
resource is present in the current available candidates. Refresh MUST publish
and confirm the registry before atomically replacing local listing terms and
its derived mapping state. It MUST preserve local lifecycle status and pause
state. Reopen performs the same atomic local update but sets the listing and
derived mapping open and clears pause. A remote, receipt-persistence, or local-
commit failure MUST NOT be reported as local success. That guarantee covers
local state only: a publication accepted before a later failure may leave the
registry advertising the new terms, and refresh MUST NOT be read as rollback
or as atomicity across the two stores.

#### Scenario: Settlement configuration changes for a served listing
- **WHEN** an operator refreshes one tracked open listing by identifier
- **THEN** the registry and the local record carry the new terms under the original listing identifier, and every other open listing is skipped

#### Scenario: Refresh publication fails
- **WHEN** registry publication of a refresh fails
- **THEN** local terms are unchanged, the candidate is reported as failed, and repeating the refresh republishes the same identifier

#### Scenario: Refresh names an untracked or unavailable listing
- **WHEN** the named identifier is not a tracked open listing derived from a currently available resource
- **THEN** the round is refused before any registry or local write
