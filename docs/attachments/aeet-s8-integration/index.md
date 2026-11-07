# Hosted policy integration qualification

This is nonvisual implementer qualification of the joined buyer-policy,
servicing and snapshot-verification changes, not independent acceptance.
No screenshots apply. The starting revision is `ed479ab8b`; `s8` was merged
at `1d65a83e0`, followed by verifier delegation at `c64865c7f` and the
multi-registry approval repair at `50d50ee31`.

## Conflict resolutions

- API-credit selection keeps the shared `AuthoritySelection` preference hook:
  exact authority identity and params, registry-local acceptance, advertised
  minima, installed interface and configured authority order. The second
  API-credit-only authority filter is removed rather than applied twice.
  Payments compatibility retains the mechanism-specific authority account
  validation. Approval resolves accepted authorities again and retains the
  buyer's exact mandate check before approval I/O.
- API-credit authority configuration uses one resolver shared by selection and
  approval. Existing negotiation and storefront fixture assertions remain;
  their lifecycle/authority setup uses the same deterministic fixture, and the
  selection seam asserts the full advertised option and listing context.
- Seller servicing keeps per-part lifecycle reversal, stable operation keys,
  verified authority reads and refund replay behavior. Its per-agreement
  verifier factory remains injectable and defaults to the rotation-aware
  shared receipts verifier.
- The single-pin `pinned_snapshot_verifier` delegates to `receipts.verify_snapshot`;
  there is no separate signature frame or verification algorithm.
- The release dependency table contains each distribution once and preserves
  both sides' declared dependencies.

## Reproducible local regression entry point

Run from this revision in a disposable checkout with the repository's Python,
UV, build and container prerequisites installed:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/arkhai-payments test
make -C domains/apicredits/buyer test
make -C domains/apicredits/storefront test
make -C kit/deal-lifecycle-buyer test
make check-locks check-packaging check-architecture check-comment-hygiene
bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict
make test
```

The aggregate needs a Docker/Compose-compatible engine. Qualification uses an
explicit local rootless Podman compatibility shim, not an inherited remote
container target. HTTP(S) download proxies remain available; scenario traffic
bypasses proxies. The product's existing library first-use command is recorded
in [the hosted-policy packet](../hosted-lifecycle-policy/index.md#first-use-entry-point).

## Observed checks

| Check | Result |
|---|---|
| `make dist` | Pass |
| Payments kit (`make test`, including typing, vectors and generated-model checks) | 97 passed |
| API-credit buyer | 35 passed |
| API-credit storefront | 248 passed |
| Deal-lifecycle buyer | 18 passed |
| Locks, packaging, architecture and comment hygiene | Pass |
| Strict pinned OpenSpec validation | Pass |
| Full `make test` | Pass at `50d50ee31` using the local Podman shim and proxy exclusions; completed in 7m 20s |
| API-credit real local payment journey | 3/3 passed against the real local ledger; all four payment checkpoints observed |
| Scoped documentation citations | The same three planned lifecycle spec/architecture destinations tracked in [#325](https://github.com/arkhai-io/simple-compute-market/issues/325); no placeholder document or weakened checker |

After verifier delegation, the payments kit's 97 tests, typing, vectors,
generated-model check, packaging and comment hygiene passed again. After the
multi-registry approval repair, distributions, buyer/storefront tests,
packaging and comment hygiene passed again, followed by the complete aggregate
and the live re-drive below. The aggregate reports one collection skip in the
VM storefront's optional Torch-dependent middleware tests; the required payment
journey has zero skips.

The first live attempt reached agreement with a dispute-bearing option but
approval refused a multi-registry buyer: fetching only the selected registry's
descriptor incorrectly ran exact pin-set validation against that subset.
The repair validates pins against all configured registry URLs, then fetches
only the selected registry's descriptor under those pins. It does not weaken
the exact configuration boundary or reuse another registry's recommendations.
The first owned deployment was fully torn down before re-drive; its dependent
replay/refund failures were not separate payment observations.

## Live local payment replay requirements

The required surface is the three existing calls in
[`test_credits_payment_deal.py`](../../../e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py).
Use the [payment qualification topology](../settlement-option-envelope/index.md#api-credit-local-payment-qualification-2026-11-02)
and [shared payment configuration](../../../e2e-tests/README.md#shared-payment-scenario-configuration).
A real development payment authority and ledger are required, not a kit fake.

In addition to that topology, republish with adjudication terms and supply a
real mediation authority's interface, origin, account, record key, params and
advertised minima. Configure the API-credit registry's
`REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES` with that exact entry;
the seller and wallet-free buyer opt into registry recommendations. The
publication clause must include `dispute_window_seconds` at least the
advertised minimum, with a compatible `case_hold_max_seconds` (null for an
unbounded advertised minimum). Payment `window` and dispute window are
separate inputs. Keep all principals and credentials deterministic development
fixtures, never public-network credentials.

Readiness must succeed before pytest: owned Compose health checks, payment
health from host/seller/buyer, mediation health, and an authenticated listing
read showing `option["settlement"]["schema"] == "arkhai.payments.v1"` plus the
expected lifecycle authority. The envelope-reader workaround is tracked in
[#327](https://github.com/arkhai-io/simple-compute-market/issues/327).
Then, inside the branch-built runner with its funded accounts and `PAYMENTS`
profile configured, open the story directly:

```sh
.venv/bin/pytest -q --tb=short \
  tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py
```

## Observed live local payment outcome

The re-drive at `50d50ee31` passed all three existing payment tests in 5.54
seconds after the readiness gate. The payment, ledger, mediation, registry,
storefront and buyer processes were local and isolated. The published
`arkhai.payments.v1` option included `arkhai.mediation.v1` adjudication, a
1,209,600-second dispute window and an unbounded case hold. The served
mediation description matched the registry recommendation and accepted terms.
The buyer used loopback payment authentication; the funded buyer, seller and
authority were deterministic development personas, not public-network accounts.

The observer confirmed all four checkpoints:

| Phase | Observed outcome |
|---|---|
| Baseline | Buyer funded; seller has no held payment |
| Held | Credits issued and callable; buyer debited 3,000,000 USD/6 units; one seller part holds that amount |
| Replayed | Same transaction and held amount; same delivered credential; no second debit |
| Refunded | Part reversed for the full held amount; buyer baseline restored; seller has no held payment |

Readiness verified the dispute-bearing publication before pytest rather than
mistaking a running container for an eligible option. Both failed and passing
owned deployments were torn down. Cleanup reported no remaining owned
resources, and the service source checkout was unchanged. No server is left
running for this qualification. These are implementer observations, not an
independent acceptance verdict. No raw operator logs, credentials or external
runtime artifacts are published in this packet.
