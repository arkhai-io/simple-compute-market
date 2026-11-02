# Once payment adapter — first use

## Target and setup

Nonvisual library surface (visual: false; no screenshots). The prepared target
is this checkout's payments wheel and its kit-owned, invocation-owned
in-process authority fixture. There is no HTTP service, browser, external
deployment, shared seed, ignored configuration or secret.

Persona: a payee using public deterministic development accounts and a signing
identity defined in the example; never use that identity on a public network.
The example constructs the accepted Agreement, derives its exact mandate, and
installs an approved fixture receipt before driving the adapter.

From a clean checkout at repository root:

```sh
env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 \
  no_proxy=localhost,127.0.0.1 make dist
env -u ALL_PROXY -u all_proxy NO_PROXY=localhost,127.0.0.1 \
  no_proxy=localhost,127.0.0.1 uv run --no-project --no-cache --find-links .dist \
  --with .dist/arkhai_kit_arkhai_payments-0.3.0-py3-none-any.whl \
  python kit/arkhai-payments/examples/lifecycle.py
```

Readiness observed: selected generated models load, the wheelhouse resolves,
and the initial receipt and signed snapshot verify before a reverse is sent.

## Observations

- The shared PaymentsAuthority records a 100-unit voluntary reverse, then the
  client deliberately loses its response. Submit returns unknown.
- Read verifies the snapshot and returns one reverse; identical-key retry
  returns accepted with the same record, without submitting another reverse.
- Changed amount under the same key refuses; a partial refund leaves lifecycle
  state running and does not invent a delivery deadline.
- An explicitly scripted signed-read projection shows case A reversing 2500
  and case B reversing 1000 on the same once part. Both remain distinct
  authority events. Case A's lift closes ref 2, not case B's ref 4; the latter
  remains open. This is observation-side adapter evidence, not an execution of
  mediation or an extension-authority algorithm.
- The adapter requires a verifier and accepts a durable minimum-sequence floor.
  The current-pin helper verifies the snapshot signature and embedded receipt,
  exact Agreement/mandate identity and mode; rotation-aware verification is
  injected by the composition. The adapter does not keep a cursor or ledger.

## Verification

- Payments kit: 92 existing tests pass, generated models/resources and
  producer-vector conformance pass, mypy passes (23 source/example files).
- make lock refreshed dependency metadata for the direct lifecycle-contracts
  import and its consumers; make check-locks passes.
- make check-architecture, make check-packaging, make check-comment-hygiene and
  pinned OpenSpec 1.14.0 strict validation pass.
- Seller refunds now use per-part voluntary lifecycle commands. The first-use
  reconciliation encounters RefundUnavailable after a deliberately lost answer,
  then Refunded twice across retry/crash replay. There are exactly two voluntary
  reverses total: the original discount and the remaining-balance refund.
- A temporary diagnostic read the legacy whole-part reverse (which omits its
  amount), recovered the 10000-unit movement from signed cumulative state, and
  rejected a subsequently tampered snapshot.
- The isolated installed-wheel first-use command above passes. The editable
  convenience target make -C kit/arkhai-payments first-use also passes.
- Full make test passes (7m03s), including release-tooling and Helm checks, with
  the prescribed proxy environment and shell-local Podman shim. The release guide
  lists the new direct lifecycle-contracts dependency without duplicate entries.
- No permanent acceptance tests were added. No hosted or real-HTTP payment
  qualification is claimed; no outside resource is left running.

## Documentation destination

The adapter is introduced by d82242908; seller refund routing, reconciliation
and final aggregate evidence are committed with the 11.2 checkbox on this branch.

Reviewed closeout promotes payment translation, verified unknown recovery,
per-ref extension observation and voluntary seller refunds into the active
deal-lifecycle and settlement-servicing deltas and their permanent companions.
