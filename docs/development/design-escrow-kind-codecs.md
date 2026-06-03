# Escrow Kind Codec Expansion

Scope and sequencing for supporting every escrow obligation shape under
`alkahest/contracts/src/obligations/escrow`.

## Current State

The market already treats escrow settlement as a codec dispatch problem:
`EscrowTerms` carries `escrow_contract` plus the concrete
`obligation_data`, and `service.clients.alkahest.get_escrow_codec_for`
resolves `(chain_name, escrow_address)` to an `EscrowKindCodec`.

Only `erc20_escrow_obligation_nontierable` is implemented today. Several
callers are still ERC20-shaped even though the wire model is more general:

- buyer proposal construction and escrow selection mostly reason about
  `token` and `amount`;
- listing display, pricing, and filtering use helpers like
  `accepted_token_address` and `primary_rate_value`;
- CSV escrow templates are easiest to express for one token plus one rate
  slot;
- buyer-side chain creation and seller-side settlement verification reject
  unknown codecs.

## Contract Coverage

Alkahest escrow obligations currently split into tierable and non-tierable
variants of the same seven obligation shapes:

- ERC20: `arbiter`, `demand`, `token`, `amount`
- native token: `arbiter`, `demand`, `amount`
- ERC721: `arbiter`, `demand`, `token`, `tokenId`
- ERC1155: `arbiter`, `demand`, `token`, `tokenId`, `amount`
- token bundle: `arbiter`, `demand`, native amount, ERC20 arrays, ERC721 arrays,
  ERC1155 arrays
- attestation request: `arbiter`, `demand`, `attestation`
- attestation UID: `arbiter`, `demand`, `attestationUid`

The tierable and non-tierable variants may share the same `ObligationData`
layout, but they still need distinct codec kinds and SDK paths.

## Goals

- Register codecs for each escrow obligation kind that can resolve its chain
  address, create the on-chain obligation, and read it back for verification.
- Keep `EscrowTerms` as the negotiated settlement artifact; do not add an
  out-of-band escrow kind field to the wire model.
- Make unsupported escrow kinds fail explicitly with kind/address context.
- Keep listing-side `accepted_escrows` as the seller's advertised shape:
  `(chain_name, escrow_address, literal_fields, rates)`.
- Add tests at the codec boundary first, then representative end-to-end tests
  once listing/proposal semantics are stable.

## Non-Goals

- Do not implement every possible marketplace policy for every asset class in
  the codec layer. Codecs encode/decode and call the SDK; negotiation policy
  decides what is acceptable.
- Do not force non-token escrows into ERC20 helpers such as
  `accepted_token_address`.
- Do not require a full e2e scenario for every tierable/non-tierable variant
  before exposing the first non-ERC20 codec.

## Phases

### Phase 1: Codec Registry and Unit Tests

Add codec classes for the straightforward asset escrows:

- native token, non-tierable and tierable;
- ERC721, non-tierable and tierable;
- ERC1155, non-tierable and tierable;
- ERC20 tierable, if the SDK path is available and matches the existing
  non-tierable behavior.

Each codec should have unit tests for:

- address resolution against the Alkahest address book;
- `obligation_data` normalization, especially `demand` bytes;
- SDK call shape for create;
- decoded obligation shape used by seller verification.

### Phase 2: Listing and Proposal Semantics

Generalize the places that currently assume ERC20:

- escrow selection should match by `(chain_name, escrow_address)` and policy,
  not just token address;
- displayed price/rate helpers should expose a generic primary rate and only
  expose token-specific helpers for token escrows;
- CSV escrow templates should support multiple rate slots and array-valued
  literal fields where needed;
- buyer proposal construction should derive `literal_fields` and rate-bearing
  `fields` from the selected accepted escrow, not hard-code `token`/`amount`.

This phase should preserve current ERC20 behavior and error messages for the
existing compute buyer flow.

### Phase 3: Seller Verification

Extend settlement verification so the decoded on-chain obligation can be
compared against `EscrowTerms.obligation_data` for all registered codecs.
The verifier should remain a byte/field compare, not a policy dispatcher.

Tests should cover:

- unsupported codec rejection;
- matching decoded obligation data;
- mismatched literal fields;
- mismatched rate-bearing fields;
- tierable and non-tierable address dispatch.

### Phase 4: Representative E2E Coverage

Add compose-backed e2e coverage for representative non-ERC20 flows rather than
every contract variant. A practical first set:

- native token escrow;
- ERC721 or ERC1155 escrow;
- token bundle if listing/proposal templates are stable.

The goal is to prove the buyer/storefront/provisioning settlement path works
with non-ERC20 codecs, not to exhaustively test Alkahest itself.

### Phase 5: Attestation Escrows

Handle attestation-request and attestation-UID escrows after the product
semantics are explicit:

- who supplies the attestation data or UID;
- whether it is a literal field, a rate-like field, or negotiated message
  content;
- how the seller advertises acceptable schemas;
- how the buyer proves or selects the attestation before settlement.

These codecs can still be mechanically implemented earlier, but they should
not be treated as product-complete until those semantics are settled.

## Open Questions

- Which Alkahest SDK methods exist for each tierable path, and do their return
  receipts all expose `log.uid` consistently?
- Should `accepted_escrows.rates[*].field` support nested paths for bundle
  arrays, or should bundles require a richer typed template shape?
- Should registry filters gain first-class non-ERC20 axes such as
  `escrow_kind`, `token`, `tokenId`, or native amount, or should they stay as
  JSONPath filters over `accepted_escrows`?
- What is the minimum useful e2e matrix for release confidence without turning
  the integration suite into an Alkahest contract test suite?
