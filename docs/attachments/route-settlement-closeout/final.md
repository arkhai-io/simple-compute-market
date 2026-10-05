# Joined settlement closeout after repairs

Target: checkout-owned `closeout-final`, campaign production `4d04fbf7` plus import/comment repair `2d22f6e4`. Mode: auditing then documentation closeout. This packet supersedes the original audit's findings disposition, not its independent observations. No behavioral repairs or new permanent tests were made by closeout. Visual: false; screenshots: none.

## Result

Clean build/reinit, every original named suite and every repair-worker entry passed. Original verifier F1/F2/F3 and review fixes hold under their committed replays. Storage and protected recovery confirmation tasks 6.1/6.2 are complete. **8.2 remains blocked** by standalone API-credit negotiation and disabled-contact accepted reveal/re-read; see [final-inventory.md](final-inventory.md). Passing suites do not substitute for this broader control-flow criterion.

## Reproduce and prepared target

From the repository root:

```sh
bash docs/attachments/route-settlement-closeout/replay.sh &&
bash docs/attachments/route-settlement-closeout/replay-repairs.sh
```

The first command cleans `.dist`, builds all wheels and reinits core buyer/storefront, VM buyer/storefront, bare-metal storefront, API-credit buyer/storefront/service, payments and e2e environments. Core, bare-metal buyer and API-credit domain test environments sync/reinstall from wheels. Bare-metal role inspection installs non-editable wheels. The second reruns all four repair packets' entries, including the original schema/reclaimed diagnostics and VM negotiation inspection. Cross-project internal dependencies use wheels, never injected sibling source. API-credit imports moved by closeout are exercised after full rebuild and buyer reinit.

Actual prepared target: installed local CLI/library and in-process ASGI authority with fresh owned temporary SQLite/run logs. Synthetic canonical buyer/seller/service identities and an ephemeral operator key; no external credentials or inherited deployment selector. API-credit first use seeds 100 units of `svc-quota` and observes `/health=200` before effects. Entry scripts create, reopen and remove their own databases. No live payment/site/provider/auth target was supplied or made ready; the three complete-deal deployment scenarios remain unavailable, not failed/mocked live qualifications.

## Suite counts

Counts in separate rows overlap; do not sum repeat runs.

| Original joined primary selection | Passed |
|---|---:|
| Core carriers/domain/import boundaries | 15 |
| Core buyer dispatch/acceptance/policy/priceless/recovery | 51 |
| Core storefront registry/lifecycle/publication | 24 |
| VM buyer focused group | 101 |
| VM storefront focused group plus all integrations | 246 |
| Bare-metal buyer | 9 |
| Bare-metal 15 storefront files | 90 |
| API-credit buyer | 17 |
| API-credit seven storefront files | 60 |
| API-credit typed client/HTTP/issuance evidence | 25 |
| Credits authority key/API/migrations | 35 |
| Payments kit | 7 |

**680 passes** in the original primary groups. Isolated integration slices: VM **30**, bare metal **25**, credit client **4**, credits-service HTTP **3**. Storage slices: VM **12**, bare metal **6**, credit storefront **14**, credits service **13**. Four published payment vectors, generated models and core/payment mypy (**6/9 files**) pass. Domain/core-role packages declare no additional static target.

| Repair entry | Passed |
|---|---:|
| Core full carrier/boundary group; buyer group; actual VM accepted-run CLI | 26 / 51 / 2 |
| VM expanded buyer/storefront repair replay | 105 / 270 |
| API-credit payment recovery + coordinator + issuance/private repository | 20 |
| API-credit buyer/domain/service HTTP re-drive | 17 / 25 / 3 |
| Bare-metal settlement/HTTP/physical affected group | 26 |
| Bare-metal domain/runtime composition | 11 |
| Bare-metal authoritative recovery-only group | 10 (6 deselected) |

The expanded file selections cover **723 distinct passing cases** across the joined primary groups plus repaired carrier/VM/API-credit additions, not the sum of all repeated commands. No behavioral suite failure, skip or xfail was reported. Temporary import probes deliberately failed as described below and are not test results.

