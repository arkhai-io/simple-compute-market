# Settlement-option envelope — implementation evidence

## Scope and contract

This packet covers task 2.5, including 2.5b and 2.5c, of
`agreed-evidence-and-early-termination`. It records implementer self-checks and
existing regression suites, not independent acceptance. The initial suites cover
the wire-flip commit introducing this packet; the final API-credit payment run
covers `9e4fe5aff3b001a187576ac24cf9364eac55664d` on 2026-11-02.
Reviewed-closeout promotion remains in the change's specification deltas.
This is a nonvisual wire/library/CLI journey; no screenshots apply.

Before: options carried `{option_id, mechanism, asset, rates, params}`.
After: options carry `{option_id, price?, settlement, lifecycle?}`. The settlement
parameters are flat beside `settlement.schema`; lifecycle identity is separate.
Selections carry the schema-tagged settlement envelope with buyer-owned inputs;
Agreement `settlement_params` excludes its schema tag. IDs hash sorted compact
JSON of the new payload. Absent optional price/lifecycle keys are omitted.
All listings must be republished; no old-shape compatibility reader was added.

Mediation's producer projection gate is satisfied. Its schema and regenerated
vectors are copied from the published revision identified only in
[`SOURCE.md`](../../../kit/arkhai-mediation/schema/SOURCE.md). Payments contract
bytes did not change. The local mediation adapter and ruling-trace fixture now
read lifecycle terms at their new location, without rewriting the Agreement.
No gate-related xfail or skip remains.

## Setup and entry points

Use a disposable checkout of this branch. No inherited service or credentials
are required for the in-process checks. All commands below use:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
```

The existing in-process first-use surface is:

```sh
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && uv run --find-links ../../../.dist python examples/payment_smoke.py)
```

It uses injected payment/provisioning seams and deterministic development
principals, with no resident service, external account, seed, or browser.
Observed output: before approval, zero pending deliveries; after approval,
`provisioning`; retry, `ready` with one delivery; zero escrow rows. This proves
agreement-only dispatch through the app seam, not live payment settlement.

For fresh infrastructure runs, use the public lane targets with a Docker/Compose-
compatible engine. The execution used a verified rootless Podman compatibility
shim only in lane shells. Each lane name was checked unused before startup;
stacks and buyer images were built from the branch, not reused deployments.

```sh
make -C e2e-tests test-e2e-vm E2E_MODULE=e2e_deal PYTEST_ARGS=-q
make -C e2e-tests e2e-vm-down
make -C e2e-tests test-e2e-bare-metal E2E_BARE_METAL_MODULE=e2e_bare_metal_mock_deal PYTEST_ARGS=-q
make -C e2e-tests e2e-bare-metal-down
make -C e2e-tests test-e2e-apicredits E2E_APICREDITS_MODULE=e2e_credits_payment_deal PYTEST_ARGS=-q
make -C e2e-tests e2e-apicredits-down
```

The payment lane additionally requires the explicit ready payment policy in
[the shared payment-scenario setup](../../../e2e-tests/README.md#shared-payment-scenario-configuration).
The initial run had no target and skipped; the follow-up below supplied a real
local authority and passed with zero skips. A successful process exit alone is
not payment-journey evidence.

## Observed results

| Required claim / command | Observation |
| --- | --- |
| Core, buyer, registry, mechanisms, VM/bare-metal/API-credit unit and application-integration suites | Full `make test` passes, including payment admission, accepted selection/Agreement retention, fulfillment dispatch, and registry filters. |
| Published mediation projection and trace replay | `make -C kit/arkhai-mediation test` passes: contract/signature/vector checks, model drift, mypy and 40 tests, including 14 ruling traces. Models were regenerated with `make -C kit/arkhai-mediation generate-models`; no generated model diff was needed. |
| Core typing | `make -C core typecheck-core` passes (9 source files). |
| Architecture | `make check-architecture` passes; also included in packaging checks. |
| Fresh wheels, locks, install boundaries | `make check-packaging` passes after the final source changes. |
| Comments | `make check-comment-hygiene` passes. |
| Active specification deltas | `bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict` passes. |
| Republished VM deal | `e2e_deal`: 35 passed. |
| Republished bare-metal mock deal | `e2e_bare_metal_mock_deal`: 39 passed. |
| API-credit payment deal, real local authority | `e2e_credits_payment_deal`: **3 passed, 0 skipped**, in 5.14 seconds. Purchase/issuance/consumption, unchanged settlement replay and seller reversal pass; baseline/held/replayed/refunded balance observations all pass. See the local qualification below. |

The aggregate tooling suite needs `docker compose` for configuration rendering.
On this runner, a temporary config-only wrapper invoked the standalone Compose
binary; it provided no daemon or fake service behavior. The normal lane shim
was not placed on the aggregate suite's PATH.

## Repairs, limits and cleanup

The first branch-built VM run exposed an e2e helper reading the retired
`entry['mechanism']`. That helper now uses the schema accessor; its re-drive
passes all 35 cases. Earlier focused/aggregate runs exposed additional direct
option and selection attributes and fixture assumptions; these were migrated,
and the final full aggregate passes. No kept acceptance assertion was removed
or weakened to hide the wire change. The advertised-price comparison is now
conditional on a price being present, because rateless introductions have none.

Task 2.5's three named end-to-end suites now pass. The original missing-target
skip was an environment prerequisite, not a mediation-projection failure.
The successful payment run used a real local authority, not a hosted deployment
or a lane double. Deterministic isolated payment-lane doubles remain owned by
[`add-arkhai-payments-lane-double`](../../../openspec/changes/add-arkhai-payments-lane-double/).
The optional Alkahest release-model section 4 is outside this implementation.

All owned lane containers, volumes and networks were removed. Native Anvil
children left by the lane scenarios were stopped by their owned process groups;
no Anvil child, server, tunnel, or browser remains from this work.

## API-credit local payment qualification (2026-11-02)

### Prepared target and replay surface

The tested SCM revision was `9e4fe5aff3b001a187576ac24cf9364eac55664d`.
Images were built from that exact source and fresh API-credit registry,
storefront, credits-service and sample-app state republished the listings.
The payment authority was the real Arkhai payments HTTP service in development
mode, backed by Formance v2.4.14 and Postgres 16, in a separate disposable
container project. No hosted credentials, Stripe, WorkOS, payment double or
in-process receipt fixture was used.

The buyer used an Ed25519 marketplace profile with only payments enabled and no
wallet; the seller used an Ed25519 principal trusted by both the storefront and
credits service. Fresh test balances were issued through the authority's
operator funding route: buyer 1,000,000,000 USD/6 base units, seller one base unit
for account existence. These were deterministic development personas, never
public-network accounts or credentials.

Both roles pinned the same service signer, fee of 250 bps, dispute authority,
`livemode=false` and `development_auth=true`. The seller published a USD/6 option
at 1,000,000 base units per token with a seven-day hold. The scenario requested
three credits. Scenario policy came from the documented `PAYMENTS` section,
including `SERVICE_URL`, `SERVICE_IDENTITY`, `DISPUTE_AUTHORITY`, `BUYER_ACCOUNT`
and both marketplace credentials; seller policy/publication matched it.

Development authentication stayed on literal loopback. A namespace-local TCP
forwarder in each seller/buyer namespace exposed `http://127.0.0.1:3080`, forwarding
to the same isolated payment authority. This preserves the existing loopback
restriction without giving each container an unrelated localhost service or
relaxing authentication. Host ports were dynamically allocated on loopback;
containers, networks and volumes were run-owned rather than the stock lane's
fixed project. Compose readiness and payment `/health` succeeded from the host,
seller and buyer before pytest. The registry readiness read confirmed a
republished option with `settlement.schema == "arkhai.payments.v1"`.

