## Context

The authority half landed already. `ReclaimRequest` carries an optional
`return_instructions_email`; the Stripe provider refuses a `us_bank_transfer.v1`
return without one, because Stripe returns a push-funded balance by mailing the
payer for return bank details and will not issue that mail with nowhere to send
it. The authority encrypts the address against the reversal reservation so
recovery can finish a reclaim whose caller never came back, and drops it once
the reversal is terminal.

The marketplace sends `OperationRequest(request_id=...)` and nothing else, so
every bank-transfer reclaim stops at that refusal.

## Goals / Non-Goals

Goals:

- The address reaches the hosted client from the buyer who owns it.
- No layer between them learns what it is.
- Nothing in marketplace state keeps it.

Non-Goals:

- No new persistence for the address, and no marketplace-side recovery of a
  reclaim whose address is gone. That is the authority's job and it already does
  it.
- No change to how the address is collected from a human. The buyer supplies it;
  where a buyer UI would get it is outside this change.
- No loosening of protected evidence or of the fail-closed release binding.

## Decisions

### The carrier is per-operation options, not bound mechanism params

`bind_mechanism_params` already accepts a mechanism-opaque mapping from the
storefront, which makes it the obvious candidate. It is the wrong one: its own
contract is "bind immutable, mechanism-safe materialization inputs", the values
merge into the obligation's accepted params, and they live as long as the
obligation. A payer's return address is none of those things — it is chosen at
reclaim time, for one reversal, and the whole point of the authority's lifecycle
is that it stops existing when the reversal finishes. Persisting it in
marketplace state would undo that.

So `reclaim` takes the options as an argument and forgets them. The runtime's
signature gains `mechanism_options: Mapping[str, Any] | None`, the port's
`reclaim_expired` gains the same, and neither reads a key.

### The options are bound into the reservation hash

`_reserve` already takes `request_values`, which `_request_hash` folds into the
digest that makes an operation idempotent. Reclaim currently passes none.

Passing the options there is what makes a second reclaim with a different
address a conflict at the marketplace edge instead of a provider-level
`idempotency_conflict` after a round trip. It is the same property the authority
gets from hashing the request body with `exclude_none=True`, applied one layer
out, and it costs nothing.

What this stores is a SHA-256 digest over the obligation reference, obligation
hash, operation, principal, and options together. It is not the address, it is
not linkable to the address without already knowing it, and the row it sits in
is the reservation the reclaim needs anyway.

### Only the hosted adapter names the address

`core_buyer.HostedSettlementTransport` documents itself as schema-opaque —
"Domain terms and provider models stay outside this boundary" — and the
settlement runtime has just been through a deliberate mechanism-neutrality pass.
Neither may say `return_instructions_email`.

The vocabulary belongs to whoever chose the mechanism: the caller that knows it
selected `us_bank_transfer.v1` names the key, and
`HostedSettlementAdapter.reclaim_expired` is the only code that reads it. When
the key is absent the adapter sends the same bare `OperationRequest` it sends
today, so every other profile is untouched and the authority keeps ownership of
which profiles require what.

### The harness uses the account's own registered address

Stripe declines to mail a third party from an account whose application is not
submitted, but will mail the address registered to the account itself. The
`us_bank_transfer.v1` lane therefore reads the connected account's own address
and reclaims to it. That exercises the entire path locally today; only a real
payer's return needs the account application submitted, which stays an explicit
external prerequisite rather than something the harness simulates.

### Binding 0.4.0 is a sequencing statement

Consuming a capability means depending on the release that declares it, so the
pin moves to `0.4.0` in `kit/hosted-settlement/pyproject.toml` and its two
followers. The protected path still requires a signed manifest and still fails
closed, which means a protected run cannot exercise this until 0.4.0 is
published; the local development lane can exercise it now.

## Risks / Trade-offs

- **An opaque mapping crossing four layers is unvalidated in transit.** Accepted:
  every layer that touches it is prohibited from acting on it, and the one layer
  that reads it validates against the client's own model, which constrains the
  address by pattern and length. The alternative — a typed field — would put a
  provider term in the neutral layers, which is the defect this change exists to
  avoid repeating.
- **The address is in a signed request body and therefore in the storefront's
  process memory.** Unavoidable for anything the buyer sends. It is not logged,
  not projected, and not stored; the storefront's existing rule that receipts and
  projections carry no payer identifiers already covers the outputs.
- **A reclaim that fails uncertainly must be retried with the same address.** The
  buyer holds it and resends it, which is what the retry loop already does. A
  retry with a different address is refused rather than accepted, which is the
  behavior above.

## Migration Plan

The option is absent everywhere until a caller supplies one, so every existing
lane keeps its current behavior. The pin bump is the only step with an ordering
constraint: build the 0.4.0 wheel from the producer's `.dist`, move the pin, run
`make fix-hosted-client-pin`, then relock.

## Open Questions

None.
