# Settlement-option envelope — implementation evidence

## Scope and contract

This packet covers tasks 2.5b and 2.5c of `agreed-evidence-and-early-termination`.
It records implementer self-checks and existing regression suites, not independent
acceptance. The tested tree is the wire-flip commit introducing this packet;
reviewed-closeout promotion remains in the change's specification deltas.
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
No target was supplied for this run. Do not treat its successful process exit
as a successful payment journey.

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
| API-credit hosted payment deal | **Unobservable**: all 3 cases skip at the existing readiness gate, `blocked: PAYMENTS.SERVICE_URL not configured`. Required end-to-end payment acceptance is pending. |

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

Task 2.5 remains incomplete solely on the hosted payment lane: configure a ready
external payment authority and rerun `e2e_credits_payment_deal`. Its absence is
an environment prerequisite, not an old mediation-projection failure.
Deterministic isolated payment-lane infrastructure is owned by
[`add-arkhai-payments-lane-double`](../../../openspec/changes/add-arkhai-payments-lane-double/).
The optional Alkahest release-model section 4 is outside this implementation.

All owned lane containers, volumes and networks were removed. Native Anvil
children left by the lane scenarios were stopped by their owned process groups;
no Anvil child, server, tunnel, or browser remains from this work.
