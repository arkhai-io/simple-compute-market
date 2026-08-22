## Why

The authority can return a bank-transfer funding to its payer, and refuses to
try without somewhere to send the payer's collection notice: `bank-transfer
return requires a payer return address`. Nothing in the marketplace supplies
one. A `us_bank_transfer.v1` buyer whose seller never delivers therefore still
cannot get their money back — the capability exists on one side of the boundary
and is unreachable from the other.

## What Changes

- The buyer's reclaim request carries mechanism-scoped options through the
  storefront to the mechanism client. The transport, the storefront routes, and
  the settlement runtime pass them without interpreting them; only the hosted
  adapter names what is inside.
- The hosted adapter turns a `return_instructions_email` option into the
  client's `ReclaimRequest`, and continues to send a bare `OperationRequest`
  when the profile does not need one.
- The reclaim reservation hashes the options it was given, so a second reclaim
  naming a different address is refused at the marketplace edge rather than
  becoming a provider-level idempotency conflict.
- The marketplace binds hosted-settlement client `0.4.0`, the release that
  declares `payer-return-instructions.v1`.
- The `us_bank_transfer.v1` reclaim lane in the real-Stripe harness supplies the
  connected account's own registered address and asserts the return is accepted.

Nothing persists the address in marketplace state. It is an argument to one
operation, and the authority — which does have to keep it across recovery —
already encrypts it and drops it when the reversal reaches a terminal state.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `settlement-servicing`: the provider-neutral conditional-escrow contract gains
  a mechanism-opaque per-operation option carrier for reclaim; mechanism clients
  keep sole ownership of what the options mean.
- `test-compatibility`: the `us_bank_transfer.v1` reclaim lane supplies a payer
  return address and proves the return is accepted.

## Impact

- `core/buyer/src/core_buyer/hosted_settlement.py` — `reclaim` gains an optional
  options mapping on the signed body.
- `kit/settlement-runtime` — `ports.py` contract, `runtime.reclaim`,
  `hosted_routes.reclaim`.
- `kit/hosted-settlement/src/market_hosted_settlement/adapter.py` — builds
  `ReclaimRequest`.
- `kit/contact-exchange/src/market_contact_exchange/client.py`,
  `kit/alkahest/src/market_alkahest/claim_hooks.py` — accept and ignore.
- Storefront reclaim routes in `domains/vms`, `domains/apicredits`,
  `domains/bare_metal`.
- `kit/hosted-settlement/pyproject.toml` and its two followers move to
  `arkhai-hosted-settlement-client==0.4.0`; affected `uv.lock` files refresh.
- `e2e-tests` — the reclaim lane and its unit coverage.
