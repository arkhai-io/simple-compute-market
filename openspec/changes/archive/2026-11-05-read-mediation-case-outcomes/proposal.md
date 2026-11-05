# Proposal

## Why

The mediation case reader validates a bare case even though the authority returns
an accepted-case or pending-protection envelope. Recovery of an existing
delivery-end filing therefore rejects a valid authority response.

## What Changes

- Read the existing strict filing-outcome envelope on case GETs.
- Preserve pending protection and reject mismatched case/deal bindings.
- Make the contract peer and recovery tests exercise the same envelope.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deal-lifecycle`: existing mediation case recovery distinguishes accepted and
  pending protection without repeating the original filing.

## Impact

`kit/arkhai-mediation` client, adapter, contract peer and integration tests.
The Python case method returns the existing `FilingAnswer` union rather than
`CaseAnswer`; its sole production caller is updated together. Refresh the paired published schema/vector resources and publication digests
through the documented producer/vendor procedure; generated transport models
remain unchanged. No new wire shape, database, deployment setting or dependency
changes. Financial mapping,
rulings and operator intervention are non-goals.

## Permanent documentation impact

- [x] Existing subsystem specification and companion architecture: `deal-lifecycle`.
- [ ] Repository-wide architecture: no ownership or dependency change.

### Knowledge to promote

Case reads preserve authority protection outcomes. An accepted case must match
the requested case and committed deal; the signed record remains the source of
filing evidence. Pending protection never authorizes a duplicate filing.
