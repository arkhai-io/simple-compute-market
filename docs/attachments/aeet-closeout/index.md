# Agreed evidence and early termination — closeout evidence

## Scope and setup

Documentation-only closeout of implementation base `64f647d53`, tasks 16.1–16.10.
Task 16.11 archival is intentionally withheld for owner review of permanent docs.
This is nonvisual evidence; no screenshots, browser, server or deployment is used
by closeout. The target is this branch's freshly built public wheelhouse and
package-owned temporary test databases with deterministic development personas.
No external credentials, inherited deployment selector or destructive seed is used.

The independently recorded deployed encounters below used fresh owned stacks,
readiness-gated before pytest, with real local authorities where stated. Those
packets own exact revisions, persona/auth setup, seed state and cleanup evidence;
closeout does not relabel them as public hosted or physical-host qualification.

## Runnable closeout entry

Run at the committed closeout revision in a clean checkout:

```sh
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make check-packaging
make check-architecture-change CHANGE=agreed-evidence-and-early-termination
make test
make check-change CHANGE=agreed-evidence-and-early-termination
```

The shell-local Podman shim supplies Docker-compatible test tooling, not an
alternative payment authority. A successful full `make test` includes package,
application, e2e-harness unit, release-tooling and Helm checks; it does not itself
start all deployed e2e scenarios. Missing deployments remain unrun, not passed.
For a small direct product-surface replay after wheel build:
`make -C kit/deal-servicing first-use` (temporary SQLite and injected authorities).
The existing deployed launch recipes remain in the linked packets.

## Pipeline and deployed evidence matrix

| Boundary | Observed result | Durable packet |
|---|---|---|
| Final production review repairs | Full shim-backed tests at `fd85d9873`, 7m54s; VM 1196 unit/524 integration, one optional RL collection skip; servicing 63 plus typing and 28 focused VM cases | [Confirmation repairs](../aeet-fix3/index.md) |
| `e2e_deal` | Fresh branch-built VM lane, 38/38, zero skips; retains expiry journey and adds repeated delivery surrender, original signed site report before teardown completion, one teardown handle and proven capacity return | [VM delivery](../vm-end-classification/index.md) |
| `e2e_deal_buyer_cli` | Same owned lane, real CLI negotiate/settle/end, 30/30, zero skips; receipt/current view and release are separate | [VM CLI](../vm-end-classification/index.md) |
| `e2e_bare_metal_mock_deal` | Fresh mock-provisioned lane, 39 stages, zero skips; canonical teardown/report and later proven capacity return | [Bare metal](../bare-metal-lifecycle/index.md) |
| `e2e_bare_metal_deal` | Selected but readiness-gated: BARE_METAL.REGISTRY_URL/real target and role-scoped SSH credentials absent. No physical access or revocation qualification | [Release models](../alkahest-release-models/index.md) |
| `e2e_non_erc20_settlement` | VM ERC20 plus native/ERC1155 selection: all 37 selected stages pass after wire-path correction | [Release models](../alkahest-release-models/index.md) |
| `e2e_credits_payment_deal` | Real local payments/ledger, 3/3, zero skips at `9e4fe5aff3b001a187576ac24cf9364eac55664d`; debit, replay and full reversal checked | [Wire cutover](../settlement-option-envelope/index.md) |
| `e2e_bare_metal_payment_deal` | Real local payments/mediation readiness, 3/3, zero skips; approval/commit, replay, reversal and separate physical surrender/release | [Bare-metal payments](../bare-metal-lifecycle/index.md) |
| `e2e_vm_payment_deal` | Fresh images at `eac70ec3d`, real local authorities: 4/4, zero skips; hosted commit/replay, servicing, administrator end with one signed case, refund and proven release | [Hosted VM](../aeet-vm-hosted/index.md) |
| Published contracts/fixtures | Signed snapshot and payment vectors, both mediation signature schemes, 14 producer ruling traces; library evidence, not deployed monetary execution | [Payments contract](../payments-contract-foundation/index.md), [Mediation](../agreed-evidence-mediation/index.md) |
| Producer/outbox and domain recovery repairs | Permanent CI tests cover atomic event/outbox, all causes, crash/ack/pull/rotation/parking; full tests at `0143c1ea9` pass 7m27s | [Combined re-review](../aeet-rereview-domain/index.md) |

All packets report cleanup of their owned deployments. No closeout deployment was
started and none is left running.

## Closeout rerun

- Fresh-wheelhouse `make check-packaging`: pass, including lock currency, install,
  Python/layout and layer/scope/dependency/kind checks.
- `make check-architecture-change CHANGE=agreed-evidence-and-early-termination`:
  pass, no owned exception/override row.
- `make check-agent-skills`, `make check-comment-hygiene`, `make check-change-index`:
  pass.
- Full shim-backed `make test`: pass in 7m55s on `0d861e80c`, with the prescribed
  proxy environment. This freshly rebuilt checkout ran through package/application,
  e2e-harness unit, release-tooling and Helm structural/render checks. The existing
  optional RL/Torch collection skip remains; this is not a deployed e2e rerun.

## Explicitly unrun and accepted limits

No fresh deployed lane, real bare-metal host, public hosted-development mediation
upgrade, standalone domain typing sweep, rate-stop/funding or monetary ruling
execution was run by closeout. Earlier local once-only case filing/observation
passes do not establish those outcomes. Rate execution belongs to
spot-deals-through-arkhai-payments; ongoing/revised-remedy scenarios to
converge-ongoing-compute-leases; hosted rate qualification to
activate-per-period-compute-servicing. The absent real-host target is an external
qualification prerequisite, not a mock acceptance claim.

The permanent lifecycle companion records pinned dispute origin/key rotation,
VM/bare-metal respondent lifetime and term-end differences, absent storefront prune
trigger and the per-deal cursor hold. These accepted limits are not silently
waived by green tests. Archival and its spec synchronization remain owner work.
