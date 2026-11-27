## Why

A buyer receives an API key's secret once, in the seller's signed settlement
status, and today keeps it by appending the whole `tenant_credentials` mapping,
the secret included, to its run log as a `credentials_delivered` event. Both the
buy command and every resumed settlement do so, through the api family's
buying library. The run log is the buyer's only durable copy, and both API-credit
end-to-end scenarios read the secret back from it.

That contradicts `buyer-orchestration`'s "Buyer evidence is separate from private
delivery": delivery results and credentials stay behind the domain's private
result boundary and out of the run log. No buyer in the repository has such a
boundary on its side, so the fix is a storage design rather than a relocation.

## What Changes

- Add a private buyer credential store behind an abstraction, with a `0600`
  file under the buyer's XDG state directory as the first implementation and a
  keyring implementation optional.
- Record in the run log a non-secret reference in place of the secret: the
  delivery status, the key ID, the credential reference, and the store that
  holds it.
- Add a retrieval command for buyers and scenarios, so the secret is read from
  the store, never from the run log.
- Define the outcome when settlement succeeds but the private write fails,
  without losing a secret the seller will not return again.
- Define how existing `credentials_delivered` events that carry a secret are
  read and whether they are migrated.
- Keep the secret out of logs, exceptions, and command output except where the
  buyer asks to see it.
- Migrate `e2e_credits_deal` and `e2e_credits_payment_deal` to the retrieval
  command.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `buyer-orchestration`: a delivered bearer credential is kept in the buyer's
  private store; the run log records only its non-secret reference.
- `api-family`: the buying library persists delivered credentials through the
  store.

## Non-Goals

- No change to what the seller delivers or how it signs it.
- No change to the authority's key handling.
- No change to the buyer's mechanism inputs or command-line flags.

## Impact

- Code: `domains/api/buying` (the buy and settle paths and their shared resume
  steps), the store's home, and the API-credits buyer plugin's tests.
- Tests: the store's unit tests, the CLI's application-integration tests, and
  both API-credit end-to-end scenarios.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/buyer-orchestration/spec.md`;
  the `api-family` specification.
- [ ] New subsystem specification

### Knowledge to promote

- Where a buyer keeps a delivered credential and what its run log records
  instead — `openspec/specs/buyer-orchestration/spec.md`.

## Dependencies and Related Changes

- Depends on `compose-api-family-kit`, whose buying library it changes; opened
  by that change's section 10 review, which records this as an owned deferral.
- A follow-up change on the same commands removes the mechanism override flags.
