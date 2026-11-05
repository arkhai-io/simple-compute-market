# Hosted VM commit, servicing and end-case qualification

Nonvisual implementer qualification of O-F18, not independent acceptance.
Starting revision: **83e899ebb**. Final production, fresh images and deployed
scenario: **eac70ec3d**. No screenshots apply; evidence is authenticated HTTP,
canonical client operations and explicit lifecycle cycles.

## Required and prepared target

Required and prepared: a new invocation-owned disposable checkout of this
branch, freshly rebuilt VM-lane images, empty named volumes, isolated networks
and remapped loopback ports, with real local payment and mediation authorities,
ledger and Postgres. No inherited deployment selector was reused or seeded.
Provisioning uses the committed mock executor, not real KVM or SSH. The local
Anvil chain is real. Images were rebuilt after the mediation repair below and
contain the earlier admin-end ordering repair.

Buyer, seller, administrator and site use the VM lane's deterministic public
development personas and role-bound signatures; payment accounts are disposable
and funded for the encounter. Authority source stayed read-only and unchanged.
Namespace-local forwarders preserve SCM's loopback-only payment-development-auth
guard. A disposable authority-side bridge translates party-scoped fixture bearer
credentials to mediation's development account authentication. SCM's credential
checks and proof verification are unchanged; no production auth is claimed.

The seller opts into the exact registry-recommended mediation authority and
has an identity-bound `[[DisputeCredential]]` whose `api_key_env` references
`VM_MEDIATION_SELLER_TOKEN`. Only the variable name is recorded here. The accepted
option fixes a 300-second delivery deadline, 1,296,000-second dispute window and
unbounded case hold; payment `window=P7D` is separate. No rate part is used.

## Reproduction and observed readiness

Build the committed branch in an owned checkout:

```sh
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make build-e2e-vm IMAGE_SUFFIX=-fixE
```

Render `compose.vms.yml` and `compose.vms-local.yml` with the output of
`make -s --no-print-directory e2e-vms-dev-env`, assigning a new project, fresh
volumes and free loopback ports. Select the fresh suffixed images, not old bare
tags. Prepare actual authorities using the
[local authority recipe](../aeet-s8-integration/index.md#live-local-payment-replay-requirements)
and [shared payments configuration](../../../e2e-tests/README.md#shared-payment-scenario-configuration),
plus the seller credential reference. A source checkout is not deployment readiness.

Before pytest, owned Compose health, payment health from host/seller/buyer,
mediation health/description and the authenticated signed registry publication
all passed. Publication uses `option["settlement"]["schema"]` per
[#327](https://github.com/arkhai-io/simple-compute-market/issues/327), and checks
the exact mediation authority and lifecycle terms above.

Mount the lane config and `PAYMENTS` profile into the branch-built runner and the
committed [readiness script](../vm-end-classification/readiness.py) at
`/runtime/readiness.py`. These exact first-use commands were personally run
from `/app`; `VM_READY` appeared before pytest started:

```sh
ACTIVE_PROFILES=docker,payments CONFIG_DIRECTORY=/app/config PYTHONPATH=/app \
  .venv/bin/python /runtime/readiness.py
ACTIVE_PROFILES=docker,payments CONFIG_DIRECTORY=/app/config PYTHONPATH=/app \
  .venv/bin/pytest -p no:cacheprovider -q --tb=short \
  tests/e2e/roles/scenarios/vms/test_vm_payment_deal.py
```

Not-ready stops at setup, not a product encounter. No private launcher, raw
operator log, credential or external runtime artifact is published here.

## Stages actually run

Final deployed result: **4 passed in 10.09 seconds, zero skips**.

| Stage | Action and observed result |
| --- | --- |
| Hosted commit/delivery | Signed hosted-only publication; negotiation accepts the selected option; settlement is pending before approval. `PaymentApproval` verifies the Agreement/mandate and receipt. Canonical `LifecycleClient.commit` is accepted. Releasing the controlled create gate yields active fulfillment, credentials and one part holding its gross amount. |
| Replay and servicing | Same-key commit creates no new fulfillment. Explicit `settlement-servicing` cycle runs; buyer read retains the transaction, running payment and active delivery. Before its first case, mediation does not know the Agreement; its absent record is not asserted to be verified empty history. |
| Operator end and case | With teardown gated, unentitled administrator end records attribution and independently files at mediation. Retry retains the same end. A second servicing cycle/read returns one case, a verified signed filed record, one site report and `tearing_down`; held money is unchanged, with no inferred local remedy. |
| Refund and proven release | Seller refund reverses the whole held payment; held/released amounts become zero. Delivery remains `tearing_down` until provider completion and the separate capacity-return callback. Repeated cycles preserve end/report and exactly one reservation-scoped release event. |

The cycles' `processed: 0` counts emitted observations, not whether the cycle ran;
case and signed-read assertions establish the result. This does not claim an
independent respondent-answer journey, rate-stop/funding behavior or real hardware.

## Defect and regression

First delivery-end filing read the authority record to adopt any existing
semantic case. The real authority learns an Agreement on its first filing and
returns **HTTP 404 `invalid_request`** beforehand. The adapter rejected the
command before its first write; the fake's initially empty page hid the defect.

`eac70ec3d` permits that specific initial missing record **only while preparing
the original filing**. Ordinary reads still fail closed; later missing pages,
single-writer reservation and signed filed-entry verification are unchanged.
The authority still validates the Agreement and alone decides effects. The kept
semantic-recovery regression now models initial 404, confirms general reads
fail closed, files once and adopts that same case. A temporary old-call-path
diagnostic fails (`rejected != accepted`); repaired mediation has **45 passed**,
clean typing and published-contract/vector/generated-model checks.

Earlier failures are not counted as passing. Disposable setup needed the correct
image tag and complete runner mount. New assertions were corrected to read
credentials from settlement status (not its wait response) and lease `active`
(not reservation `leased`). The preliminary pre-case read no longer incorrectly
demands verified mediation history before registration; the post-case read still
requires accepted, verified authority evidence. No product guard or pre-existing
assertion was weakened.

## Validation and cleanup

- Focused e2e harness: **319 passed**; mediation: **45 passed** and typing clean.
- Fresh VM image build at **eac70ec3d**, readiness and all four deployed stages: pass.
- Comment hygiene, fresh-wheelhouse packaging (architecture/locks included), and
  pinned OpenSpec 1.14.0 strict change validation: pass.
- Full shim-backed **`make test` passes in 7m51s** on the final production
  source, including package/application regressions, e2e harness, release tooling
  and Helm structural/render checks. The existing optional Torch collection skip
  remains; the required hosted VM encounter has zero skips.

Every attempted deployment was torn down: forwarders before namespace owners,
then owned containers, named volumes and networks. Final owned inventories are
empty. Both builds reproduced [#326](https://github.com/arkhai-io/simple-compute-market/issues/326);
each exact owned native Anvil child was stopped through its build supervisor,
without pattern kills. Authority source is unchanged. No server, tunnel,
browser or deployment remains; image caches are not resident services.

Permanent promotion remains reviewed section 16 closeout in the existing
lifecycle/VM contracts and architecture. The mediation README describes initial
filing versus read evidence now. No new remedy policy, authority, schema,
dependency or lock is introduced.
