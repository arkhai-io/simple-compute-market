## ADDED Requirements

### Requirement: New delivery eligibility is explicit accepted policy

The mechanism SHALL remain contact-exchange.v1. Exact versioned delivery policy
SHALL be included in public option hashing, obligation params and accepted
introduction package. Missing policy SHALL preserve old option identity and
create no two-sided jobs; malformed/unknown policy SHALL fail closed rather than
downgrade. Eligible work SHALL refuse legacy start before contact capture.
Acceptance and review SHALL persist no obligation contact payload or delivery job.

#### Scenario: Historical work encounters configured SMTP

- **WHEN** an old no-outbound accepted/unstarted/revealed agreement is read,
  started, replayed or encountered after restart with new SMTP configuration
- **THEN** its accepted terms and IDs remain unchanged and it gains no new jobs

### Requirement: Human finalization binds exact independent snapshots

A version-2 review SHALL validate both contact profiles/routes and bind exact
buyer input, accepted context/policy, buyer principal, finalization UUID and
seller resolved contact/route fingerprint for at most 300 seconds and no later
than obligation expiry. It SHALL disclose no seller contact/route before sharing.
Persisted salts/fingerprints SHALL be treated as confidential pseudonymous data.
Finalize SHALL require explicit consent and atomically recheck the bindings,
expiry and seller snapshot before immutable exchange/two-intent capture. A caller
SHALL freeze its reviewed own request in a short consent transaction before HTTP;
no local lock SHALL span the network call. Earlier drift requires fresh consent;
later settings edits SHALL NOT alter the captured request or message.

#### Scenario: Seller configuration drifts

- **WHEN** seller contact or route changes between review and finalize
- **THEN** finalize durably rejects before capture or jobs and requires new review

### Requirement: Finalization outcomes fence stale writers

Signed outcome reads and cancel SHALL use exact resource
`introduction-finalization:{obligation_ref}:{finalization_id}` reconstructed
from canonical path IDs. Method, operation, resource, request identity and
accepted buyer SHALL be bound; the HTTP path itself is not signed. They SHALL return only the exact intent outcome. GET SHALL perform no lifecycle mutation. Review/capture/expiry/rejection/cancel SHALL share
one serialized durable transaction boundary and terminal states SHALL NOT reopen.
Startup and five-second recovery SHALL expire reviewed intents. Unknown/reviewed
SHALL NOT authorize conflicting consent. A signed human-authorized same-ID cancel
SHALL fence late review and finalize even for an unregistered intent; it SHALL
return committed if capture already won and SHALL NOT undo sharing or the deal.
A caller SHALL clear its own frozen request on authoritative terminal reconciliation
while retaining identifiers/status and necessary authorization/timing metadata.

#### Scenario: Cancel wins before delayed review

- **WHEN** the accepted buyer fences an unresolved ID before its delayed review
  or finalize reaches the serialized transaction
- **THEN** a durable cancelled tombstone prevents either late writer from capture

#### Scenario: Capture wins a cancellation race

- **WHEN** capture commits before cancel can acquire the transaction
- **THEN** cancel returns authoritative committed, no route/contact is rewritten,
  and the caller recovers through its ordinary protected introduction read

#### Scenario: Expiry races finalize across restart

- **WHEN** expiry and finalize contend over the same persisted reviewed ID
- **THEN** exactly one durable terminal winner is observed after restart
- **AND** GET performs no contact capture, completion or dispatch
