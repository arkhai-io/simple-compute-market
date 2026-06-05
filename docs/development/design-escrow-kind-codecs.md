# Escrow Kind Codec Expansion

Scope and sequencing for supporting every escrow obligation shape under
`alkahest/contracts/src/obligations/escrow`.

## Current State

The market already treats escrow settlement as a codec dispatch problem:
`EscrowTerms` carries `chain_name`, `escrow_contract`, and the concrete
`obligation_data`, and the buyer submit hook resolves each
`(chain_name, escrow_contract)` to an `EscrowKindCodec`.

ERC20, native-token, ERC721, ERC1155, token-bundle, attestation-request, and
attestation-UID tierable/non-tierable codecs are implemented. Negotiation still
uses `EscrowProposal` as the per-round message shape, but accept paths now echo
`accepted_escrow_terms`: concrete `list[EscrowTerms]` materialized from the
final accepted proposal. Split settlement commands consume those final terms
directly and only rebuild from `EscrowProposal` for older run logs.

Remaining ERC20-shaped or policy-specific surfaces:

- the bundled/default compute policies mostly reason about one scalar
  `amount`; native token, ERC20 tierable, and ERC1155 can reuse that policy
  shape, while ERC721, bundles, and attestation escrows need caller-supplied
  policy or the packaged exact-match guard;
- listing display, pricing, filtering, refund, and some admin helpers still
  use convenience helpers like `accepted_token_address` and
  `primary_rate_value`;
- token bundle final-term materialization supports field-path assignment for
  array paths such as `erc20Amounts[0]`;
- claim/reclaim/show convenience commands now dispatch through escrow codecs
  when the escrow address is known, with best-effort codec discovery for raw
  UID inspection/reclaim; manual refund remains an explicit ERC20-transfer
  helper separate from codec-backed failure-policy refunds.

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
- Do not require the project to ship default negotiation policies for every
  escrow kind before the codecs exist. The default policy surface may remain
  compute/ERC20-oriented; users can supply policies for other escrow formats.
- Add tests at the codec boundary first, then representative end-to-end tests
  once listing/proposal semantics are stable.

## Non-Goals

- Do not implement every possible marketplace policy for every asset class in
  the codec layer. Codecs encode/decode and call the SDK; negotiation policy
  decides what is acceptable.
- Do not package default policies for every non-ERC20 format. A generic
  "accept only if the proposed escrow terms exactly match the listing
  template; reject otherwise" guard is enough baseline behavior.
- Do not force non-token escrows into ERC20 helpers such as
  `accepted_token_address`.
- Do not require a full e2e scenario for every tierable/non-tierable variant
  before exposing the first non-ERC20 codec.

## Phases

### Phase 1: Codec Registry and Unit Tests

Add codec classes for the escrow obligation variants under
`alkahest/contracts/src/obligations/escrow`.

Implemented:

- ERC20, non-tierable and tierable;
- native token, non-tierable and tierable;
- ERC721, non-tierable and tierable;
- ERC1155, non-tierable and tierable;
- token bundle, non-tierable and tierable;
- attestation-request, non-tierable and tierable;
- attestation-UID, non-tierable and tierable.

Each codec should have unit tests for:

- address resolution against the Alkahest address book;
- `obligation_data` normalization, especially `demand` bytes;
- SDK call shape for create;
- decoded obligation shape used by seller verification.

### Phase 2: Listing and Proposal Semantics

Generalize the places that currently assume ERC20:

- escrow selection already matches by `(chain_name, escrow_address)`, but
  optional filters and UI still expose token-oriented conveniences;
- displayed price/rate helpers should expose a generic primary rate and only
  expose token-specific helpers for token escrows;
- CSV escrow templates already support multiple named rate slots and
  array/indexed contract field paths through aliases:
  `escrow_templates.<name>.rates.<alias>.field = "erc20Amounts[0]"`, with
  CSV cells using the flat alias (`bundle:usdc=180,credits=10`);
- final-term materialization assigns those field paths into nested/indexed
  `obligation_data` for token bundles;
- buyer proposal construction already carries selected `literal_fields`,
  `rates`, and listing-level `demands`; keep hard-coded `token` handling only
  as a convenience for token-shaped default flows.

This phase should preserve current ERC20 behavior and error messages for the
existing compute buyer flow.

### Phase 3: Seller Verification

Settlement verification now materializes the final proposal into
`EscrowTerms` and compares decoded chain obligation data against
`EscrowTerms.obligation_data`. Keep the verifier a byte/field compare, not a
policy dispatcher.

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

Attestation-request and attestation-UID escrow semantics are policy-owned, not
product-level codec behavior. The codec only carries whatever
`obligation_data` the negotiated terms require. A seller policy may require a
specific attestation and encode it in the listing like a fixed token price,
because the buyer creates the attestation escrow as payment; another policy may
negotiate the attestation parameters, especially once more freeform negotiation
strategies exist.

The codecs are mechanically implemented so user-supplied policies can target
them. Treating an attestation escrow as a default marketplace flow requires a
policy that defines:

- who supplies the attestation data or UID;
- whether it is a literal field, a rate-like field, or negotiated message
  content;
- how the seller advertises acceptable attestation schemas or predicates;
- how the buyer proves or selects the attestation before settlement.

## Open Questions

- Registry filtering should follow the schema-plugin model in
  `design-market-core-extraction.md`: filters are packaged with the registry
  schema and buyer CLI plugin, with generic `--filter name=value` passthrough
  as the core fallback.
- What is the minimum useful e2e matrix for release confidence without turning
  the integration suite into an Alkahest contract test suite?