Replay requires that prepared topology and funding, not just a URL exported on
the host: forward `PAYMENTS` configuration into the runner, and configure the
seller for the same authority. Use the
[shared payment-scenario configuration](../../../e2e-tests/README.md#shared-payment-scenario-configuration).
In the branch-built E2E runner, the public scenario entry point is:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
.venv/bin/pytest -q --tb=short \
  tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py
```

The successful qualification ran those same three existing test functions with
additional read-only payment balance observations. No scenario assertion or SCM
production code was changed. Public CI still readiness-gates this externally
supplied authority; it does not acquire service internals.

### Observations

The final run began pytest at 06:36:48 UTC and reported **3 passed in 5.14s**,
zero errors, failures or skips. All amounts below are USD/6 base units.

| Claim / action | Observed result |
| --- | --- |
| Discover, negotiate, approve and issue | Ordered buyer events reached `payment_approved`, `settlement_submitted`, `credentials_delivered` and successful `run_ended`; the delivered credential made a forecast request returning HTTP 200. |
| Real payment debit and hold | Buyer available fell from 1,000,000,000 to 997,000,000; seller available stayed at one, with a 3,000,000 hold. The pinned-signer receipt quoted gross 3,000,000, fee 75,000 and net 2,925,000; its signature and test mode verified. |
| Re-drive settlement from the run log | Returned the same credit key. The transaction receipt, part state, buyer/seller available balances and matching hold were unchanged. No second debit or issuance was observed. |
| Seller refund | The typed seller route returned `refunded`; payer-authenticated transaction read reported `reversed`, held zero, reversed 3,000,000, released zero and `feePaid=0`. Buyer available returned to 1,000,000,000; seller had no remaining hold. |
| Connected observation gates | Baseline, held, replayed and refunded checkpoints all passed against real HTTP balance/snapshot reads. |
| Repository checks | `make check-comment-hygiene` and `make check-packaging` passed again on the tested source. |
| Teardown | All owned payment and SCM containers, Postgres/SCM volumes and both networks were removed. Final owned inventories were empty; no native Anvil child or HTTP service remained. |

These observations cover the named once-payment scenario, not service restart,
credit exhaustion, hold maturity, rate servicing, mediation execution or hosted
authentication. No browser was needed; this remains nonvisual evidence. Raw
operator/runtime artifacts are not included in this public packet.

### Setup friction

An initial image fetch timed out without the host's working registry proxy;
image transport used that proxy while local scenario traffic bypassed proxies.
The local Podman engine API and the system nftables binary were used for runtime
network operations. One attempt stopped at payment readiness before pytest;
an unchanged fresh retry reached readiness and completed the journey.

An operator-side listing check still read the retired `option["mechanism"]` and
stopped before pytest. Its disposable runner copy was adapted to
`option["settlement"]["schema"]`, retaining the same payment-publication
assertion. The service checkout remained unchanged. The consumer-tooling
follow-up is [#327](https://github.com/arkhai-io/simple-compute-market/issues/327);
no old-shape compatibility reader was added to SCM.
