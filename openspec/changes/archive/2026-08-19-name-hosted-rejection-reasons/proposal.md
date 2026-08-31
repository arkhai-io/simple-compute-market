## Why

A hosted deal can be parked forever with nothing said about why. When the hosted
authority refuses an operation with a non-retryable error, the adapter raises
`SettlementManualRequired("hosted settlement <operation> rejected")` — the
authority's own stable error code is dropped, the released client's exception is
severed with `from None`, and the obligation is recorded as `manual_required`
with no mechanism reference, no receipt, and no reason. The projection every
consumer reads then carries a status and nothing else.

The redaction is deliberate and correct: the released client's message can name
provider detail, and this boundary exists to keep that out of marketplace
persistence and buyer-facing responses. But the authority's `code` is not
provider detail — it is the authority's own stable vocabulary, the half of the
error that is safe to keep, and it is being discarded with the half that is not.

This is not hypothetical. A real `card.v1` collection lane against the real test
account reaches materialization and stops there: `status='manual_required'`, no
settlement identity, no reason. An operator holding that obligation cannot tell
an unsupported funding profile from a rejected condition from an account that
lost a capability, and neither can the marketplace.

## What Changes

- The released-call boundary keeps the authority's stable error code and drops
  only its message, so a rejection names itself without naming the provider.
- An obligation parked as `manual_required` projects a stable reason, in the
  field consumers already read for a funding reason, across every domain that
  adopts the hosted mechanism rather than in one of them.
- The e2e fixture that asserts on a materialization result reports what the
  result actually was rather than only that it was wrong.
- Whatever rejection the real lane then names is diagnosed, and fixed here if it
  is a marketplace defect; if it is an authority-side or configuration matter it
  is recorded for `add-bare-metal-hosted-settlement` rather than resolved here.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-servicing`: the requirement governing hosted adapter validation and
  state projection gains the obligation that a non-retryable rejection is
  recorded and projected with the authority's stable code, and that
  `manual_required` is never projected without a reason.

## Impact

- `kit/hosted-settlement` — the released-call error mapping.
- `kit/settlement-runtime` — the manual-required finish path and the shared
  projection surface the domains build on.
- `domains/vms/storefront`, `domains/apicredits/storefront`,
  `domains/bare_metal/storefront` — three copies of the hosted status
  projection, which is why the reason belongs in the shared surface.
- `e2e-tests` — the hosted materialization assertion.

No wire, listing, negotiation, or obligation shape changes. The redaction
boundary is preserved: provider messages, identifiers, and payloads stay out of
persistence and responses exactly as they do today.
