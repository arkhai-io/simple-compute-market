# Add buyer compute RFQs

## Why

A buyer who needs a block of compute for a term can search advertised supply, but cannot
publish the requirement so that sellers can respond. For example, a buyer may need 100
eight-GPU nodes for six months and welcome introductions to more than one provider.

An implementation of an earlier design of this change exists on its branch,
`feat/buyer-compute-rfqs` (pull request #401). Its review on 2026-11-27 replaced that
design: buyers sign RFQ operations with their own marketplace principal rather than
through a delegated account authority, contact custody is shared with the
contact-exchange mechanism rather than duplicated, and the request is structured
throughout. This proposal and its design state the design the branch must implement
before it merges. The branch's code predates it.

## What Changes

- **A buyer publishes structured compute demand in the registry.** An RFQ states what a
  seller's listing states — the same shape and terms vocabulary, validated by the
  listing schema and filter specification the registry already loads — plus the
  demand's own fields: node count, region codes, start window, term and a response
  deadline (design D4, D5).
- **Callers sign RFQ operations with their own marketplace principal**, verified as
  every other signed registry route verifies its caller. The principal owns its RFQs
  and responses (D1).
- **RFQ writes are admitted as the registry's other writes are**: open, by an
  operator-issued key, or by a buyer account service's admission certificate, through
  `add-buyer-account-login` (D2).
- **Any admitted caller other than the buyer may respond**, optionally with a partial
  node count, without a seller role or listing. A respondent consents to share a chosen
  contact with the buyer if selected; the buyer consents when selecting. Only then may
  that pair read each other's contact (D6).
- **Contacts are held by the shared introduction custody layer**, which
  `unify-introduction-custody` builds for both this change and contact-exchange
  settlement. This change adds only the stage before selection: respond, withdraw,
  dismiss and close (D7).
- **Only the deadline is editable.** Any other change is close and repost, and closing
  may name the replacement RFQ (D8).
- **Records are bounded**: a maximum deadline horizon, bounded field sizes, a request
  body limit, and configurable caps on open RFQs and pending responses per principal
  (D9).
- **An operator can take an RFQ down** (D10).
- **Open RFQs are browsable without signing in** where the registry's supply discovery
  is public, without party references, responses or contacts (D3).
- **No free text is published** on an RFQ (D5).
- **The marketplace flow ends at the introduction.** The parties arrange any contract
  themselves.

The engineering detail is open in the design's "Open Questions".

## Capabilities

### New Capabilities

- `buyer-compute-rfqs`: compute requests, responses, consent, and access to
  introductions.

### Modified Capabilities

- `registry-discovery`: an RFQ route family beside listing discovery, sharing its
  admission and its listing schema.
- `contact-exchange-settlement`: the introduction custody layer gains a pre-selection
  stage used by RFQs (with `unify-introduction-custody`).

## Dependencies and Related Changes

- Depends on `add-buyer-account-login` (admission certificates) and
  `unify-introduction-custody` (contact custody) for implementation.
- `search-rfqs-in-the-database` follows it: this change filters RFQs as the registry
  filters listings today.
- `rotate-registry-account-principals` follows it: until then a principal owns its RFQs,
  and a changed key cannot carry them.
- `deny-banned-buyer-accounts` follows `add-buyer-account-login`.
- `redesign-authenticated-requests` is redesigning the shared request envelope and
  replay retention; this change's retry rules follow whatever it settles.

## Permanent documentation impact

- [x] The repository's architecture document
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: principal ownership to the new `buyer-compute-rfqs` capability and
  `docs/development/ARCHITECTURE.md`.
- D2: write admission to `buyer-compute-rfqs` and `registry-discovery`.
- D3: public browsing to `buyer-compute-rfqs` and `registry-discovery`.
- D4: requests mirroring listings to `buyer-compute-rfqs` and `docs/development/ARCHITECTURE.md`.
- D5: no free text, typed terms and region codes to `buyer-compute-rfqs`.
- D6: consents and introductions to `buyer-compute-rfqs`.
- D7: custody through the shared layer to `buyer-compute-rfqs`.
- D8: deadline-only edits to `buyer-compute-rfqs`.
- D9: bounds and caps to `buyer-compute-rfqs`, `registry-discovery`'s configuration and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D10: takedown to `buyer-compute-rfqs` and `docs/operator-handbook.md`.
- D11: the flow ending at the introduction to `buyer-compute-rfqs`.
- The capability is indexed in `openspec/specs/README.md`, and its terms (RFQ, respondent,
  party reference) go to `docs/development/ARCHITECTURE.md`, "Shared vocabulary and
  identities".
