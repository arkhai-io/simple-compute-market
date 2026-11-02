# Arkhai mediation kit

This library speaks the Agreement-pinned `arkhai.mediation.v1` authority. It does
not contact payments, compute remedies or hold a servicing daemon. The owning
role supplies the exact Agreement, commitment reference and durable operation
store through `market_deal_lifecycle.adapters.submit_dispute`.

## First use

From a clean checkout, with the repository's normal Python/uv prerequisites:

```sh
make dist && env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 make -C kit/arkhai-mediation demo
```

This opens the library's actual filing/append/read surface against its installed,
vector-derived in-process fake: a payee claimant loses a filing response, reads
one case, retries the same key and appends evidence. Expected output includes
`unknown`, one case, `accepted`, and record sequences `[1, 2]`. No containers,
server, database, seed files or real credentials are needed. The target belongs
to the invocation; nothing remains running. The fake takes protection and ruling
answers as inputs, never simulates financial rules. Tests are library integration
against that peer; they are not hosted qualification.

```sh
env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 make -C kit/arkhai-mediation test
```

## Composition

- Construct `MediationClient` with the Agreement's `DisputeAuthority` and a
  `MediationCredential(identity, api_key_env)` reference. Identity is the entire
  interface/origin/account/record-key tuple, not just an account. The referenced
  environment variable supplies the party's owner-scoped bearer credential.
  Non-loopback origins require HTTPS. Redirects are never followed.
- Construct `MediationAdapter(binding, exact_agreement, client)`, then inject it
  into the neutral dispute table. The binding must match the Agreement's authority.
  `effects_request` builds validated free-form requests. `delivery_end` maps the
  neutral intent without sending seller payment stops or reversals. Supply the
  buyer's kept `SignedDeliveryEndClaim` as `concurrence=` on the adapter (or on
  `delivery_end_request`); adoption verifies the exact claim, Agreement digest and
  seller principal. Invalid concurrence can still be submitted as raw evidence
  in an `InterfaceRequest` for operator review. Neither mapper calculates remedies.
  Stable filing and append keys come from the
  foundation's operation store, which rejects changed command content before I/O.
- `read` verifies the pinned key, Agreement, transaction, sequence continuity and
  case association across all pages. It returns signed records as independent
  evidence and projects per-part/delivery effects. Aggregate penalties stay in
  the signed authority record: SCM must not invent their per-part decomposition.
  Per-case filing protection is not an assertion that a payment extension remains
  open; only a payment-authority read establishes that.
- Supply `capture=...` on the client to persist exact response bytes in the role's
  evidence store. The record projection also retains a canonical signed entry;
  that projection is not a substitute for exact transport-byte capture.
- The installed `contract` APIs expose exact schema/vector bytes, publication
  status and hashes. `models` exposes generated transport models. `claims` signs
  and verifies the published frame under both marketplace identity schemes;
  verification binds the seller, Agreement digest and optional exact case claim.

## Current boundary

The published delivery-end revision is vendored (see [provenance](schema/SOURCE.md)),
and the adapter maps delivery-end intents for either party. `RulingTraceFake`
replays the 14 published automatic-ruling/manual-guard/recovery traces, delegating
payments execution to an injected peer rather than implementing mediation rules.
The library integration suite compares canonical signed record, payment event,
receipt and snapshot bytes with the shared payments authority. The payments kit
is a test dependency only; this dispute kit does not import it.
The respondent HTTP client/poller, receipt embedding and setup-bearing presets
remain separate implementation work. Legacy exceptional-end/buyer-end requests are not
emitted. No hosted service is prepared or qualified by this package's demo.