## Observations

- VM: pending/0 deliveries → provisioning → ready/1; payment escrow rows 0. Actual accepted-run CLI preserves the recorded mechanism/reference with and without a stray proposal.
- API credits: health 200; pending grants 0 → lost-ack 1 → final 2, balance 5, payment escrows 0, payment polls 3. Owner-only private retrieval and secret-free top-up/exact retry hold; temporary databases removed.
- `inspect_vm_schema.py`: malformed verified storage refuses `ValueError: verified VM evidence requires a sha256 Agreement digest`; fresh evidence/delivery SQL and cleanup printed.
- `reclaimed_gate.py`: refuses `SettlementRequestError: verified settlement is no longer active`; no physical effect.
- VM standalone negotiation inspection: old config-key, payer-helper, wallet/chain and proposal-absence dispatch absent; all four selected-stage hooks present. Fresh CLI cases are in the 105-pass group.
- API-credit verified receipt recovery survives unavailable polling; prepared Alkahest delivery does not perform a second preparation; neutral failure release correlates by negotiation. Bare-metal recovery rechecks authoritative chain state/index and refuses inactive journal variants before physical effects.

## Import and comment closeout

Actual diff from `9233a332` was scanned for added/touched local imports, comments and docstrings. API-credit settle imports moved to module scope and its real buyer/recovery/client suites passed. Three local imports remain with concrete reasons: VM recovery table import reproduced `ChainSettings` circular import after wheel rebuild; VM delivery connectivity import reproduced a `fulfill_vm_obligation` cycle; VM publication's domain runtime loads process-global operator config and stays deliberately lazy for help/pure payload construction. Reasons are local in code. Historical job-hook wording was replaced by the current recovery invariant. No production reference to active change documents was introduced. `make check-comment-hygiene` passes.

An initial import probe used a nonexistent leaf `dist` target and was corrected to `make -C domains dist-buyer`; uninstalled guessed import names were corrected to the declared wheel module. These are operator command corrections, not product regressions. All temporary module-scope probes were reverted before final builds/tests.

## Documentation and residual ownership

`openspec validate route-settlement-by-mechanism --strict` and
`openspec validate --specs --strict` both pass, as does final comment hygiene.
Informational long-requirement notices are not validation failures.

All six deltas and existing architecture companions are promoted; repository architecture, Goal 6 and active change status describe both repaired behavior and the remaining inventory gaps. `design.md` records exact destinations. No new capability companion was needed; the capability index is unchanged. Four repair packets now live under repo-level attachments: [core](../core-settlement-closeout/index.md), [bare metal](../baremetal-recovery-gate/index.md), [API credits](../apicredits-settlement-repair/index.md), [VM](../vm-settlement-findings/index.md).

- Quota-ledger `escrow_uid` correlation API rename: `openspec/changes/move-escrow-into-alkahest/proposal.md`.
- Cross-domain helper duplication (review F7): [#261](https://github.com/arkhai-io/simple-compute-market/issues/261), idea.
- Credits service dev wheel closure (review F9): [#262](https://github.com/arkhai-io/simple-compute-market/issues/262), idea; runtime authority coupling is not alleged.
- Reinit lock churn [#257](https://github.com/arkhai-io/simple-compute-market/issues/257), core asyncio warning [#258](https://github.com/arkhai-io/simple-compute-market/issues/258), Pydantic schema warnings [#259](https://github.com/arkhai-io/simple-compute-market/issues/259), TestClient deprecation [#260](https://github.com/arkhai-io/simple-compute-market/issues/260) remain visible. Generated lock churn was restored only after execution; tested environments were not resynced.
- Process completion could not preview retained logs again; `process logs` and direct `read`/`grep` recovered counts without rerunning. Existing [pi log-preview owner](https://github.com/mlegls/mlegls-pi/blob/main/docs/issues/managed-process-retained-logs-disappear-during-test-run.md) applies; retained logs did not disappear.

No server, browser, container, tunnel or external deployment was started. Temporary databases, engines, run logs and coordinators were cleaned. All supervised work finished; no external resource remains. The change remains active and is not archived.
