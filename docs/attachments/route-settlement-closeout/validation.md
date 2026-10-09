# Merged-tree validation

This record replaces the closeout's replay scripts. The scripts pinned wheel
versions and named individual test files, so each later merge or rename broke
them. Validation instead runs each project's own `make` targets, and every
finding the audits recorded is encoded as a committed regression test, listed
below. Counts are from the tree after `dev` was merged into the campaign
branch and section 10 of the change's tasks was implemented.

## How to run

From the repository root:

```sh
make dist
make test-core test-kits test-bare-metal test-apicredits test-vms-domain test-vms-buyer test-e2e-unit
make -C kit/arkhai-payments test
make check-comment-hygiene check-packaging
make check-doc-citations CHANGE=route-settlement-by-mechanism
```

Each project target reinitializes its environment from `.dist` before testing,
so cross-project dependencies are always the built wheels. The end-to-end
lanes run in the `E2E` GitHub workflow (`make test-e2e-vm`,
`make test-e2e-bare-metal`).

## Findings and the tests that hold them

| Finding | Regression test |
|---|---|
| F1: bare-metal Alkahest recovery authorized a reclaimed journal | `domains/bare_metal/storefront/tests/test_http_settlement.py::test_alkahest_recovery_refuses_non_active_journal_before_physical_effects` |
| F2: standalone VM negotiation chose mechanism behavior outside its entry | `domains/vms/buyer/tests/test_negotiate_stage_dispatch.py` |
| F3: VM evidence storage accepted malformed verified records | `domains/vms/storefront/tests/unit/test_vm_evidence_validation.py` |
| Credits authority grant schema carries no mechanism or escrow columns | `domains/apicredits/service/tests/integration/test_migrations.py` |
| B1: `market credits negotiate` bypassed the declared buyer table | `domains/apicredits/buyer/tests/test_negotiate_cli.py`; against the served storefront, `domains/apicredits/storefront/tests/integration/test_credits_negotiate_cli.py` |
| B2: accepted contact reveal and re-read required current enablement | `domains/bare_metal/storefront/tests/test_http_introductions.py::test_accepted_introduction_survives_contact_disable` |
| Bare-metal servicing hooks follow the accepted Agreement's seller entry | `domains/bare_metal/storefront/tests/test_obligation_servicing.py` |
| A fresh selection of a priced option bargains its amount | `kit/policy/tests/unit/test_selection_scalar.py`; against the served storefront, `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py` |
| A materialized Alkahest plan is checked against the selected entry | `kit/alkahest/tests/unit/test_selected_escrow_plan.py` |

## Merged-tree counts

Every suite below passed, with no failures. Each environment was rebuilt from a
fresh `make dist`.

| Project | Passed |
|---|---:|
| `core` | 126 |
| `core/buyer` | 134 |
| `core/storefront` | 190 (2 skipped) |
| `domains/vms/buyer` | 197 |
| `domains/vms/storefront` unit | 1073 (1 skipped) |
| `domains/vms/storefront` integration | 347 |
| `domains/bare_metal/buyer` | 11 |
| `domains/bare_metal/storefront` | 296 |
| `domains/apicredits` (domain) | 41 |
| `domains/apicredits/buyer` | 24 |
| `domains/apicredits/storefront` | 126 |
| `domains/apicredits/service` | 70 |
| `kit/arkhai-payments` | 84, plus 4 published vectors, current generated models and mypy |
| `kit/alkahest` unit | 200 |
| `kit/settlement-runtime` | 127 |
| `kit/policy` | 63 |
| `e2e-tests` unit | 22 |

The VM storefront integration count excludes `test_publication_loop.py` (see
below) and `test_alkahest.py`, which needs a local Anvil chain and runs in the
end-to-end lanes instead.

## End-to-end

The `E2E` workflow on this branch, after the merge:

| Run | Outcome |
|---|---|
| [37917911937](https://github.com/arkhai-io/simple-compute-market/actions/runs/37917911937) | Bare metal passed. VM failed four scenarios: three buyer-CLI openings that selected a priced Alkahest option carried no amount, and the force-accept scenario still opened with an escrow proposal |
| [37935819676](https://github.com/arkhai-io/simple-compute-market/actions/runs/37935819676) | Bare metal passed. VM failed four later stages: three lease checks looked a deal's reservation up by escrow, and the force-accept listing advertised a stub escrow contract |
| [37937212352](https://github.com/arkhai-io/simple-compute-market/actions/runs/37937212352) | Passed: VM and API credits 135 passed, 3 skipped; bare metal 16 passed |

`dev` itself passed the same workflow in
[37936939239](https://github.com/arkhai-io/simple-compute-market/actions/runs/37936939239),
so every failure above was this branch's and is fixed.

## Known pre-existing failures

`domains/vms/storefront/tests/integration/test_publication_loop.py` hangs when
run in sequence with the other integration modules and has five failing tests
on its own. Both reproduce identically on the tree `dev` carried before this
merge, so they are excluded from the counts above rather than attributed to
this change.
